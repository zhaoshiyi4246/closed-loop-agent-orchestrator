package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	chatsvc "github.com/aoagents/agent-orchestrator/backend/internal/service/chat"
)

type RecoveryStatus struct {
	CanContinue bool   `json:"canContinue"`
	Reason      string `json:"reason"`
	Stage       string `json:"stage,omitempty"`
}
type recoveryCore interface {
	Probe(context.Context, Mission) (Evidence, error)
	PrepareVerification(context.Context, Mission, Evidence) (Evidence, error)
}

func finalState(state string) bool {
	return state == "DONE" || state == "FAILED" || state == "CANCELLED" || state == "HUMAN"
}
func decodeObject(data json.RawMessage, target any) error { return json.Unmarshal(data, target) }
func latestTurn(snap chatsvc.Snapshot, sid domain.SessionID) domain.ConversationTurn {
	for i := len(snap.Turns) - 1; i >= 0; i-- {
		t := snap.Turns[i]
		if t.HandledBySessionID == sid && t.RolledBackAt == nil {
			return t
		}
	}
	return domain.ConversationTurn{}
}
func (s *Service) findOwner(owner string) (domain.SessionRecord, error) {
	rows, err := s.ownedSessions(ports.CLAOMissionOwner(owner))
	if err != nil {
		return domain.SessionRecord{}, err
	}
	var found domain.SessionRecord
	for _, r := range rows {
		if r.Metadata.CLAOMissionID == owner {
			if found.ID != "" {
				return found, errors.New("不可变 owner 关联不唯一")
			}
			found = r
		}
	}
	if found.ID == "" {
		return found, errors.New("原生 Session 尚未发布")
	}
	return found, nil
}
func (s *Service) requireStopped(sid domain.SessionID) error {
	r, ok, err := s.store.GetSession(s.ctx, sid)
	if err != nil || !ok || r.Activity.State != domain.ActivityExited || s.chat.HasLiveChatController(sid) {
		return errors.New("原生 Session 停止尚未确认")
	}
	return nil
}

// A failed send-intent write proves that namedOperation never called Send.
// Stop the newly resumed controller while its real handle is still available,
// so a later daemon restart can continue this charged, still-unsent action.
// Once an intent exists its outcome may be unknown: neither compensate it as
// "unsent" nor infer process death from an absent in-memory controller.
func (s *Service) stopUnsentRepair(id string, d Decision) error {
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return err
	}
	for _, op := range m.Operations {
		if op.ID == d.ID+":send" {
			return nil
		}
	}
	if !s.chat.HasLiveChatController(d.WorkerID) {
		return nil
	}
	return s.stopped(id, d.WorkerID)
}

// Input checks never run a Gate, materialize, restore, or change a Git index.
func (s *Service) checkpointInput(m Mission) error {
	core, ok := s.acceptance.(recoveryCore)
	if !ok {
		return errors.New("恢复取证能力不可用")
	}
	proof, err := core.Probe(s.ctx, m)
	if err != nil {
		return err
	}
	if proof.ReadError != "" {
		return errors.New(proof.ReadError)
	}
	if m.Checkpoint.Digest != "" && m.Checkpoint.Digest != proof.Digest {
		return errors.New("当前工作区与已保存验收/决策输入不一致；请创建新尝试")
	}
	return nil
}

// Native client identity + handled Session + provider completion, never just
// a message appearing in the local timeline or disappearing from a queue.
func (s *Service) delivered(sid domain.SessionID, clientID string) (domain.ConversationTurn, bool, error) {
	snap, err := s.chat.Snapshot(s.ctx, sid)
	if err != nil {
		return domain.ConversationTurn{}, false, err
	}
	for _, msg := range snap.Messages {
		if msg.ClientMessageID == clientID && msg.Role == domain.MessageRoleUser {
			for _, turn := range snap.Turns {
				if turn.ID == msg.TurnID && turn.HandledBySessionID == sid && turn.RolledBackAt == nil {
					return turn, turn.ProviderTurnID != "" && turn.State == domain.TurnStateCompleted, nil
				}
			}
		}
	}
	return domain.ConversationTurn{}, false, nil
}

