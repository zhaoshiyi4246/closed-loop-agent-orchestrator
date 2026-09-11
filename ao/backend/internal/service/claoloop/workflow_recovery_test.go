package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

type repairWriteFault struct {
	Store
	phase string
}

func (f repairWriteFault) SaveCLAOMission(ctx context.Context, row domain.CLAOMissionRecord) error {
	var m Mission
	if err := json.Unmarshal([]byte(row.Document), &m); err != nil {
		return err
	}
	if len(m.Operations) > 0 {
		op := m.Operations[len(m.Operations)-1]
		if (f.phase == "intent" || f.phase == "stop_intent") && op.Kind == "repair_send" && op.State == "IN_FLIGHT" ||
			f.phase == "receipt" && op.Kind == "repair_send" && op.State == "CONFIRMED_SUCCESS" ||
			f.phase == "stop_intent" && op.Kind == "stop" {
			return errors.New("controlled operation write failure")
		}
	}
	return f.Store.SaveCLAOMission(ctx, row)
}

type repairControllerBoundary struct {
	Chat
	Sessions
	live      bool
	sends     int
	stops     int
	sendError error
	stopError error
	lastID    string
	stop      func(context.Context, domain.SessionID) (domain.SessionRecord, error)
}

func (b *repairControllerBoundary) HasLiveChatController(domain.SessionID) bool { return b.live }
func (b *repairControllerBoundary) Send(_ context.Context, _ domain.SessionID, msg ports.ChatUserMessage) (domain.ConversationTurn, error) {
	b.sends++
	b.lastID = msg.ClientMessageID
	return domain.ConversationTurn{}, b.sendError
}
func (b *repairControllerBoundary) ExitAgent(ctx context.Context, id domain.SessionID) (domain.SessionRecord, error) {
	b.stops++
	if b.stopError != nil {
		return domain.SessionRecord{}, b.stopError
	}
	r, err := b.stop(ctx, id)
	if err == nil {
		b.live = false
	}
	return r, err
}

type repairInputBoundary struct{ Acceptance }

func (repairInputBoundary) Probe(context.Context, Mission) (Evidence, error) {
	return Evidence{Digest: "unchanged-input"}, nil
}
func (repairInputBoundary) PrepareVerification(context.Context, Mission, Evidence) (Evidence, error) {
	panic("repair must not invoke Verifier")
}

// Actual decision/operation persistence runs against SQLite. Only the external
// Chat process and the already-checked input observation are substituted here;
// the daemon-restart integration test exercises native SessionManager/Chat too.
func TestCLAOUnsentRepairStopsOnlyBeforeExternalDispatch(t *testing.T) {
	for _, tc := range []struct {
		name, writePhase string
		live             bool
		sendError        bool
		stopError        bool
		wantSends        int
		wantStops        int
		wantStopped      bool
	}{
		{"intent_not_saved", "intent", true, false, false, 0, 1, true},
		{"stop_not_confirmed", "intent", true, false, true, 0, 1, false},
		{"stop_intent_not_saved", "stop_intent", true, false, false, 0, 0, false},
		{"send_receipt_lost", "receipt", true, false, false, 1, 0, false},
		{"send_outcome_unknown", "", true, true, false, 1, 0, false},
		{"controller_handle_absent", "intent", false, false, false, 0, 0, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			st := sqlitetest.MustOpen(t)
			ctx := context.Background()
			req := contract()
			req.MaxRepairs = 1
			if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
				t.Fatal(err)
			}
			rec, err := st.CreateSession(ctx, domain.SessionRecord{ProjectID: req.ProjectID, Kind: domain.KindWorker, Harness: req.Agent, Mode: domain.SessionModeChat,
				Activity: domain.Activity{State: domain.ActivityIdle}, Metadata: domain.SessionMetadata{CLAOMissionID: req.ID}, CreatedAt: time.Now(), UpdatedAt: time.Now()})
			if err != nil {
				t.Fatal(err)
			}
			d := Decision{ID: req.ID + ":incident:0", WorkerID: rec.ID, PlannerID: "checked-planner", Action: "SEND_LOCAL_FIX", Charged: true, State: "EXECUTING", EvidenceIndex: 0}
			m := Mission{Request: req, Revision: 1, State: "PAUSED", SessionID: rec.ID, Repairs: 1, Decisions: []Decision{d}, Evidence: []Evidence{{Digest: "unchanged-input"}},
				Checkpoint: &Checkpoint{Stage: "action", Incident: d.ID}, RoleCalls: []RoleCall{{ID: d.PlannerID, State: "VALIDATED", Result: json.RawMessage(`{"message":"repair under original contract"}`)}},
				Operations: []Operation{{ID: d.ID + ":resume", Kind: "resume", Target: string(rec.ID), State: "CONFIRMED_SUCCESS"}}}
			if err := st.CreateCLAOMission(ctx, record(m)); err != nil {
				t.Fatal(err)
			}
			boundary := &repairControllerBoundary{live: tc.live}
			boundary.stop = func(ctx context.Context, id domain.SessionID) (domain.SessionRecord, error) {
				r, _, e := st.GetSession(ctx, id)
				if e != nil {
					return r, e
				}
				r.Activity.State = domain.ActivityExited
				r.UpdatedAt = time.Now()
				return r, st.UpdateSession(ctx, r)
			}
			if tc.sendError {
				boundary.sendError = errors.New("external send acknowledgement unknown")
			}
			if tc.stopError {
				boundary.stopError = errors.New("external controller still alive")
			}
			svc := New(ctx, repairWriteFault{st, tc.writePhase}, boundary, boundary, repairInputBoundary{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
			if err := svc.applyDecision(req.ID, m); err == nil {
				t.Fatal("original dispatch failure was hidden")
			}
			got, err := svc.Get(ctx, req.ID)
			if err != nil {
				t.Fatal(err)
			}
			if boundary.sends != tc.wantSends || boundary.stops != tc.wantStops || (svc.requireStopped(rec.ID) == nil) != tc.wantStopped {
				t.Fatalf("sends=%d stops=%d stopped=%v", boundary.sends, boundary.stops, svc.requireStopped(rec.ID) == nil)
			}
			if got.Repairs != 1 || !got.Decisions[0].Charged || got.Checkpoint.Stage != "action" || got.SessionID != rec.ID {
				t.Fatalf("charged original action changed: %+v", got)
			}
			if boundary.sends > 0 && boundary.lastID != d.ID+":fix" {
				t.Fatal("original message identity changed")
			}
			for _, op := range got.Operations {
				if tc.wantSends == 0 && op.Kind == "repair_send" {
					t.Fatal("uncommitted send was recorded or dispatched")
				}
				if op.Kind == "stop" && tc.wantStopped && op.State != "CONFIRMED_SUCCESS" {
					t.Fatal("confirmed controller exit not persisted")
				}
			}
		})
	}
}
