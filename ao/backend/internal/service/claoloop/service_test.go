package claoloop

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

type absentController struct{ Chat }

func (absentController) HasLiveChatController(domain.SessionID) bool { return false }

func contract() Request {
	return Request{ID: "mission-test", ProjectID: "project-test", Objective: "change", AllowedPaths: []string{"**"}, Criteria: []Criterion{{ID: "AC1", Description: "accepted"}}, GateCommands: []string{"python check.py"}, GateTimeout: 10, Agent: domain.HarnessOpenCode}
}

func TestCLAORecoveryUsesDurableNativeOwnerAndDoesNotReplay(t *testing.T) {
	for _, state := range []string{"active", "exited", "not_spawned"} {
		t.Run(state, func(t *testing.T) {
			dir := t.TempDir()
			st, err := sqlitetest.Open(dir)
			if err != nil {
				t.Fatal(err)
			}
			ctx := context.Background()
			now := time.Now().UTC()
			req := contract()
			if err = st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: dir, RegisteredAt: now}); err != nil {
				t.Fatal(err)
			}
			var persistedID domain.SessionID
			if state != "not_spawned" {
				activity := domain.ActivityActive
				if state == "exited" {
					activity = domain.ActivityExited
				}
				var created domain.SessionRecord
				created, err = st.CreateSession(ctx, domain.SessionRecord{ID: "native-worker", ProjectID: req.ProjectID, Kind: domain.KindWorker, Harness: req.Agent, Mode: domain.SessionModeChat, Activity: domain.Activity{State: activity, LastActivityAt: now}, Metadata: domain.SessionMetadata{CLAOMissionID: req.ID, WorkspacePath: dir}, CreatedAt: now, UpdatedAt: now})
				if err != nil {
					t.Fatal(err)
				}
				persistedID = created.ID
			}
			m := Mission{Request: req, State: "SPAWNING", Revision: 1, Operations: []Operation{{ID: "spawn-intent", Kind: "spawn", State: "IN_FLIGHT"}}, UpdatedAt: now.Format(time.RFC3339Nano)}
			if err = st.CreateCLAOMission(ctx, record(m)); err != nil {
				t.Fatal(err)
			}
			if err = st.Close(); err != nil {
				t.Fatal(err)
			}
			st, err = sqlite.Open(dir)
			if err != nil {
				t.Fatal(err)
			}
			defer st.Close()
			svc := New(ctx, st, nil, absentController{}, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
			if err = svc.Recover(); err != nil {
				t.Fatal(err)
			}
			got, err := svc.Get(ctx, req.ID)
			if err != nil {
				t.Fatal(err)
			}
			if state == "not_spawned" {
				if got.State != "FAILED" {
					t.Fatalf("no worker: %+v", got)
				}
				return
			}
			if got.State != "UNKNOWN" || got.SessionID != persistedID || got.Operations[0].State != "UNKNOWN" {
				t.Fatalf("lost ACK recovery: %+v", got)
			}
			other := req
			other.ID = "other-mission"
			if _, err = svc.Create(ctx, other); err == nil || !strings.Contains(err.Error(), "未知") {
				t.Fatalf("unknown must block before spawn: %v", err)
			}
			if err = svc.Recover(); err != nil {
				t.Fatal(err)
			}
			receipt, err := svc.Cancel(ctx, req.ID)
			if err != nil || !receipt.CancelRequested {
				t.Fatalf("receipt: %+v %v", receipt, err)
			}
			for i := 0; i < 100; i++ {
				svc.mu.Lock()
				running := svc.running[req.ID]
				svc.mu.Unlock()
				if !running {
					break
				}
				time.Sleep(time.Millisecond * 5)
			}
			got, err = svc.Get(ctx, req.ID)
			if err != nil {
				t.Fatal(err)
			}
			want := "UNKNOWN"
			if state == "exited" {
				want = "CANCELLED"
			}
			if got.State != want {
				t.Fatalf("stop state = %s, want %s", got.State, want)
			}
			if len(got.Operations) != 2 || got.Operations[0].ID != "spawn-intent" {
				t.Fatalf("unexpected replay: %+v", got.Operations)
			}
		})
	}
}

type failedReceiptStore struct{ Store }

func (failedReceiptStore) SaveCLAOMission(context.Context, domain.CLAOMissionRecord) error {
	return errors.New("injected receipt failure")
}

func TestCLAOCancelReceiptFailureHasNoStopSideEffect(t *testing.T) {
	st := sqlitetest.MustOpen(t)
	ctx := context.Background()
	req := contract()
	if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if err := st.CreateCLAOMission(ctx, record(Mission{Request: req, State: "UNKNOWN", Revision: 1})); err != nil {
		t.Fatal(err)
	}
	svc := New(ctx, failedReceiptStore{st}, nil, nil, nil, slog.Default())
	if _, err := svc.Cancel(ctx, req.ID); err == nil {
		t.Fatal("receipt write must fail")
	}
	m, err := svc.Get(ctx, req.ID)
	if err != nil {
		t.Fatal(err)
	}
	if m.CancelRequested || len(svc.running) != 0 || len(m.Operations) != 0 {
		t.Fatal("failed durable receipt produced a stop action")
	}
}
