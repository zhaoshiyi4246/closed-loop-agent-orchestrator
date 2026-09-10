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
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

type absentController struct{ Chat }

func (absentController) HasLiveChatController(domain.SessionID) bool { return false }

func contract() Request {
	return Request{ID: "mission-test", ProjectID: "project-test", Objective: "change", AllowedPaths: []string{"**"}, Criteria: []Criterion{{ID: "AC1", Description: "accepted"}}, GateCommands: []string{"python check.py"}, GateTimeout: 10, Agent: domain.HarnessOpenCode}
}

// Faults at native Spawn/receipt boundaries; the admission, operation records,
// immutable owner lookup and cancellation use the real service and SQLite.
type spawnFault struct {
	Sessions
	store *receiptFaultStore
	mode  string
	calls int
}

func (f *spawnFault) Spawn(ctx context.Context, cfg ports.SpawnConfig) (domain.SessionRecord, int, int, error) {
	f.calls++
	if f.mode == "before_session" {
		return domain.SessionRecord{}, 0, 0, errors.New("injected pre-session failure")
	}
	rec, err := f.store.native.CreateSession(ctx, domain.SessionRecord{ProjectID: cfg.ProjectID, Kind: domain.KindWorker, Harness: cfg.Harness, Mode: domain.SessionModeChat, Activity: domain.Activity{State: domain.ActivityActive}, Metadata: domain.SessionMetadata{CLAOMissionID: cfg.CLAOMissionID, WorkspacePath: "isolated-workspace", Model: "resolved"}, CreatedAt: time.Now(), UpdatedAt: time.Now()})
	if err != nil {
		return rec, 0, 0, err
	}
	if f.mode == "receipt_lost" {
		f.store.failNext = true
		return rec, 0, 0, nil
	}
	return domain.SessionRecord{}, 0, 0, errors.New("injected native ACK loss")
}

type receiptFaultStore struct {
	Store
	native interface {
		CreateSession(context.Context, domain.SessionRecord) (domain.SessionRecord, error)
	}
	failNext bool
}

func (f *receiptFaultStore) SaveCLAOMission(ctx context.Context, r domain.CLAOMissionRecord) error {
	if f.failNext {
		f.failNext = false
		return errors.New("injected receipt write failure")
	}
	return f.Store.SaveCLAOMission(ctx, r)
}

type sourceOnly struct{ Acceptance }

func (sourceOnly) Source(context.Context, string) (string, error) { return "frozen", nil }

type readyChat struct{ absentController }

func (readyChat) PreflightChat(context.Context, domain.AgentHarness, ports.PermissionMode) error {
	return nil
}

