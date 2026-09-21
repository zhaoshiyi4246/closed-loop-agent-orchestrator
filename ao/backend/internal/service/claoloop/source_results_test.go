package claoloop

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

func TestNativeSavedPackageOwnershipSurvivesWorkspaceLoss(t *testing.T) {
	ctx := context.Background()
	store := sqlitetest.MustOpen(t)
	if err := store.UpsertProject(ctx, domain.ProjectRecord{ID: "project-test", Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	dataRoot := t.TempDir()
	content := []byte("frozen package bytes")
	hash := sha256.Sum256(content)
	identity := strings.Repeat("a", 64)
	pack := ResultPackage{Identity: identity, SHA256: hex.EncodeToString(hash[:]), Bytes: int64(len(content)),
		BaseCommit: strings.Repeat("b", 40), ResultCommit: strings.Repeat("c", 40), Accepted: true}
	m := Mission{Request: contract(), State: "DONE", Revision: 1, Workspace: filepath.Join(t.TempDir(), "missing"),
		Base: pack.BaseCommit, ResultHead: pack.ResultCommit, Exports: []ResultPackage{pack}}
	if err := store.CreateCLAOMission(ctx, record(m)); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(dataRoot, "clao", "missions", m.Request.ID, "exports")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, identity+".zip")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	svc := New(ctx, store, nil, nil, PythonAcceptance{DataDir: dataRoot}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	got, err := svc.Download(ctx, m.Request.ID, identity)
	if err != nil || string(got) != string(content) {
		t.Fatalf("saved package requires no workspace: %q %v", got, err)
	}
	b := m
	b.Request.ID = "mission-other"
	b.Exports = nil
	if err := store.CreateCLAOMission(ctx, record(b)); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Download(ctx, b.Request.ID, identity); err == nil {
		t.Fatal("another mission adopted a package")
	}
	for _, pair := range [][2]string{{"../mission-test", identity}, {m.Request.ID, "../" + identity}, {m.Request.ID, strings.Repeat("f", 64)}} {
		if _, err := svc.Download(ctx, pair[0], pair[1]); err == nil {
			t.Fatal("invalid or unrecorded package was read")
		}
	}
	if err := os.WriteFile(path, []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Download(ctx, m.Request.ID, identity); err == nil {
		t.Fatal("tampered package was accepted")
	}
}

type materialFault struct {
	Acceptance
	value ResultPackage
	err   error
}

func (f materialFault) ExportResult(context.Context, Mission) (ResultPackage, error) {
	return f.value, f.err
}

func TestNativeExportRequiresDurableReceiptAndDoesNotRewriteVerdict(t *testing.T) {
	ctx := context.Background()
	native := sqlitetest.MustOpen(t)
	if err := native.UpsertProject(ctx, domain.ProjectRecord{ID: "project-test", Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	store := &receiptFaultStore{Store: native, native: native}
	m := Mission{Request: contract(), State: "FAILED", Reason: "Gate failed", Revision: 1,
		Base: strings.Repeat("b", 40), ResultHead: strings.Repeat("c", 40)}
	if err := store.CreateCLAOMission(ctx, record(m)); err != nil {
		t.Fatal(err)
	}
	pack := ResultPackage{Identity: strings.Repeat("a", 64), BaseCommit: m.Base, ResultCommit: m.ResultHead}
	svc := New(ctx, store, nil, nil, materialFault{value: pack}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	store.failNext = true
	if _, err := svc.Export(ctx, m.Request.ID); err == nil {
		t.Fatal("failed receipt must not return successful export")
	}
	saved, _ := svc.Get(ctx, m.Request.ID)
	if len(saved.Exports) != 0 || saved.State != "FAILED" || saved.Reason != m.Reason {
		t.Fatal("export changed final facts or persisted an unsuccessful receipt")
	}
	for range 2 {
		if _, err := svc.Export(ctx, m.Request.ID); err != nil {
			t.Fatal(err)
		}
	}
	saved, _ = svc.Get(ctx, m.Request.ID)
	if len(saved.Exports) != 1 || saved.State != "FAILED" || saved.Exports[0].Accepted {
		t.Fatalf("export receipts or verdict inconsistent: %#v", saved)
	}
	svc.acceptance = materialFault{err: errors.New("generation failed")}
	if _, err := svc.Export(ctx, m.Request.ID); err == nil {
		t.Fatal("generation failure was hidden")
	}
	saved, _ = svc.Get(ctx, m.Request.ID)
	if len(saved.Exports) != 1 {
		t.Fatal("failed generation removed the previously saved package")
	}
}
