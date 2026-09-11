package claoloop

import (
	"context"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
)

// Presentation is read-only and never participates in Get/mutate/recovery.
// Pending native requests are public AO facts, not a guessed Mission state.
func (s *Service) Presentation(ctx context.Context, m Mission) Mission {
	m.ActiveWait = ""
	if m.State == "RUNNING" && m.SessionID != "" {
		if snap, err := s.chat.Snapshot(ctx, m.SessionID); err == nil {
			for _, a := range snap.Activities {
				if a.Status != domain.ActivityStatusPending {
					continue
				}
				if a.Kind == domain.ActivityKindApproval {
					m.ActiveWait = "approval"
				}
				if a.Kind == domain.ActivityKindUserInput {
					m.ActiveWait = "user_input"
				}
			}
		} else {
			m.ActiveWait = "read_error"
		}
	}
	for i, child := range m.Subtasks {
		m.Subtasks[i] = s.Presentation(ctx, child)
	}
	return m
}