func (s *Service) reconcile(id string) error {
	m, err := s.Get(s.ctx, id)
	if err != nil || finalState(m.State) {
		return err
	}
	for _, child := range m.Subtasks {
		if !finalState(child.State) {
			if err = s.reconcile(child.Request.ID); err != nil {
				return err
			}
		}
	}
	owned, err := s.ownedSessions(id)
	if err != nil {
		return err
	}
	resolved := map[string]string{}
	for _, op := range m.Operations {
		if op.State != "IN_FLIGHT" && op.State != "UNKNOWN" {
			continue
		}
		switch {
		case strings.HasPrefix(op.Kind, "spawn"):
			owner := op.Target
			if owner == "worker" || owner == "" {
				owner = id
			}
			if owner == "verifier" {
				owner = id + ":verifier"
			}
			var matches []domain.SessionRecord
			for _, r := range owned {
				if r.Metadata.CLAOMissionID == owner {
					matches = append(matches, r)
				}
			}
			if len(matches) == 1 && m.Checkpoint != nil {
				snap, e := s.chat.Snapshot(s.ctx, matches[0].ID)
				if e == nil {
					t := latestTurn(snap, matches[0].ID)
					if t.ProviderTurnID != "" && t.State == domain.TurnStateCompleted {
						resolved[op.ID] = "CONFIRMED_SUCCESS"
					}
				}
			} else if len(matches) == 0 {
				resolved[op.ID] = "CONFIRMED_FAILURE"
			}
		case op.Kind == "stop":
			if s.requireStopped(domain.SessionID(op.Target)) == nil {
				resolved[op.ID] = "CONFIRMED_SUCCESS"
			}
		case op.MessageID != "":
			_, done, e := s.delivered(domain.SessionID(op.Target), op.MessageID)
			if e == nil && done {
				resolved[op.ID] = "CONFIRMED_SUCCESS"
			}
		case op.Kind == "resume":
			if s.chat.HasLiveChatController(domain.SessionID(op.Target)) {
				resolved[op.ID] = "CONFIRMED_SUCCESS"
			}
		}
	}
	_, err = s.mutate(id, func(v *Mission) error {
		for _, r := range owned {
			associateSession(v, r)
		}
		for i := range v.RoleCalls {
			c := &v.RoleCalls[i]
			if c.State == "STARTING" || c.State == "RUNNING" {
				c.State = "UNKNOWN"
				c.Error = "原调用结果待对账，不重新发起"
			}
		}
		for i := range v.Operations {
			op := &v.Operations[i]
			if state, ok := resolved[op.ID]; ok {
				op.State = state
				op.Reason += "；已按原生 owner/回合事实对账"
			} else if op.State == "IN_FLIGHT" {
				op.State = "UNKNOWN"
			}
		}
		if (v.Checkpoint == nil || v.Checkpoint.Stage == "worker") && len(owned) == 0 && v.SessionID == "" && v.ResultHead == "" && (len(v.Operations) == 0 || len(v.Operations) == 1 && v.Operations[0].State == "CONFIRMED_FAILURE") {
			v.State, v.Reason = "FAILED", "启动在原生 Session 发布前中断；已确认没有启动 Worker"
		}
		return nil
	})
	if err == nil {
		err = s.reconcileDirectives(id)
	}
	return err
}

func (s *Service) recoveryCheck(m Mission) error {
	if finalState(m.State) {
		return errors.New("原任务已结束；后续工作请创建新尝试")
	}
	if m.CancelRequested {
		return errors.New("取消已接收；请先确认停止，不恢复正常执行")
	}
	if m.Checkpoint == nil || len(m.Roles) != 4 {
		return errors.New("历史没有完整阶段/角色快照，只能查看")
	}
	if m.Checkpoint.LocalState != "" {
		return errors.New("中断的 Gate/固定产物结果未保存，不能安全重跑；可取消并创建新尝试")
	}
	for _, op := range m.Operations {
		if op.State == "UNKNOWN" || op.State == "IN_FLIGHT" {
			return fmt.Errorf("%s 的外部结果尚未确认，不会重发；可取消/确认停止", op.Kind)
		}
	}
	if m.Source != nil {
		if m.Checkpoint.Stage == "source" {
			return nil
		}
		if _, e := s.acceptance.Source(s.ctx, m.Source.ProjectPath); e != nil {
			return errors.New("私有冻结来源不可用")
		}
		if m.Checkpoint.Stage == "decompose" {
			return nil
		}
		if m.Checkpoint.Stage == "children" || m.Checkpoint.Stage == "integrate" {
			for _, child := range m.Subtasks {
				if child.State == "DONE" {
					if e := s.deliveryStopped(child); e != nil {
						return e
					}
					continue
				}
				if child.SessionID == "" && len(child.Operations) == 0 {
					continue
				}
				if e := s.recoveryCheck(child); e != nil {
					return e
				}
			}
			return nil
		}
		if m.ResultHead != "" && (m.Checkpoint.Stage == "integration_gate" || m.Checkpoint.Stage == "verify" || m.Checkpoint.Stage == "final") {
			if e := s.deliveryStopped(m); e != nil {
				return e
			}
			return s.checkpointInput(m)
		}
	}
	if m.SessionID == "" {
		return errors.New("没有已发布的 Worker，不从头重新启动原任务")
	}
	p, found, err := s.store.GetProject(s.ctx, string(m.Request.ProjectID))
	if err != nil || !found || m.SourcePath == "" || filepath.Clean(p.Path) != filepath.Clean(m.SourcePath) {
		return errors.New("项目与冻结来源位置不一致")
	}
	rec, ok, err := s.store.GetSession(s.ctx, m.SessionID)
	expectedOwner := workerOwner(m)
	if m.Checkpoint.Stage == "action" {
		for _, d := range m.Decisions {
			if d.ID == m.Checkpoint.Incident && d.Action == "REPLAN_SPAWN" && d.Charged && d.WorkerID == m.SessionID {
				prior := m
				prior.Replans--
				expectedOwner = workerOwner(prior)
			}
		}
	}
	if err != nil || !ok || rec.Metadata.CLAOMissionID != expectedOwner || rec.ProjectID != m.Request.ProjectID || rec.Metadata.WorkspacePath != m.Workspace || rec.Metadata.DiffBaseSHA != m.Base {
		return errors.New("原 Worker、工作区或 frozen base 关联不一致")
	}
	for _, role := range m.Roles {
		if err = s.checkAccount(role); err != nil {
			return err
		}
	}
	// A running phase is adoptable only from a completed native turn or an
	// AO-reconnected live controller. No provider operation is performed here.
	if m.Checkpoint.Stage == "worker" {
		snap, e := s.chat.Snapshot(s.ctx, m.SessionID)
		if e != nil {
			return e
		}
		t := latestTurn(snap, m.SessionID)
		if !s.chat.HasLiveChatController(m.SessionID) && (t.ID == "" || !t.State.Terminal() || rec.Activity.State != domain.ActivityExited) {
			return errors.New("原生在途执行不能确认已结束或续接；保留待确认，可取消/确认停止")
		}
	} else if m.Checkpoint.Stage != "action" {
		if err = s.requireStopped(m.SessionID); err != nil {
			return err
		}
	}
	if m.Checkpoint.Stage == "action" {
		for _, d := range m.Decisions {
			if d.ID == m.Checkpoint.Incident {
				return s.decisionInput(m, d)
			}
		}
		return errors.New("动作原记录缺失")
	}
	return s.checkpointInput(m)
}

