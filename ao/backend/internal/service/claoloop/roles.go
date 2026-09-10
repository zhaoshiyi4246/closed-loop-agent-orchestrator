package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	chatsvc "github.com/aoagents/agent-orchestrator/backend/internal/service/chat"
)

// A missing semantic choice inherits the Worker at admission, not at call time.
type RoleChoice struct {
	Agent domain.AgentHarness `json:"agent"`
	Model string              `json:"model"`
}
type FrozenRole struct {
	RoleChoice
	Inherited  bool   `json:"inherited"`
	AccountRef string `json:"accountRef,omitempty"`
}
type RoleCall struct {
	Owner           string           `json:"owner"`
	ID              string           `json:"id"`
	Role            string           `json:"role"`
	IncidentID      string           `json:"incidentId,omitempty"`
	SessionID       domain.SessionID `json:"sessionId,omitempty"`
	Choice          FrozenRole       `json:"choice"`
	ResolvedModel   string           `json:"resolvedModel,omitempty"`
	ConfirmedModel  string           `json:"confirmedModel,omitempty"`
	ModelFactSource string           `json:"modelFactSource,omitempty"`
	State           string           `json:"state"`
	StartedAt       string           `json:"startedAt"`
	FinishedAt      string           `json:"finishedAt,omitempty"`
	Result          json.RawMessage  `json:"result,omitempty"`
	Error           string           `json:"error,omitempty"`
}
type Decision struct {
	ID            string           `json:"id"`
	EvidenceIndex int              `json:"evidenceIndex"`
	WorkerID      domain.SessionID `json:"workerId"`
	AuditID       string           `json:"auditId"`
	PlannerID     string           `json:"plannerId"`
	Action        string           `json:"action,omitempty"`
	Reason        string           `json:"reason,omitempty"`
	State         string           `json:"state"`
	Outcome       string           `json:"outcome,omitempty"`
}
type roleCore interface {
	Role(context.Context, Mission, string, map[string]any, *string) (Evidence, error)
}
type accountReader interface {
	GetCodexActiveAccount(context.Context) (domain.CodexActiveAccount, bool, error)
}

func (s *Service) freezeRoles(ctx context.Context, r Request) (map[string]FrozenRole, error) {
	out := map[string]FrozenRole{}
	for key := range r.Roles {
		if key != "planner" && key != "auditor" && key != "verifier" {
			return nil, fmt.Errorf("unknown role: %s", key)
		}
	}
	for _, key := range []string{"worker", "auditor", "planner", "verifier"} {
		c := FrozenRole{RoleChoice: RoleChoice{Agent: r.Agent, Model: r.Model}, Inherited: key != "worker"}
		if chosen, ok := r.Roles[key]; ok {
			c.RoleChoice, c.Inherited = chosen, false
		}
		if c.Agent == "" || len(c.Model) > 512 || strings.ContainsAny(c.Model, "\x00\r\n") {
			return nil, fmt.Errorf("%s 执行器/模型无效", key)
		}
		permission := domain.PermissionModeDefault
		if key != "worker" {
			permission = domain.PermissionModeReadOnly
		}
		if err := s.chat.PreflightChat(ctx, c.Agent, permission); err != nil {
			return nil, fmt.Errorf("%s: %w", key, err)
		}
		if c.Agent == domain.HarnessCodex {
			if reader, ok := s.store.(accountReader); ok {
				a, found, err := reader.GetCodexActiveAccount(ctx)
				if err != nil {
					return nil, err
				}
				if found {
					c.AccountRef = a.AccountID
				}
			}
		}
		out[key] = c
	}
	return out, nil
}
func (m Mission) choice(role string) FrozenRole {
	if c, ok := m.Roles[role]; ok {
		return c
	}
	// Read compatibility only; no write or current-default lookup for old records.
	model := m.Request.Model
	if role == "verifier" && m.ResolvedModel != "" {
		model = m.ResolvedModel
	}
	return FrozenRole{RoleChoice: RoleChoice{Agent: m.Request.Agent, Model: model}, Inherited: role != "worker"}
}
func (s *Service) checkAccount(c FrozenRole) error {
	if c.AccountRef == "" {
		return nil
	}
	reader, ok := s.store.(accountReader)
	if !ok {
		return errors.New("冻结账号引用不可读取")
	}
	a, found, err := reader.GetCodexActiveAccount(s.ctx)
	if err != nil || !found || a.AccountID != c.AccountRef {
		return errors.New("原生账号已变化；不会用另一账号继续此任务")
	}
	return nil
}
func (s *Service) callUpdate(id, callID string, f func(*RoleCall)) (Mission, error) {
	return s.mutate(id, func(m *Mission) error {
		for i := range m.RoleCalls {
			if m.RoleCalls[i].ID == callID {
				f(&m.RoleCalls[i])
				return nil
			}
		}
		return errors.New("role call not found")
	})
}
func assistantResult(snap chatsvc.Snapshot, sid domain.SessionID) string {
	turn := ""
	for i := len(snap.Turns) - 1; i >= 0; i-- {
		t := snap.Turns[i]
		if t.HandledBySessionID == sid && t.RolledBackAt == nil {
			if t.State == domain.TurnStateCompleted {
				turn = t.ID
			}
			break
		}
	}
	text := ""
	for _, msg := range snap.Messages {
		if turn != "" && msg.Role == domain.MessageRoleAssistant && !msg.Streaming && msg.TurnID == turn {
			text = msg.Text
		}
	}
	return text
}
func (s *Service) confirmedModel(sid domain.SessionID) (string, string) {
	if reader, ok := s.chat.(interface {
		ReportedModel(domain.SessionID) (string, string)
	}); ok {
		return reader.ReportedModel(sid)
	}
	return "", ""
}