func TestCLAOSpawnFailureReceiptAndNewAttempt(t *testing.T) {
	for _, mode := range []string{"before_session", "ack_lost", "receipt_lost"} {
		t.Run(mode, func(t *testing.T) {
			st := sqlitetest.MustOpen(t)
			ctx := context.Background()
			req := contract()
			if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
				t.Fatal(err)
			}
			store := &receiptFaultStore{Store: st, native: st}
			spawn := &spawnFault{store: store, mode: mode}
			svc := New(ctx, store, spawn, readyChat{}, sourceOnly{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
			wait := func() {
				t.Helper()
				for i := 0; i < 200; i++ {
					svc.mu.Lock()
					running := len(svc.running) > 0
					svc.mu.Unlock()
					if !running {
						return
					}
					time.Sleep(5 * time.Millisecond)
				}
				t.Fatal("run did not finish")
			}
			receipt, err := svc.Create(ctx, req)
			if err != nil || receipt.State != "SPAWNING" {
				t.Fatalf("durable acceptance: %+v %v", receipt, err)
			}
			wait()
			m, err := svc.Get(ctx, req.ID)
			if err != nil {
				t.Fatal(err)
			}
			want := "UNKNOWN"
			if mode == "before_session" {
				want = "FAILED"
			}
			if m.State != want || len(m.Operations) != 1 || spawn.calls != 1 {
				t.Fatalf("%+v; spawn count %d", m, spawn.calls)
			}
			if mode == "before_session" {
				if m.SessionID != "" || m.Operations[0].State != "CONFIRMED_FAILURE" || !strings.Contains(m.Reason, "injected pre-session failure") {
					t.Fatalf("missing no-start fact: %+v", m)
				}
			} else if m.SessionID == "" || m.ResolvedModel != "resolved" || m.Operations[0].State != "UNKNOWN" {
				t.Fatalf("missing native owner adoption: %+v", m)
			}
			// Exact replay only reads the old request; edited replay cannot overwrite it.
			if _, err = svc.Create(ctx, req); err != nil {
				t.Fatal(err)
			}
			edited := req
			edited.Objective = "another objective"
			if _, err = svc.Create(ctx, edited); err == nil {
				t.Fatal("old identity accepted an edit")
			}
			if spawn.calls != 1 {
				t.Fatal("duplicate Worker")
			}
			next := req
			next.ID = "new-attempt"
			_, err = svc.Create(ctx, next)
			if mode == "before_session" {
				if err != nil {
					t.Fatal(err)
				}
				wait()
				if spawn.calls != 2 {
					t.Fatal("new attempt did not run")
				}
			} else if err == nil || !strings.Contains(err.Error(), "未知") {
				t.Fatalf("unknown did not block: %v", err)
			}
			old, _ := svc.Get(ctx, req.ID)
			if old.Revision != m.Revision || old.Request.Objective != req.Objective {
				t.Fatal("new attempt rewrote old request")
			}
		})
	}
}

type unreadableOwners struct{ Store }

func (unreadableOwners) ListAllSessions(context.Context) ([]domain.SessionRecord, error) {
	return nil, errors.New("owner read failed")
}
func TestCLAOFailedOwnerReadDoesNotProveNoExecution(t *testing.T) {
	st := sqlitetest.MustOpen(t)
	ctx := context.Background()
	req := contract()
	if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if err := st.CreateCLAOMission(ctx, record(Mission{Request: req, State: "UNKNOWN", Revision: 1, Operations: []Operation{{Kind: "spawn", State: "UNKNOWN"}}})); err != nil {
		t.Fatal(err)
	}
	svc := New(ctx, unreadableOwners{st}, nil, nil, nil, slog.Default())
	if err := svc.reconcileSpawn(req.ID, nil); err == nil {
		t.Fatal("missing read error")
	}
	m, _ := svc.Get(ctx, req.ID)
	if m.State != "UNKNOWN" || m.Revision != 1 {
		t.Fatal("failed read modified uncertainty")
	}
}

func TestCLAORecoveryUsesDurableNativeOwnerAndDoesNotReplay(t *testing.T) {
	for _, state := range []string{"active", "exited", "not_spawned", "before_intent"} {
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
			if state != "not_spawned" && state != "before_intent" {
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
			if state == "before_intent" {
				m.Operations = nil
			}
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
			if state == "not_spawned" || state == "before_intent" {
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

func TestCLAOCancelDuringFailedContinueKeepsSchedulingOwner(t *testing.T) {
	st := sqlitetest.MustOpen(t)
	ctx := context.Background()
	req := contract()
	if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if err := st.CreateCLAOMission(ctx, record(Mission{Request: req, State: "PAUSED", Revision: 1})); err != nil {
		t.Fatal(err)
	}
	svc := New(ctx, st, nil, absentController{}, nil, slog.Default())
	// Continue has reserved its local owner and is doing read-only validation.
	svc.running[req.ID] = true
	if _, err := svc.Cancel(ctx, req.ID); err != nil {
		t.Fatal(err)
	}
	svc.releaseOwner(req.ID, false) // validation fails; the cancel must not be stranded
	for deadline := time.Now().Add(time.Second); time.Now().Before(deadline); {
		m, err := svc.Get(ctx, req.ID)
		if err != nil {
			t.Fatal(err)
		}
		if m.State == "CANCELLED" {
			return
		}
		time.Sleep(time.Millisecond * 5)
	}
	t.Fatal("accepted cancel lost when Continue released its owner")
}

func TestCLAODirectiveConsumersPreserveConfirmedPrimaryAndSeparateMirror(t *testing.T) {
	m := Mission{Directives: []Directive{{DirectiveRequest: DirectiveRequest{ID: "note-identity", Target: "auditor"}, State: "received"}}}
	markConsumption(&m, RoleCall{ID: "first", Role: "auditor", State: "STARTING", DirectiveIDs: []string{"note-identity"}})
	if m.Directives[0].State != "received" {
		t.Fatal("prepared input is not external delivery")
	}
	markConsumption(&m, RoleCall{ID: "mirror", Role: "planner", State: "RECEIVED", DirectiveIDs: []string{"note-identity"}})
	if m.Directives[0].State != "received" {
		t.Fatal("mirror claimed primary consumption")
	}
	markConsumption(&m, RoleCall{ID: "first", Role: "auditor", State: "RECEIVED", DirectiveIDs: []string{"note-identity"}})
	markConsumption(&m, RoleCall{ID: "later", Role: "auditor", State: "UNKNOWN", DirectiveIDs: []string{"note-identity"}})
	if m.Directives[0].State != "applied" || len(m.Directives[0].Consumers) != 3 {
		t.Fatal("later unknown overwrote prior confirmed input")
	}
}

func TestCLAORoleRecoveryReattachesImmutableOwnerAndNeverDispatches(t *testing.T) {
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
	owner := req.ID + ":planner:1"
	rec, err := st.CreateSession(ctx, domain.SessionRecord{ProjectID: req.ProjectID, Kind: domain.KindWorker, Harness: req.Agent, Mode: domain.SessionModeChat, Activity: domain.Activity{State: domain.ActivityExited, LastActivityAt: now}, Metadata: domain.SessionMetadata{CLAOMissionID: owner, WorkspacePath: dir}, CreatedAt: now, UpdatedAt: now})
	if err != nil {
		t.Fatal(err)
	}
	frozen := FrozenRole{RoleChoice: RoleChoice{Agent: domain.HarnessOpenCode, Model: "frozen/second"}}
	m := Mission{Request: req, Roles: map[string]FrozenRole{"planner": frozen}, RoleCalls: []RoleCall{{ID: "plan-1", Owner: owner, Role: "planner", State: "STARTING", Choice: frozen}}, State: "PLANNING", Revision: 1, Operations: []Operation{{Kind: "spawn_planner", Target: owner, State: "IN_FLIGHT"}}, UpdatedAt: now.Format(time.RFC3339Nano)}
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
	// A nil session executor intentionally panics on any attempted side effect.
	service := New(ctx, st, nil, absentController{}, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	for i := 0; i < 2; i++ {
		if err = service.Recover(); err != nil {
			t.Fatal(err)
		}
	}
	got, err := service.Get(ctx, req.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.State != "UNKNOWN" || got.RoleCalls[0].SessionID != rec.ID || got.RoleCalls[0].State != "UNKNOWN" || got.Roles["planner"] != frozen || len(got.Operations) != 1 {
		t.Fatalf("role recovery: %+v", got)
	}
}
