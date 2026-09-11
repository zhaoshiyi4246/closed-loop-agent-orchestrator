package claoloop

import (
	"errors"
	"fmt"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

// Checkpoint is the next unfinished boundary in the existing Mission document.
// Local Gate/materialization work is journaled too: a crash is not permission
// to repeat a shell command or commit. All counters remain on the Mission.
type Checkpoint struct {
	Stage          string `json:"stage"`
	AfterTurn      string `json:"afterTurn,omitempty"`
	ExecutionError string `json:"executionError,omitempty"`
	Proof          int    `json:"proof"`
	Incident       string `json:"incident,omitempty"`
	LocalState     string `json:"localState,omitempty"`
	Digest         string `json:"digest,omitempty"`
}

func (s *Service) advance(id, stage, state, reason string) (Mission, error) {
	return s.mutate(id, func(m *Mission) error {
		if m.CancelRequested {
			return errCancelled
		}
		m.Checkpoint.Stage, m.Checkpoint.LocalState = stage, ""
		m.State, m.Reason = state, reason
		return nil
	})
}

func (s *Service) execute(id string) error {
	for {
		m, err := s.Get(s.ctx, id)
		if err != nil {
			return err
		}
		if m.CancelRequested {
			return errCancelled
		}
		if finalState(m.State) {
			return nil
		}
		if m.Checkpoint == nil {
			return errors.New("历史任务没有可继续的阶段记录")
		}
		cp := *m.Checkpoint
		switch cp.Stage {
		case "source":
			if err = s.freezeSource(id, m); err != nil {
				return err
			}
		case "decompose":
			if err = s.decompose(id, m); err != nil {
				return err
			}
		case "children":
			if err = s.runChildren(id, m); err != nil {
				return err
			}
		case "integrate":
			if err = s.integrate(id, m); err != nil {
				return err
			}
		case "worker":
			if m.SessionID == "" {
				if _, err = s.spawnWorker(id, m, ""); err != nil {
					return err
				}
				continue
			}
			snap, waitErr := s.waitTurn(id, m.SessionID, cp.AfterTurn)
			if s.ctx.Err() != nil {
				return s.ctx.Err()
			}
			// Same intake fence as the native Chat/directive path. Once STOPPING
			// is persisted no user send may race the acceptance snapshot.
			s.dispatchMu.Lock()
			current, snapshotErr := s.chat.Snapshot(s.ctx, m.SessionID)
			if snapshotErr != nil {
				s.dispatchMu.Unlock()
				return snapshotErr
			}
			if latestTurn(current, m.SessionID).ID != latestTurn(snap, m.SessionID).ID {
				s.dispatchMu.Unlock()
				continue // A user turn arrived before the stop fence; observe it first.
			}
			_, err = s.phase(id, "STOPPING", "等待 AO 确认 Worker 停止")
			if err == nil {
				err = s.stopped(id, m.SessionID)
			}
			s.dispatchMu.Unlock()
			if err != nil {
				return err
			}
			_, err = s.mutate(id, func(v *Mission) error {
				if v.CancelRequested {
					return errCancelled
				}
				v.Checkpoint.AfterTurn = latestTurn(snap, m.SessionID).ID
				v.Checkpoint.ExecutionError = ""
				if waitErr != nil {
					v.Checkpoint.ExecutionError = waitErr.Error()
				}
				v.Checkpoint.Stage, v.Checkpoint.LocalState = "gate", ""
				v.State, v.Reason = "GATE", "等待执行 Gate、完整性与范围验收"
				return nil
			})
			if err != nil {
				return err
			}
		case "gate", "recheck", "materialize", "integration_gate", "final":
			if err = s.reconcile(id); err != nil {
				return err
			}
			m, err = s.Get(s.ctx, id)
			if err != nil {
				return err
			}
			for _, op := range m.Operations {
				if op.State == "UNKNOWN" || op.State == "IN_FLIGHT" {
					return errors.New("外部操作尚未确认，不继续验收")
				}
			}
			if err = s.localStep(id, m); err != nil {
				return err
			}
		case "decide":
			if cp.Proof < 0 || cp.Proof >= len(m.Evidence) {
				return errors.New("验收证据关联缺失")
			}
			proof := m.Evidence[cp.Proof]
			if proof.ReadError != "" || !proof.ScopeOK || !gateIntegrity(proof) {
				_, err = s.phase(id, "FAILED", "确定性范围/完整性或取证失败，模型不能覆盖")
				return err
			}
			if proof.OK && cp.ExecutionError == "" {
				_, err = s.advance(id, "materialize", "MATERIALIZING", "固定验收产物；不写回原项目")
			} else {
				if m.Repairs+m.Replans >= m.Request.MaxRepairs {
					return s.human(id, "修复预算耗尽；Gate 或执行仍未通过")
				}
				action, incident, e := s.diagnose(id, m, proof, cp.ExecutionError)
				if e != nil {
					return e
				}
				if action == nil {
					return nil
				}
				_, err = s.mutate(id, func(v *Mission) error {
					if v.CancelRequested {
						return errCancelled
					}
					v.Checkpoint.Incident, v.Checkpoint.Stage = incident, "action"
					return nil
				})
			}
			if err != nil {
				return err
			}
		case "action":
			if err = s.applyDecision(id, m); err != nil {
				return err
			}
		case "verify":
			if cp.Proof < 0 || cp.Proof >= len(m.Evidence) {
				return errors.New("固定产物证据缺失")
			}
			preparer, ok := s.acceptance.(recoveryCore)
			if !ok {
				return errors.New("固定结果读取能力不可用")
			}
			proof, e := preparer.PrepareVerification(s.ctx, m, m.Evidence[cp.Proof])
			if e != nil || proof.VerifierPrompt == "" {
				return fmt.Errorf("固定结果证据不可读取: %v %s", e, proof.ReadError)
			}
			if _, err = s.semantic(id, "verifier", id+":verify", "", proof.VerifierPrompt); err != nil {
				return err
			}
			if _, err = s.advance(id, "final", "VERIFYING", "核对最终 Gate 与结构化复核结论"); err != nil {
				return err
			}
		default:
			return errors.New("未支持的历史恢复阶段：" + cp.Stage)
		}
	}
}

func (s *Service) localStep(id string, m Mission) error {
	cp := *m.Checkpoint
	if cp.LocalState != "" {
		return errors.New("Gate/固定产物的在途结果无法确认，不会重跑：" + cp.Stage)
	}
	if err := s.deliveryStopped(m); err != nil {
		return err
	}
	if err := s.checkpointInput(m); err != nil {
		return err
	}
	text := ""
	if cp.Stage == "final" {
		for _, c := range m.RoleCalls {
			if c.ID == id+":verify" {
				text = c.Text
			}
		}
		if text == "" {
			return errors.New("Verifier 正式结果缺失")
		}
	}
	if _, err := s.mutate(id, func(v *Mission) error {
		if v.CancelRequested {
			return errCancelled
		}
		v.Checkpoint.LocalState = "IN_FLIGHT"
		return nil
	}); err != nil {
		return err
	}
	proof, err := s.acceptance.Check(s.ctx, m, cp.Stage == "materialize", cp.Digest, text)
	if err != nil {
		return err
	}
	_, err = s.mutate(id, func(v *Mission) error {
		public := proof
		public.VerifierPrompt = ""
		v.Evidence = append(v.Evidence, public)
		v.Checkpoint.Proof, v.Checkpoint.Digest = len(v.Evidence)-1, proof.Digest
		v.Checkpoint.LocalState = ""
		if v.CancelRequested {
			return nil
		} // run loop performs all-owner stop confirmation
		switch cp.Stage {
		case "gate":
			v.Checkpoint.Stage = "decide"
		case "recheck":
			for i := range v.Decisions {
				if v.Decisions[i].ID == cp.Incident {
					v.Decisions[i].State = "APPLIED"
					v.Decisions[i].Outcome = "已执行一次确定性复查，未向 Worker 发指令"
				}
			}
			if !proof.OK || cp.ExecutionError != "" {
				v.State, v.Reason = "HUMAN", "复查未解除已有 Gate/执行失败；停止无进展循环"
			} else {
				v.Checkpoint.Stage = "materialize"
			}
		case "materialize":
			if !proof.OK || proof.ResultHead == "" {
				v.State, v.Reason = "FAILED", "无法固定验收产物："+proof.ReadError
			} else {
				v.ResultHead, v.Checkpoint.Stage = proof.ResultHead, "verify"
				if v.CoordinatorID != "" {
					v.State = "DONE"
					v.Reason = "子任务 Gate/范围通过，等待 Mission 集成与最终验收"
					v.Checkpoint.Digest = ""
					return nil
				}
				if v.Source != nil {
					v.Checkpoint.Stage = "integrate"
				}
				v.State, v.Reason = "VERIFYING", "等待独立原生 Session 结构化复核"
				// Materialization changes HEAD/index. The frozen commit is the next
				// boundary's source; do not compare against the pre-commit digest.
				v.Checkpoint.Digest = ""
			}
		case "integration_gate":
			if !proof.OK {
				v.State = "FAILED"
				v.Reason = "Mission 集成 Gate/范围/完整性未通过：" + proof.ReadError
			} else {
				proof.ResultHead = v.ResultHead
				v.Evidence[len(v.Evidence)-1].ResultHead = v.ResultHead
				v.Checkpoint.Stage = "verify"
				v.State = "VERIFYING"
				v.Reason = "等待 Mission 独立最终复核"
			}
		case "final":
			for i := range v.RoleCalls {
				if v.RoleCalls[i].Role == "verifier" {
					v.RoleCalls[i].Result = proof.Verification
					v.RoleCalls[i].State = "VALIDATED"
					if proof.ReadError != "" {
						v.RoleCalls[i].State, v.RoleCalls[i].Error = "PROTOCOL_ERROR", proof.ReadError
					}
				}
			}
			v.State, v.Reason = "FAILED", "最终验收未通过："+proof.ReadError
			if proof.OK {
				v.State, v.Reason = "DONE", "最终 Gate、范围及独立 Verifier PASS"
			}
		}
		return nil
	})
	return err
}

func (s *Service) applyDecision(id string, m Mission) error {
	var d Decision
	for _, v := range m.Decisions {
		if v.ID == m.Checkpoint.Incident {
			d = v
		}
	}
	if d.ID == "" {
		return errors.New("决策关联缺失")
	}
	effectRecorded := decisionEffectRecorded(m, d)
	if err := s.decisionInput(m, d); err != nil {
		return err
	}
	var action map[string]any
	for _, c := range m.RoleCalls {
		if c.ID == d.PlannerID {
			if err := decodeObject(c.Result, &action); err != nil {
				return err
			}
		}
	}
	if action == nil {
		return errors.New("已校验 Planner 结果缺失")
	}
	if d.Action == "HUMAN" {
		return s.human(id, d.Reason)
	}
	if d.Action == "CONTINUE" || d.Action == "CANDIDATE_DONE" {
		_, err := s.advance(id, "recheck", "GATE", "按已校验决策执行一次确定性复查")
		return err
	}
	if !d.Charged {
		if m.Repairs+m.Replans >= m.Request.MaxRepairs || d.Action == "REPLAN_SPAWN" && m.Replans >= m.Request.MaxReplans {
			return s.human(id, "已校验动作超出剩余修复/替换预算")
		}
		if err := s.requireStopped(d.WorkerID); err != nil {
			return err
		}
	}
	if !d.Charged {
		var err error
		m, err = s.mutate(id, func(v *Mission) error {
			if v.CancelRequested {
				return errCancelled
			}
			if v.Repairs+v.Replans >= v.Request.MaxRepairs {
				return errors.New("动作预算耗尽")
			}
			if d.Action == "REPLAN_SPAWN" {
				if v.Replans >= v.Request.MaxReplans {
					return errors.New("替换预算耗尽")
				}
				v.Replans++
			} else if d.Action == "SEND_LOCAL_FIX" {
				v.Repairs++
			} else {
				return errors.New("未支持的 Planner 动作")
			}
			for i := range v.Decisions {
				if v.Decisions[i].ID == d.ID {
					v.Decisions[i].Charged = true
					v.Decisions[i].State = "EXECUTING"
					v.Checkpoint.Digest = ""
				}
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	if d.Action == "REPLAN_SPAWN" {
		replacement, _ := action["replacement_task_spec"].(map[string]any)
		plan, _ := replacement["objective"].(string)
		if _, err := s.spawnWorker(id, m, plan); err != nil {
			return err
		}
	} else {
		if err := s.checkAccount(m.choice("worker")); err != nil {
			return err
		}
		resumeKey := d.ID + ":resume"
		if !effectRecorded && !s.chat.HasLiveChatController(d.WorkerID) {
			for _, op := range m.Operations {
				if op.Kind == "resume" && op.Target == string(d.WorkerID) && op.State == "CONFIRMED_SUCCESS" {
					if err := s.requireStopped(d.WorkerID); err != nil {
						return err
					}
					// A confirmed earlier controller is now stopped. Reopen the
					// same native Session for the still-unsent action, with a new
					// durable controller intent but the original message identity.
					resumeKey = fmt.Sprintf("%s:resume:%d", d.ID, len(m.Operations))
				}
			}
		}
		if err := s.namedOperation(id, resumeKey, "resume", string(d.WorkerID), "", func() error {
			_, e := s.sessions.ResumeAgentWithMode(ports.WithCLAOOwner(s.ctx, id), d.WorkerID)
			return e
		}); err != nil {
			return err
		}
		message, _ := action["message"].(string)
		if err := s.namedOperation(id, d.ID+":send", "repair_send", string(d.WorkerID), d.ID+":fix", func() error {
			_, e := s.chat.Send(ports.WithCLAOOwner(s.ctx, id), d.WorkerID, ports.ChatUserMessage{Text: "在原目标/AC/Gate/范围不变的约束内处理本次局部修复：\n" + message, ClientMessageID: d.ID + ":fix", Origin: domain.MessageOriginAutomation})
			return e
		}); err != nil {
			return errors.Join(err, s.stopUnsentRepair(id, d))
		}
	}
	_, err := s.mutate(id, func(v *Mission) error {
		for i := range v.Decisions {
			if v.Decisions[i].ID == d.ID {
				v.Decisions[i].State, v.Decisions[i].Outcome = "APPLIED", "已执行一次动作；后续结果仍须验收"
			}
		}
		v.Checkpoint.Stage, v.Checkpoint.Digest = "worker", ""
		if d.Action == "REPLAN_SPAWN" {
			v.Checkpoint.AfterTurn = ""
		}
		v.State, v.Reason = "RUNNING", "Worker 处理已校验的修复要求"
		return nil
	})
	return err
}

func decisionEffectRecorded(m Mission, d Decision) bool {
	for _, op := range m.Operations {
		if op.ID == d.ID+":send" || (d.Action == "REPLAN_SPAWN" && d.Charged && op.Target == workerOwner(m)) {
			return true
		}
	}
	return false
}
func (s *Service) decisionInput(m Mission, d Decision) error {
	if !decisionEffectRecorded(m, d) {
		if d.EvidenceIndex < 0 || d.EvidenceIndex >= len(m.Evidence) {
			return errors.New("动作原始证据缺失")
		}
		check := *m.Checkpoint
		check.Digest = m.Evidence[d.EvidenceIndex].Digest
		m.Checkpoint = &check
	}
	return s.checkpointInput(m)
}