// Each semantic call gets a distinct immutable owner and isolated worktree.
// No tools are granted; engine exit and a clean base are required before use.
func (s *Service) semantic(id, role, callID, incident, prompt string) (string, error) {
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return "", err
	}
	choice := m.choice(role)
	if err = s.checkAccount(choice); err != nil {
		return "", err
	}
	for _, c := range m.RoleCalls {
		if c.ID == callID {
			return "", errors.New("role call already recorded; automatic replay refused")
		}
	}
	_, err = s.mutate(id, func(v *Mission) error {
		if v.CancelRequested {
			return errCancelled
		}
		v.RoleCalls = append(v.RoleCalls, RoleCall{ID: callID, Owner: id + ":" + role + ":" + fmt.Sprint(len(m.RoleCalls)), Role: role, IncidentID: incident, Choice: choice, State: "STARTING", StartedAt: time.Now().UTC().Format(time.RFC3339Nano)})
		return nil
	})
	if err != nil {
		return "", err
	}
	var rec domain.SessionRecord
	base := m.Base
	if role == "verifier" {
		base = m.ResultHead
	}
	owner := id + ":" + role + ":" + fmt.Sprint(len(m.RoleCalls))
	err = s.operation(id, "spawn_"+role, owner, func() error {
		var e error
		rec, _, _, e = s.sessions.Spawn(ports.WithCLAOOwner(s.ctx, id), ports.SpawnConfig{ProjectID: m.Request.ProjectID, Branch: "clao/" + id + "/" + role + "-" + fmt.Sprint(len(m.RoleCalls)), Kind: domain.KindWorker, Harness: choice.Agent, RequestedMode: domain.SessionModeChat, CLAOMissionID: owner, CLAOBaseSHA: base, CLAOReview: true, AgentConfig: ports.AgentConfig{Model: choice.Model, Permissions: domain.PermissionModeReadOnly}, Prompt: prompt, DisplayName: role + " · " + m.Request.Objective})
		return e
	})
	if err != nil {
		return "", err
	}
	_, err = s.callUpdate(id, callID, func(c *RoleCall) { c.SessionID = rec.ID; c.ResolvedModel = rec.Metadata.Model; c.State = "RUNNING" })
	if err != nil {
		return "", err
	}
	if role == "verifier" {
		if _, err = s.mutate(id, func(v *Mission) error { v.VerifierSessionID = rec.ID; return nil }); err != nil {
			return "", err
		}
	}
	snap, waitErr := s.waitTurn(id, rec.ID, "")
	confirmed, modelSource := s.confirmedModel(rec.ID)
	if err = s.stopped(id, rec.ID); err != nil {
		return "", err
	}
	m, err = s.Get(s.ctx, id)
	if err != nil {
		return "", err
	}
	if m.CancelRequested {
		return "", errCancelled
	}
	text := assistantResult(snap, rec.ID)
	if waitErr == nil && strings.TrimSpace(text) == "" {
		waitErr = errors.New("角色未提供正式结构化回复")
	}
	clean, e := s.acceptance.Source(s.ctx, rec.Metadata.WorkspacePath)
	if e != nil || clean != base {
		waitErr = errors.New("只读角色工作区有改动或无法取证")
	}
	_, err = s.callUpdate(id, callID, func(c *RoleCall) {
		c.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)
		c.ConfirmedModel = confirmed
		c.ModelFactSource = modelSource
		c.State = "RECEIVED"
		if waitErr != nil {
			c.State = "FAILED"
			c.Error = waitErr.Error()
		}
	})
	if err != nil {
		return "", err
	}
	return text, waitErr
}

