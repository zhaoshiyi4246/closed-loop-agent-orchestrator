package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"strings"
	"sync"
	"time"
)

type sourceCore interface {
	SourcePreview(context.Context, domain.ProjectID, string) (SourcePreview, error)
	FreezeSource(context.Context, domain.ProjectID, string, string, string) (SourceSnapshot, error)
	Integrate(context.Context, Mission, []Mission) (IntegrationResult, error)
}

func (m Mission) sourceRepository() string {
	if m.Source != nil {
		return m.Source.ProjectPath
	}
	return ""
}
func subtaskIdentity(id string) (string, string, bool) {
	parent, suffix, ok := strings.Cut(id, "--task-")
	return parent, id, ok && (suffix == "1" || suffix == "2") && safeID.MatchString(parent)
}

// Called under the same service mutex as any other record mutation. Children
// are checkpoints inside the original Mission document, not new controllers.
func (s *Service) mutateSubtask(parent, id string, f func(*Mission) error) (Mission, error) {
	outer, err := s.Get(s.ctx, parent)
	if err != nil {
		return Mission{}, err
	}
	for i := range outer.Subtasks {
		v := &outer.Subtasks[i]
		if v.Request.ID != id {
			continue
		}
		v.CancelRequested = v.CancelRequested || outer.CancelRequested
		if err = f(v); err != nil {
			return *v, err
		}
		totalRepairs, totalReplans := 0, 0
		for _, sub := range outer.Subtasks {
			totalRepairs += sub.Repairs
			totalReplans += sub.Replans
		}
		if totalRepairs+totalReplans > outer.Request.MaxRepairs || totalReplans > outer.Request.MaxReplans {
			return *v, errors.New("Mission 共享修复/替换预算耗尽")
		}
		outer.Repairs, outer.Replans = totalRepairs, totalReplans
		v.Revision++
		v.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
		outer.UpdatedAt = v.UpdatedAt
		if err = s.store.SaveCLAOMission(s.ctx, record(outer)); err != nil {
			return *v, err
		}
		return *v, nil
	}
	return Mission{}, errors.New("原任务没有该子任务")
}

func (s *Service) freezeSource(id string, m Mission) error {
	core, ok := s.acceptance.(sourceCore)
	if !ok || m.Source == nil {
		return errors.New("来源快照能力不可用")
	}
	source, err := core.FreezeSource(s.ctx, m.Request.ProjectID, m.SourcePath, id, m.Request.SourceRevision)
	if err != nil {
		_, _ = s.phase(id, "FAILED", "来源固定失败，未启动 Worker："+err.Error())
		return err
	}
	_, err = s.mutate(id, func(v *Mission) error {
		if v.CancelRequested {
			return errCancelled
		}
		v.Source = &source
		v.Base = source.Base
		v.Checkpoint.Stage = "worker"
		if v.Request.MaxTasks == 2 {
			v.Checkpoint.Stage = "decompose"
		}
		return nil
	})
	return err
}