// Startup only reconciles. Continue is the sole entry that claims scheduling.
func (s *Service) Recover() error {
	rows, err := s.List(s.ctx)
	if err != nil {
		return err
	}
	for _, m := range rows {
		if finalState(m.State) {
			continue
		}
		if err = s.reconcile(m.Request.ID); err != nil {
			return err
		}
		m, err = s.Get(s.ctx, m.Request.ID)
		if err != nil {
			return err
		}
		if finalState(m.State) {
			continue
		}
		check := s.recoveryCheck(m)
		_, err = s.mutate(m.Request.ID, func(v *Mission) error {
			v.State, v.Reason = "PAUSED", "运行已中断；可检查原进度并继续任务"
			v.Recovery = &RecoveryStatus{CanContinue: check == nil, Reason: v.Reason}
			if v.Checkpoint != nil {
				v.Recovery.Stage = v.Checkpoint.Stage
			}
			if check != nil {
				v.State = "UNKNOWN"
				v.Reason = check.Error()
				v.Recovery.Reason = v.Reason
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) Continue(ctx context.Context, id string) (Mission, error) {
	if _, _, child := subtaskIdentity(id); child {
		return Mission{}, errors.New("子任务由原 Mission 统一继续，不能单独启动调度")
	}
	// Reserve the same local owner used by Create/Cancel. SQLite CAS remains
	// the durable mutation boundary; the AO daemon already owns this database.
	s.mu.Lock()
	if s.running[id] {
		s.mu.Unlock()
		return s.Get(ctx, id)
	}
	s.running[id] = true
	s.mu.Unlock()
	launched := false
	defer func() {
		if !launched {
			s.releaseOwner(id, false)
		}
	}()
	if err := s.reconcile(id); err != nil {
		return Mission{}, err
	}
	m, err := s.Get(ctx, id)
	if err != nil {
		return m, err
	}
	if err = s.recoveryCheck(m); err != nil {
		if !finalState(m.State) {
			_, _ = s.mutate(id, func(v *Mission) error { v.Recovery = &RecoveryStatus{Reason: err.Error()}; return nil })
		}
		return m, err
	}
	m, err = s.mutate(id, func(v *Mission) error {
		if v.CancelRequested {
			return errCancelled
		}
		v.Recovery = nil
		v.State = "RESUMING"
		v.Reason = "继续原任务已接收；沿用阶段、Session 与剩余预算"
		return nil
	})
	if err != nil {
		return m, err
	}
	launched = true
	go s.run(id)
	return m, nil
}

// A cancel arriving during Continue's preflight must inherit the same owner,
// including when preflight fails. Never leave an accepted cancel without a runner.
func (s *Service) releaseOwner(id string, cancelHandled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m, err := s.Get(s.ctx, id)
	if !cancelHandled && err == nil && m.CancelRequested && !finalState(m.State) && s.ctx.Err() == nil {
		go func() {
			defer func() { s.mu.Lock(); delete(s.running, id); s.mu.Unlock() }()
			if err := s.cancelStopped(id); err != nil {
				_, _ = s.phase(id, "UNKNOWN", "取消已接收；停止尚未确认："+err.Error())
			}
		}()
		return
	}
	delete(s.running, id)
}