func (s *Service) human(id, reason string) error {
	_, err := s.mutate(id, func(m *Mission) error {
		if m.CancelRequested {
			return errCancelled
		}
		m.State = "HUMAN"
		m.Reason = reason + "；可查看原请求与角色记录，或创建新的尝试"
		for i := range m.Decisions {
			d := &m.Decisions[i]
			if d.State == "DIAGNOSING" || d.State == "CHECKED" || d.State == "EXECUTING" {
				d.State = "HUMAN"
				d.Outcome = reason
			}
		}
		return nil
	})
	return err
}
func (s *Service) decisionUpdate(id, incident, state, outcome string) error {
	_, err := s.mutate(id, func(m *Mission) error {
		for i := range m.Decisions {
			if m.Decisions[i].ID == incident {
				m.Decisions[i].State = state
				m.Decisions[i].Outcome = outcome
				return nil
			}
		}
		return errors.New("incident not found")
	})
	return err
}

// Returns an action only after the old Prompt/Schema/correlation contracts and
// current target/permission/budget checks. It never runs an external side effect.
func (s *Service) diagnose(id string, m Mission, proof Evidence, executionError string) (map[string]any, string, error) {
	if len(m.Decisions) >= m.Request.MaxRepairs+2 {
		return nil, "", s.human(id, "诊断/无进展预算耗尽")
	}
	if len(m.Decisions) > 0 && executionError == "" {
		old := m.Decisions[len(m.Decisions)-1]
		if old.EvidenceIndex < len(m.Evidence)-1 && m.Evidence[old.EvidenceIndex].Digest == proof.Digest {
			return nil, "", s.human(id, "修复后没有新的文件进展，停止重复诊断")
		}
	}
	core, ok := s.acceptance.(roleCore)
	if !ok {
		return nil, "", s.human(id, "角色契约核心不可用")
	}
	incident := fmt.Sprintf("%s:incident:%d", id, len(m.Decisions))
	auditID, plannerID := incident+":audit", incident+":plan"
	_, err := s.mutate(id, func(v *Mission) error {
		v.Decisions = append(v.Decisions, Decision{ID: incident, EvidenceIndex: len(v.Evidence) - 1, WorkerID: v.SessionID, AuditID: auditID, PlannerID: plannerID, State: "DIAGNOSING"})
		return nil
	})
	if err != nil {
		return nil, incident, err
	}
	history := map[string]any{"local_fixes": m.Repairs, "replans": m.Replans, "decisions": m.Decisions, "role_results": m.RoleCalls}
	contextData := map[string]any{"incidentId": incident, "workerId": m.SessionID, "workerStatus": map[string]any{"sessionId": m.SessionID, "stopped": true, "executionError": executionError}, "proof": proof, "executionError": executionError, "history": history, "remainingReplans": m.Request.MaxReplans - m.Replans, "remainingActions": m.Request.MaxRepairs - m.Repairs - m.Replans, "auditId": auditID}
	for _, role := range []string{"auditor", "planner"} {
		rid := auditID
		phase := "DIAGNOSING"
		reason := "Auditor 正在诊断实际失败证据"
		if role == "planner" {
			rid = plannerID
			phase = "PLANNING"
			reason = "Planner 正在决定下一动作"
		}
		contextData["id"] = rid
		if _, err = s.phase(id, phase, reason); err != nil {
			return nil, incident, err
		}
		prepared, e := core.Role(s.ctx, m, role, contextData, nil)
		if e != nil || !prepared.OK || prepared.RolePrompt == "" {
			return nil, incident, s.human(id, fmt.Sprintf("%s 证据无法完整准备：%v %s", role, e, prepared.ReadError))
		}
		text, e := s.semantic(id, role, rid, incident, prepared.RolePrompt)
		if e != nil {
			current, readErr := s.Get(s.ctx, id)
			if errors.Is(e, errCancelled) || readErr != nil || current.State == "UNKNOWN" {
				return nil, incident, e
			}
			if len(current.Operations) > 0 && strings.HasPrefix(current.Operations[len(current.Operations)-1].Kind, "spawn_") {
				return nil, incident, e
			}
			return nil, incident, s.human(id, role+" 未提供可用结果："+e.Error())
		}
		validated, e := core.Role(s.ctx, m, role, contextData, &text)
		if e != nil || !validated.OK {
			_, _ = s.callUpdate(id, rid, func(c *RoleCall) { c.State = "PROTOCOL_ERROR"; c.Error = fmt.Sprintf("%v %s", e, validated.ReadError) })
			return nil, incident, s.human(id, role+" 契约校验失败："+validated.ReadError)
		}
		if _, err = s.callUpdate(id, rid, func(c *RoleCall) { c.State = "VALIDATED"; c.Result = validated.RoleResult }); err != nil {
			return nil, incident, err
		}
		var obj map[string]any
		if err = json.Unmarshal(validated.RoleResult, &obj); err != nil {
			return nil, incident, err
		}
		if role == "auditor" {
			contextData["audit"] = obj
		} else {
			_, err = s.mutate(id, func(v *Mission) error {
				d := &v.Decisions[len(v.Decisions)-1]
				d.Action, _ = obj["action"].(string)
				d.Reason, _ = obj["reason"].(string)
				d.State = "CHECKED"
				return nil
			})
			return obj, incident, err
		}
	}
	return nil, incident, nil
}
