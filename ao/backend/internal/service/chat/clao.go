package chat

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

// The native approval UI remains the request owner. A closed-loop approval is
// limited to this request; a verifier cannot gain write/tool permission.
func (s *Service) claoApproval(ctx context.Context, rec domain.SessionRecord, requestID string, decision ports.ChatDecision) error {
	if rec.Metadata.CLAOMissionID == "" {
		return nil
	}
	snapshot, err := s.Snapshot(ctx, rec.ID)
	if err != nil {
		return err
	}
	for _, activity := range snapshot.Activities {
		if activity.RequestID != requestID || activity.Status != domain.ActivityStatusPending {
			continue
		}
		var detail struct {
			Decisions []struct {
				ID   string                 `json:"id"`
				Kind ports.ChatDecisionKind `json:"kind"`
			} `json:"decisions"`
		}
		if err := json.Unmarshal(activity.Detail, &detail); err != nil {
			return err
		}
		for _, offered := range detail.Decisions {
			if offered.ID != decision.ID || len(decision.Raw) != 0 {
				continue
			}
			if offered.Kind == ports.ChatDecisionRejectOnce || offered.Kind == ports.ChatDecisionRejectAlways {
				return nil
			}
			if offered.Kind == ports.ChatDecisionAllowOnce && !ports.CLAOSemanticOwner(rec.Metadata.CLAOMissionID) {
				if s.claoApprovalPolicy == nil {
					return errors.New("闭环审批策略不可用；可拒绝请求或取消任务")
				}
				return s.claoApprovalPolicy(ctx, rec, activity)
			}
			return errors.New("闭环仅允许当前请求的一次审批；Verifier 不获得工具权限")
		}
	}
	return errors.New("审批请求已失效或无法确认其权限含义")
}

// Wired before serving requests. The existing Chat service still owns delivery
// and request lifecycle; this hook only checks the immutable mission scope.
func (s *Service) SetCLAOApprovalPolicy(policy func(context.Context, domain.SessionRecord, domain.ConversationActivity) error) {
	s.claoApprovalPolicy = policy
}

// CLAO reads already-observed model facts; never infer them from requested settings.
func (s *Service) ReportedModel(id domain.SessionID) (string, string) {
	controller, err := s.Controller(id)
	if err != nil {
		return "", ""
	}
	if reader, ok := controller.conv.(ports.ChatReportedModelReader); ok {
		return reader.ReportedModel()
	}
	return "", ""
}
