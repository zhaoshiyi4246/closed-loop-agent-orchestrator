package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

type legacyBoundary struct {
	Acceptance
	calls       int
	checks      int
	response    LegacyResponse
	callError   error
	onCall      func()
	lastRequest map[string]any
}

func (c *legacyBoundary) Legacy(ctx context.Context, in map[string]any) (LegacyResponse, error) {
	c.lastRequest = in
	if in["action"] == "check" {
		c.checks++
		return LegacyResponse{OK: true, Configured: true}, nil
	}
	c.calls++
	if c.onCall != nil {
		c.onCall()
	}
	return c.response, c.callError
}
func legacyProfile(service string) json.RawMessage {
	return json.RawMessage(`{"id":"same-name","service":"` + service + `","credential_ref":"same-ref","model":"saved-model"}`)
}
func connectionRecord(id, service string) domain.CLAOImportRecord {
	doc, _ := json.Marshal(LegacyConnection{Name: "same name", Service: service, Model: "saved-model", Compatible: true, Billing: "standard_api", Roles: []string{"planner", "auditor", "verifier"}, Profile: legacyProfile(service)})
	return domain.CLAOImportRecord{ID: id, Kind: "connection", Document: string(doc), CreatedAt: "now"}
}
func legacyService(t *testing.T) (*Service, *legacyBoundary) {
	t.Helper()
	st := sqlitetest.MustOpen(t)
	core := &legacyBoundary{}
	svc := New(context.Background(), st, nil, nil, core, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := st.UpsertProject(context.Background(), domain.ProjectRecord{ID: "project-test", Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	return svc, core
}

func TestCLAOLegacyImportIdentityConflictAndCatalog(t *testing.T) {
	svc, _ := legacyService(t)
	st := svc.store.(legacyStore)
	a := connectionRecord("legacy-glm", "bigmodel_general")
	b := connectionRecord("legacy-kimi", "moonshot_cn")
	ctx := context.Background()
	if err := st.ImportCLAORecords(ctx, []domain.CLAOImportRecord{a, b}); err != nil {
		t.Fatal(err)
	}
	if err := st.ImportCLAORecords(ctx, []domain.CLAOImportRecord{a, b}); err != nil {
		t.Fatal(err)
	}
	view, err := svc.LegacyCatalog(ctx)
	if err != nil || len(view.Connections) != 2 {
		t.Fatalf("catalog: %v %#v", err, view)
	}
	raw, _ := json.Marshal(view)
	if strings.Contains(string(raw), "credential_ref") || strings.Contains(string(raw), "same-ref") {
		t.Fatal("catalog exposes private reference")
	}
	a.Document = `{"changed":true}`
	if err = st.ImportCLAORecords(ctx, []domain.CLAOImportRecord{connectionRecord("legacy-third", "moonshot_cn"), a}); err == nil {
		t.Fatal("conflicting source silently replaced")
	}
	rows, err := st.ListCLAOImports(ctx)
	if err != nil || len(rows) != 2 {
		t.Fatal("partial import committed", err, len(rows))
	}
}

func TestCLAOLegacyFreezeRequiresSpecificServiceAndKeepsSnapshot(t *testing.T) {
	svc, core := legacyService(t)
	ctx := context.Background()
	st := svc.store.(legacyStore)
	if err := st.ImportCLAORecords(ctx, []domain.CLAOImportRecord{connectionRecord("legacy-glm", "bigmodel_general"), connectionRecord("legacy-kimi", "moonshot_cn")}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.freezeLegacyRole(ctx, "verifier", RoleChoice{ConnectionID: "legacy-kimi"}, []string{"bigmodel_general"}); err == nil {
		t.Fatal("GLM consent grants Kimi")
	}
	if core.checks != 0 {
		t.Fatal("unconsented service checked")
	}
	c, err := svc.freezeLegacyRole(ctx, "verifier", RoleChoice{ConnectionID: "legacy-kimi", Model: "untrusted-override"}, []string{"moonshot_cn"})
	if err != nil {
		t.Fatal(err)
	}
	if c.Model != "saved-model" || c.Agent != "" || c.Connection.Service != "moonshot_cn" || !strings.Contains(string(c.Connection.Profile), "same-ref") {
		t.Fatalf("wrong frozen consumer: %#v", c)
	}
	if _, err = svc.freezeLegacyRole(ctx, "worker", RoleChoice{ConnectionID: "legacy-glm"}, []string{"bigmodel_general"}); err == nil {
		t.Fatal("HTTP model admitted as Worker")
	}
	view, _ := svc.LegacyCatalog(ctx)
	view.Connections[0].Model = "new-default"
	if c.Model != "saved-model" || c.Connection.Model != "saved-model" {
		t.Fatal("catalog changed frozen selection")
	}
}

func storeLegacyCall(t *testing.T, svc *Service) (Mission, RoleCall) {
	t.Helper()
	if err := svc.store.(legacyStore).ImportCLAORecords(context.Background(), []domain.CLAOImportRecord{connectionRecord("legacy-kimi", "moonshot_cn")}); err != nil {
		t.Fatal(err)
	}
	req := contract()
	choice := FrozenRole{RoleChoice: RoleChoice{ConnectionID: "legacy-kimi", Model: "saved-model"}, Connection: &LegacyConnection{ID: "legacy-kimi", Service: "moonshot_cn", Billing: "standard_api", Compatible: true, Profile: legacyProfile("moonshot_cn")}}
	call := RoleCall{ID: req.ID + ":verifier", Role: "verifier", State: "STARTING", Choice: choice, Owner: req.ID + ":verifier", InputDigest: "existing-frozen-digest"}
	m := Mission{Request: req, State: "VERIFYING", Roles: map[string]FrozenRole{"verifier": choice}, RoleCalls: []RoleCall{call}, Operations: []Operation{}}
	doc, _ := json.Marshal(m)
	if err := svc.store.CreateCLAOMission(context.Background(), domain.CLAOMissionRecord{ID: req.ID, ProjectID: req.ProjectID, State: m.State, Revision: 1, Document: string(doc), UpdatedAt: "now"}); err != nil {
		t.Fatal(err)
	}
	return m, call
}

func TestCLAOLegacyHTTPResultReuseAndUnknownNoResend(t *testing.T) {
	for _, mode := range []string{"success", "network", "auth", "local_receipt_lost"} {
		t.Run(mode, func(t *testing.T) {
			svc, core := legacyService(t)
			m, call := storeLegacyCall(t, svc)
			core.response = LegacyResponse{OK: true, Text: `{"verdict":"FAIL"}`, ConfirmedModel: "server-model", ModelFactSource: "Chat Completions response.model"}
			if mode == "network" {
				core.response = LegacyResponse{OK: false, Category: "NETWORK", Error: "network result unknown"}
			}
			if mode == "auth" {
				core.response = LegacyResponse{OK: false, Category: "AUTH", Error: "HTTP 401; body withheld"}
			}
			if mode == "local_receipt_lost" {
				fault := &receiptFaultStore{Store: svc.store}
				svc.store = &legacyReceiptFault{receiptFaultStore: fault, legacyStore: svc.store.(legacyStore)}
				core.onCall = func() { fault.failNext = true }
			}
			text, err := svc.semanticLegacy(m.Request.ID, "verifier", call, "complete input")
			if (mode == "success") != (err == nil) {
				t.Fatalf("first result %q %v", text, err)
			}
			landed, readErr := svc.Get(context.Background(), m.Request.ID)
			if readErr != nil {
				t.Fatal(readErr)
			}
			if mode == "success" {
				if landed.RoleCalls[0].ConfirmedModel != "server-model" || landed.Operations[0].State != "CONFIRMED_SUCCESS" {
					t.Fatal("confirmed fact lost")
				}
			} else if mode == "auth" {
				if landed.Operations[0].State != "CONFIRMED_FAILURE" {
					t.Fatal("known failure became unknown")
				}
			} else if landed.Operations[0].State != "UNKNOWN" && landed.Operations[0].State != "IN_FLIGHT" {
				t.Fatal("ambiguous call erased")
			}
			_, _ = svc.semanticLegacy(m.Request.ID, "verifier", landed.RoleCalls[0], "complete input")
			if core.calls != 1 {
				t.Fatal("HTTP side effect repeated", core.calls)
			}
		})
	}
}

type legacyReceiptFault struct {
	*receiptFaultStore
	legacyStore
}

func TestCLAOLegacyReconnectInvalidatesDraftAndFrozenConsumer(t *testing.T) {
	svc, core := legacyService(t)
	ctx := context.Background()
	m, call := storeLegacyCall(t, svc)
	core.response = LegacyResponse{OK: true, Configured: true}
	status, err := svc.ReconnectLegacy(ctx, "legacy-kimi", "isolated-key")
	if err != nil || status.AuthRevision != 1 {
		t.Fatal(status, err)
	}
	raw, _ := json.Marshal(core.lastRequest["profile"])
	if !strings.Contains(string(raw), "native-") || strings.Contains(string(raw), "same-ref") {
		t.Fatal("reconnect overwrites legacy credential", string(raw))
	}
	if _, err := svc.freezeLegacyRole(ctx, "verifier", RoleChoice{ConnectionID: "legacy-kimi"}, []string{"moonshot_cn"}); err == nil {
		t.Fatal("old consent reused")
	}
	before := core.calls
	if _, err := svc.semanticLegacy(m.Request.ID, "verifier", call, "frozen input"); err == nil || core.calls != before {
		t.Fatal("frozen call changed account", err)
	}
	choice, err := svc.freezeLegacyRole(ctx, "verifier", RoleChoice{ConnectionID: "legacy-kimi", ConnectionRevision: 1}, []string{"moonshot_cn"})
	if err != nil || choice.Connection.AuthRevision != 1 {
		t.Fatal(choice, err)
	}
	core.response = LegacyResponse{OK: false}
	if _, err := svc.ReconnectLegacy(ctx, "legacy-kimi", "another-isolated-key"); err == nil {
		t.Fatal("failed save accepted")
	}
	view, _ := svc.LegacyCatalog(ctx)
	if view.Connections[0].AuthRevision != 2 || !view.Connections[0].AuthPending {
		t.Fatal("lost durable failure", view)
	}
	if _, err := svc.freezeLegacyRole(ctx, "verifier", RoleChoice{ConnectionID: "legacy-kimi", ConnectionRevision: 2}, []string{"moonshot_cn"}); err == nil {
		t.Fatal("pending key admitted")
	}
}

func TestCLAOLegacyReceiptFailureBeforeHTTPDoesNotSend(t *testing.T) {
	svc, core := legacyService(t)
	m, call := storeLegacyCall(t, svc)
	svc.store = &receiptFaultStore{Store: svc.store, failNext: true}
	if _, err := svc.semanticLegacy(m.Request.ID, "verifier", call, "input"); err == nil {
		t.Fatal("receipt failure swallowed")
	}
	if core.calls != 0 {
		t.Fatal("sent before durable intent")
	}
}

func TestCLAOLegacyCancellationDiscardsLateResponse(t *testing.T) {
	svc, core := legacyService(t)
	m, call := storeLegacyCall(t, svc)
	core.response = LegacyResponse{OK: true, Text: `{"verdict":"PASS"}`}
	core.onCall = func() {
		_, _ = svc.mutate(m.Request.ID, func(v *Mission) error { v.CancelRequested = true; return nil })
	}
	if _, err := svc.semanticLegacy(m.Request.ID, "verifier", call, "input"); !errors.Is(err, errCancelled) {
		t.Fatal("late response advanced cancel", err)
	}
	landed, _ := svc.Get(context.Background(), m.Request.ID)
	if landed.RoleCalls[0].Text != "" || landed.Operations[0].State != "UNKNOWN" {
		t.Fatal("late response recorded accepted")
	}
}

func TestCLAOLegacyReconnectCannotSelectAnotherServiceOrReference(t *testing.T) {
	svc, core := legacyService(t)
	st := svc.store.(legacyStore)
	if err := st.ImportCLAORecords(context.Background(), []domain.CLAOImportRecord{connectionRecord("legacy-kimi", "moonshot_cn")}); err != nil {
		t.Fatal(err)
	}
	core.response = LegacyResponse{OK: true, Configured: true}
	status, err := svc.ReconnectLegacy(context.Background(), "legacy-kimi", "isolated-test-key")
	if err != nil || status.Status != "configured" {
		t.Fatal(status, err)
	}
	if _, err = svc.ReconnectLegacy(context.Background(), "missing-connection", "isolated-test-key"); err == nil {
		t.Fatal("unknown connection accepted")
	}
	if _, err = svc.ReconnectLegacy(context.Background(), "legacy-kimi", "bad key"); err == nil {
		t.Fatal("invalid credential accepted")
	}
	if core.calls != 1 {
		t.Fatal("unexpected credential operation", core.calls)
	}
}
