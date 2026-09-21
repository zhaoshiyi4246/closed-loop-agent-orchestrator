package claoloop

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/sqlitetest"
)

func TestCLAOSharedLastBudgetReservationIsAtomic(t *testing.T) {
	for _, replacement := range []bool{false, true} {
		t.Run(map[bool]string{false: "repair", true: "replacement"}[replacement], func(t *testing.T) {
			ctx := context.Background()
			st := sqlitetest.MustOpen(t)
			req := contract()
			req.MaxRepairs, req.MaxReplans = 1, 1
			if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
				t.Fatal(err)
			}
			m := Mission{Request: req, Revision: 1, State: "RUNNING"}
			for _, suffix := range []string{"--task-1", "--task-2"} {
				child := Mission{Request: req, CoordinatorID: req.ID, State: "PLANNING", Revision: 1,
					Decisions: []Decision{{ID: "checked", State: "CHECKED"}}}
				child.Request.ID += suffix
				m.Subtasks = append(m.Subtasks, child)
			}
			if err := st.CreateCLAOMission(ctx, record(m)); err != nil {
				t.Fatal(err)
			}
			svc := New(ctx, st, nil, absentController{}, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
			var wg sync.WaitGroup
			errs := make(chan error, 2)
			start := make(chan struct{})
			for _, child := range m.Subtasks {
				wg.Add(1)
				go func(id string) {
					defer wg.Done()
					<-start
					_, err := svc.mutate(id, func(v *Mission) error {
						if replacement {
							v.Replans++
						} else {
							v.Repairs++
						}
						v.Decisions[0].Charged = true
						v.Decisions[0].State = "EXECUTING"
						return nil
					})
					errs <- err
				}(child.Request.ID)
			}
			close(start)
			wg.Wait()
			close(errs)
			refused := 0
			for err := range errs {
				if errors.Is(err, errSharedBudgetExhausted) {
					refused++
				} else if err != nil {
					t.Fatal(err)
				}
			}
			got, err := svc.Get(ctx, req.ID)
			if err != nil || refused != 1 || got.Repairs+got.Replans != 1 {
				t.Fatalf("refused=%d saved=%+v error=%v", refused, got, err)
			}
			for _, child := range got.Subtasks {
				if child.Repairs+child.Replans == 0 && (child.Decisions[0].Charged || child.Decisions[0].State != "CHECKED") {
					t.Fatal("refused mutation changed durable decision", child)
				}
			}
		})
	}
}

func TestCLAOChildFailureRequiresEveryOwnedSessionStopped(t *testing.T) {
	ctx := context.Background()
	st := sqlitetest.MustOpen(t)
	req := contract()
	if err := st.UpsertProject(ctx, domain.ProjectRecord{ID: string(req.ProjectID), Path: t.TempDir(), RegisteredAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	m := Mission{Request: req, Revision: 1, State: "RUNNING", Checkpoint: &Checkpoint{Stage: "children"}}
	for i, suffix := range []string{"--task-1", "--task-2"} {
		child := Mission{Request: req, State: []string{"HUMAN", "DONE"}[i], Reason: "shared allowance refused", Revision: 1}
		child.Request.ID += suffix
		m.Subtasks = append(m.Subtasks, child)
	}
	if err := st.CreateCLAOMission(ctx, record(m)); err != nil {
		t.Fatal(err)
	}
	// A semantic session also belongs to the original owner; stopped Workers
	// alone cannot authorize a terminal parent and a fresh attempt.
	role, err := st.CreateSession(ctx, domain.SessionRecord{ProjectID: req.ProjectID, Kind: domain.KindWorker, Harness: req.Agent, Mode: domain.SessionModeChat,
		Activity: domain.Activity{State: domain.ActivityActive}, Metadata: domain.SessionMetadata{CLAOMissionID: m.Subtasks[0].Request.ID + ":planner:test"}, CreatedAt: time.Now(), UpdatedAt: time.Now()})
	if err != nil {
		t.Fatal(err)
	}
	svc := New(ctx, st, nil, absentController{}, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := svc.runChildren(req.ID, m); err == nil {
		t.Fatal("unconfirmed semantic stop was accepted")
	}
	got, _ := svc.Get(ctx, req.ID)
	if finalState(got.State) {
		t.Fatal("parent became terminal before stop confirmation")
	}
	role.Activity.State = domain.ActivityExited
	if err := st.UpdateSession(ctx, role); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.mutate(req.ID, func(v *Mission) error {
		v.Subtasks[0].SessionID = "missing-worker"
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := svc.runChildren(req.ID, m); err == nil {
		t.Fatal("missing referenced Worker was treated as stopped")
	}
	if _, err := svc.mutate(req.ID, func(v *Mission) error {
		v.Subtasks[0].SessionID = ""
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := svc.runChildren(req.ID, m); err != nil {
		t.Fatal(err)
	}
	got, _ = svc.Get(ctx, req.ID)
	if got.State != "HUMAN" {
		t.Fatal("confirmed failed child did not terminate parent", got.State)
	}
}