func (s *Service) decompose(id string, m Mission) error {
	core, ok := s.acceptance.(roleCore)
	if !ok {
		return errors.New("Planner 契约不可用")
	}
	prepared := m
	prepared.Workspace = m.sourceRepository()
	if prepared.Workspace == "" {
		prepared.Workspace = m.SourcePath
	}
	proof, err := core.Role(s.ctx, prepared, "decomposition", nil, nil)
	if err != nil || !proof.OK {
		return s.human(id, fmt.Sprintf("分解输入不可用：%v %s", err, proof.ReadError))
	}
	text, err := s.semantic(id, "planner", id+":decompose", "", proof.RolePrompt)
	if err != nil {
		return err
	}
	checked, err := core.Role(s.ctx, prepared, "decomposition", nil, &text)
	if err != nil || !checked.OK {
		return s.human(id, fmt.Sprintf("分解未通过范围/AC/依赖校验：%v %s", err, checked.ReadError))
	}
	var plan struct {
		Subtasks []struct {
			Objective string      `json:"objective"`
			Allowed   []string    `json:"allowed_paths"`
			Criteria  []Criterion `json:"acceptance_criteria"`
			Gates     []string    `json:"gate_commands"`
		} `json:"subtasks"`
	}
	if err = json.Unmarshal(checked.RoleResult, &plan); err != nil {
		return err
	}
	_, err = s.callUpdate(id, id+":decompose", func(c *RoleCall) { c.Result = checked.RoleResult; c.State = "VALIDATED" })
	if err != nil {
		return err
	}
	_, err = s.mutate(id, func(v *Mission) error {
		if v.CancelRequested {
			return errCancelled
		}
		v.Plan = checked.RoleResult
		if len(plan.Subtasks) == 1 {
			v.Checkpoint.Stage = "worker"
			return nil
		}
		if len(plan.Subtasks) != 2 {
			return errors.New("分解数量无效")
		}
		if len(v.Subtasks) > 0 {
			return errors.New("已有子任务，禁止重新分解")
		}
		for i, sub := range plan.Subtasks {
			req := v.Request
			req.ID = fmt.Sprintf("%s--task-%d", id, i+1)
			req.ParentID = ""
			req.MaxTasks = 1
			req.Objective = sub.Objective
			req.AllowedPaths = sub.Allowed
			req.Criteria = sub.Criteria
			req.GateCommands = sub.Gates
			v.Subtasks = append(v.Subtasks, Mission{CoordinatorID: id, Request: req, Source: v.Source, SourcePath: v.SourcePath, Base: v.Base, Roles: v.Roles, State: "SPAWNING", Reason: "等待独立 Worker", Revision: 1, UpdatedAt: v.UpdatedAt, Checkpoint: &Checkpoint{Stage: "worker", Proof: -1}, Operations: []Operation{}, Evidence: []Evidence{}})
		}
		v.Checkpoint.Stage = "children"
		v.State = "RUNNING"
		v.Reason = "两个独立子任务执行；完成后仍须集成与最终验收"
		return nil
	})
	return err
}

func (s *Service) runChildren(id string, m Mission) error {
	if len(m.Subtasks) != 2 {
		return errors.New("独立子任务记录不完整")
	}
	var wg sync.WaitGroup
	// Check every saved lane before starting any continuation. An invalid later
	// lane must never release the parent claim with an earlier lane still live.
	for _, child := range m.Subtasks {
		if child.State != "DONE" && finalState(child.State) {
			return s.human(id, "子任务未通过："+child.Reason)
		}
	}
	// Parent retains the sole scheduling claim. Each lane reuses execute/run;
	// no Create, initial replay, separate runtime or externally claimable owner.
	for _, child := range m.Subtasks {
		if child.State == "DONE" {
			continue
		}
		wg.Add(1)
		go func(cid string) { defer wg.Done(); s.run(cid) }(child.Request.ID)
	}
	wg.Wait()
	current, err := s.Get(s.ctx, id)
	if err != nil {
		return err
	}
	if current.CancelRequested {
		return errCancelled
	}
	for _, child := range current.Subtasks {
		if child.State != "DONE" {
			return errors.New("子任务尚未通过或执行待确认：" + child.Reason)
		}
	}
	_, err = s.advance(id, "integrate", "MATERIALIZING", "集成两个已停止并验收的子任务成果")
	return err
}

func (s *Service) integrate(id string, m Mission) error {
	if m.Checkpoint.LocalState != "" {
		return errors.New("原集成操作的结果尚未确认，不能重跑")
	}
	children := m.Subtasks
	if len(children) == 0 {
		children = []Mission{m}
	}
	for _, child := range children {
		if err := s.requireStopped(child.SessionID); err != nil {
			return err
		}
		if child.ResultHead == "" {
			return errors.New("子任务固定结果缺失")
		}
	}
	core, ok := s.acceptance.(sourceCore)
	if !ok {
		return errors.New("隔离集成能力不可用")
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
	result, err := core.Integrate(s.ctx, m, children)
	if err != nil {
		return err
	}
	_, err = s.mutate(id, func(v *Mission) error {
		v.Workspace = result.Workspace
		v.ResultHead = result.ResultHead
		v.Checkpoint.LocalState = ""
		v.Checkpoint.Digest = ""
		v.Checkpoint.Stage = "integration_gate"
		v.State = "GATE"
		v.Reason = "对固定集成结果运行 Mission 全部验收"
		return nil
	})
	return err
}

func (s *Service) deliveryStopped(m Mission) error {
	if len(m.Subtasks) > 0 {
		for _, child := range m.Subtasks {
			if err := s.requireStopped(child.SessionID); err != nil {
				return err
			}
		}
		return nil
	}
	return s.requireStopped(m.SessionID)
}
