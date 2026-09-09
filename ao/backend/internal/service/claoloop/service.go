// Package claoloop owns acceptance scheduling for opt-in native AO Sessions.
// Native AO remains the sole runtime/session/workspace authority.
package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	chatsvc "github.com/aoagents/agent-orchestrator/backend/internal/service/chat"
	sessionmanager "github.com/aoagents/agent-orchestrator/backend/internal/session_manager"
)

type Criterion struct {
	ID          string `json:"id"`
	Description string `json:"description"`
}
type Request struct {
	ID             string              `json:"id"`
	ProjectID      domain.ProjectID    `json:"projectId"`
	Objective      string              `json:"objective"`
	AllowedPaths   []string            `json:"allowedPaths"`
	ForbiddenPaths []string            `json:"forbiddenPaths"`
	Criteria       []Criterion         `json:"criteria"`
	GateCommands   []string            `json:"gateCommands"`
	Agent          domain.AgentHarness `json:"agent"`
	Model          string              `json:"model"`
	MaxRepairs     int                 `json:"maxRepairs"`
	GateTimeout    float64             `json:"gateTimeout"`
}
type Operation struct {
	ID     string `json:"id"`
	Kind   string `json:"kind"`
	Target string `json:"target"`
	State  string `json:"state"`
	Reason string `json:"reason,omitempty"`
}
type Evidence struct {
	OK             bool            `json:"ok"`
	ReadError      string          `json:"readError,omitempty"`
	ScopeOK        bool            `json:"scopeOK"`
	Gate           json.RawMessage `json:"gate,omitempty"`
	Records        json.RawMessage `json:"records,omitempty"`
	Paths          []string        `json:"paths"`
	Forbidden      []string        `json:"forbidden"`
	Outside        []string        `json:"outside"`
	Digest         string          `json:"digest"`
	ResultHead     string          `json:"resultHead,omitempty"`
	VerifierPrompt string          `json:"verifierPrompt,omitempty"`
	Verification   json.RawMessage `json:"verification,omitempty"`
}
type Mission struct {
	Request           Request          `json:"request"`
	State             string           `json:"state"`
	Reason            string           `json:"reason"`
	Revision          int64            `json:"revision"`
	SessionID         domain.SessionID `json:"sessionId,omitempty"`
	VerifierSessionID domain.SessionID `json:"verifierSessionId,omitempty"`
	Base              string           `json:"base,omitempty"`
	ResolvedModel     string           `json:"resolvedModel,omitempty"`
	Workspace         string           `json:"workspace,omitempty"`
	ResultHead        string           `json:"resultHead,omitempty"`
	Repairs           int              `json:"repairs"`
	CancelRequested   bool             `json:"cancelRequested"`
	Operations        []Operation      `json:"operations"`
	Evidence          []Evidence       `json:"evidence"`
	UpdatedAt         string           `json:"updatedAt"`
}

func (m Mission) Terminal() bool {
	return m.State == "DONE" || m.State == "FAILED" || m.State == "CANCELLED" || m.State == "UNKNOWN"
}

type Store interface {
	CreateCLAOMission(context.Context, domain.CLAOMissionRecord) error
	GetCLAOMission(context.Context, string) (domain.CLAOMissionRecord, bool, error)
	ListCLAOMissions(context.Context) ([]domain.CLAOMissionRecord, error)
	SaveCLAOMission(context.Context, domain.CLAOMissionRecord) error
	GetSession(context.Context, domain.SessionID) (domain.SessionRecord, bool, error)
	ListAllSessions(context.Context) ([]domain.SessionRecord, error)
	GetProject(context.Context, string) (domain.ProjectRecord, bool, error)
}
type Sessions interface {
	Spawn(context.Context, ports.SpawnConfig) (domain.SessionRecord, int, int, error)
	ExitAgent(context.Context, domain.SessionID) (domain.SessionRecord, error)
	ResumeAgentWithMode(context.Context, domain.SessionID) (sessionmanager.RestoreResult, error)
}
type Chat interface {
	Snapshot(context.Context, domain.SessionID) (chatsvc.Snapshot, error)
	Send(context.Context, domain.SessionID, ports.ChatUserMessage) (domain.ConversationTurn, error)
	HasLiveChatController(domain.SessionID) bool
	PreflightChat(context.Context, domain.AgentHarness, ports.PermissionMode) error
}
type Acceptance interface {
	Source(context.Context, string) (string, error)
	Check(context.Context, Mission, bool, string, string) (Evidence, error)
}
type Service struct {
	store       Store
	sessions    Sessions
	chat        Chat
	acceptance  Acceptance
	log         *slog.Logger
	ctx         context.Context
	mu          sync.Mutex // only record transactions and launch admission, never external calls
	running     map[string]bool
	Poll        time.Duration
	TurnTimeout time.Duration
}

func New(ctx context.Context, store Store, sessions Sessions, chat Chat, acceptance Acceptance, log *slog.Logger) *Service {
	return &Service{ctx: ctx, store: store, sessions: sessions, chat: chat, acceptance: acceptance, log: log, running: map[string]bool{}, Poll: 500 * time.Millisecond, TurnTimeout: 30 * time.Minute}
}

func (s *Service) CheckApproval(ctx context.Context, rec domain.SessionRecord, activity domain.ConversationActivity) error {
	m, err := s.Get(ctx, rec.Metadata.CLAOMissionID)
	if err != nil {
		return err
	}
	if m.Terminal() || m.CancelRequested {
		return errors.New("闭环已停止接收审批")
	}
	policy, ok := s.acceptance.(interface {
		Approval(context.Context, Mission, domain.ConversationActivity) error
	})
	if !ok {
		return errors.New("闭环审批策略不可用")
	}
	// The immutable native session is the workspace authority, including the
	// short interval before the spawn receipt has been saved to the mission.
	m.Workspace = rec.Metadata.WorkspacePath
	return policy.Approval(ctx, m, activity)
}

var safeID = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_-]{7,79}$`)

func Validate(r Request) error {
	if !safeID.MatchString(r.ID) || r.ProjectID == "" || strings.TrimSpace(r.Objective) == "" || len(r.Objective) > 20000 {
		return errors.New("任务标识、项目或目标无效")
	}
	if len(r.AllowedPaths) == 0 || len(r.Criteria) == 0 || len(r.GateCommands) == 0 || len(r.Criteria) > 50 || len(r.GateCommands) > 20 {
		return errors.New("必须明确允许范围、验收条件和 Gate")
	}
	seen := map[string]bool{}
	for _, ac := range r.Criteria {
		if ac.ID == "" || strings.TrimSpace(ac.Description) == "" || seen[ac.ID] {
			return errors.New("验收条件缺失或 ID 重复")
		}
		seen[ac.ID] = true
	}
	for _, p := range append(append([]string{}, r.AllowedPaths...), r.ForbiddenPaths...) {
		if strings.TrimSpace(p) == "" || strings.ContainsAny(p, "\x00\r\n") {
			return errors.New("范围模式无效")
		}
	}
	for _, cmd := range r.GateCommands {
		if strings.TrimSpace(cmd) == "" || len(cmd) > 4000 || strings.ContainsAny(cmd, "\x00\r\n") {
			return errors.New("Gate 必须是明确的单条命令")
		}
	}
	if r.MaxRepairs < 0 || r.MaxRepairs > 3 || math.IsNaN(r.GateTimeout) || math.IsInf(r.GateTimeout, 0) || r.GateTimeout < 1 || r.GateTimeout > 600 {
		return errors.New("修复次数须为 0–3，Gate 超时须为 1–600 秒")
	}
	if r.Agent == "" {
		return errors.New("请选择执行器")
	}
	return nil
}
func decode(r domain.CLAOMissionRecord) (Mission, error) {
	var m Mission
	err := json.Unmarshal([]byte(r.Document), &m)
	m.State = r.State
	m.Revision = r.Revision
	m.UpdatedAt = r.UpdatedAt
	return m, err
}
func (s *Service) Get(ctx context.Context, id string) (Mission, error) {
	r, ok, err := s.store.GetCLAOMission(ctx, id)
	if err != nil {
		return Mission{}, err
	}
	if !ok {
		return Mission{}, errors.New("闭环任务不存在")
	}
	return decode(r)
}
func (s *Service) List(ctx context.Context) ([]Mission, error) {
	rows, err := s.store.ListCLAOMissions(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]Mission, 0, len(rows))
	for _, r := range rows {
		m, e := decode(r)
		if e != nil {
			return nil, e
		}
		out = append(out, m)
	}
	return out, nil
}
func record(m Mission) domain.CLAOMissionRecord {
	b, _ := json.Marshal(m)
	return domain.CLAOMissionRecord{ID: m.Request.ID, ProjectID: m.Request.ProjectID, State: m.State, Revision: m.Revision, Document: string(b), UpdatedAt: m.UpdatedAt}
}
func (s *Service) mutate(id string, f func(*Mission) error) (Mission, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return m, err
	}
	if err = f(&m); err != nil {
		return m, err
	}
	m.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if err = s.store.SaveCLAOMission(s.ctx, record(m)); err != nil {
		return m, err
	}
	m.Revision++
	return m, nil
}
func (s *Service) Create(ctx context.Context, r Request) (Mission, error) {
	if err := Validate(r); err != nil {
		return Mission{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if prior, ok, err := s.store.GetCLAOMission(ctx, r.ID); err != nil {
		return Mission{}, err
	} else if ok {
		m, e := decode(prior)
		a, _ := json.Marshal(m.Request)
		b, _ := json.Marshal(r)
		if string(a) != string(b) {
			return Mission{}, errors.New("任务提交标识已用于另一份确认")
		}
		return m, e
	}
	all, err := s.List(ctx)
	if err != nil {
		return Mission{}, err
	}
	for _, m := range all {
		if !m.Terminal() || m.State == "UNKNOWN" {
			return Mission{}, errors.New("已有闭环任务执行中或停止结果未知，请先处理")
		}
	}
	p, ok, err := s.store.GetProject(ctx, string(r.ProjectID))
	if err != nil {
		return Mission{}, err
	}
	if !ok || p.Kind.WithDefault() != domain.ProjectKindSingleRepo {
		return Mission{}, errors.New("当前闭环迁移支持单 Git 项目；普通 AO Session 能力不变")
	}
	base, err := s.acceptance.Source(ctx, p.Path)
	if err != nil {
		return Mission{}, err
	}
	if err = s.chat.PreflightChat(ctx, r.Agent, domain.PermissionModeDefault); err != nil {
		return Mission{}, err
	}
	m := Mission{Request: r, State: "SPAWNING", Reason: "准备原生 Session", Base: base, Revision: 1, Operations: []Operation{}, Evidence: []Evidence{}, UpdatedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	if err = s.store.CreateCLAOMission(ctx, record(m)); err != nil {
		return Mission{}, err
	}
	s.running[r.ID] = true
	go s.run(r.ID)
	return m, nil
}
func (s *Service) Cancel(ctx context.Context, id string) (Mission, error) {
	m, err := s.mutate(id, func(m *Mission) error {
		if m.State == "DONE" || m.State == "FAILED" || m.State == "CANCELLED" {
			return errors.New("终态不可取消")
		}
		m.CancelRequested = true
		m.Reason = "取消请求已持久接收；等待停止确认"
		return nil
	})
	if err != nil {
		return m, err
	}
	s.mu.Lock()
	if !s.running[id] {
		s.running[id] = true
		go func() {
			defer func() { s.mu.Lock(); delete(s.running, id); s.mu.Unlock() }()
			if err := s.cancelStopped(id); err != nil {
				_, _ = s.phase(id, "UNKNOWN", "取消已接收；停止尚未确认："+err.Error())
			}
		}()
	}
	s.mu.Unlock()
	return m, nil
}

// Exact immutable ownership is the only adoption key, never a title or time.
func (s *Service) ownedSessions(id string) ([]domain.SessionRecord, error) {
	rows, err := s.store.ListAllSessions(s.ctx)
	if err != nil {
		return nil, err
	}
	result := []domain.SessionRecord{}
	for _, r := range rows {
		if r.Metadata.CLAOMissionID == id || r.Metadata.CLAOMissionID == id+":verifier" {
			result = append(result, r)
		}
	}
	return result, nil
}

// Spawn rollback only deletes a native seed row, before initial turn delivery.
// Once a controller/turn is published, immutable ownership survives even when
// the caller loses the receipt. Adopt that association, never launch a replacement.
func (s *Service) reconcileSpawn(id string, cause error) error {
	owned, err := s.ownedSessions(id)
	if err != nil {
		return err // A failed read is not evidence that nothing started.
	}
	_, err = s.mutate(id, func(m *Mission) error {
		if len(m.Operations) == 0 {
			return nil
		}
		op := &m.Operations[len(m.Operations)-1]
		if op.Kind != "spawn" && op.Kind != "spawn_verifier" {
			return nil
		}
		if op.Reason == "" && cause != nil {
			op.Reason = cause.Error()
		}
		owner, priorID := id, m.SessionID
		if op.Kind == "spawn_verifier" {
			owner, priorID = id+":verifier", m.VerifierSessionID
		}
		found, allStopped := false, true
		for _, r := range owned {
			if r.Metadata.CLAOMissionID == id {
				m.SessionID, m.Workspace, m.ResolvedModel = r.ID, r.Metadata.WorkspacePath, r.Metadata.Model
			} else {
				m.VerifierSessionID = r.ID
			}
			found = found || r.Metadata.CLAOMissionID == owner
			allStopped = allStopped && r.Activity.State == domain.ActivityExited && !s.chat.HasLiveChatController(r.ID)
		}
		if !found && priorID == "" && op.State != "CONFIRMED_SUCCESS" {
			op.State = "CONFIRMED_FAILURE"
			op.Reason += "; native owner query: no Session was published; initial turn was not dispatched"
			// Verifier failure must not hide a missing or still-live Worker.
			if allStopped && (op.Kind == "spawn" || m.SessionID != "" && len(owned) > 0) {
				m.State = "FAILED"
				m.Reason = "启动失败，已确认没有启动本次执行：" + op.Reason
				return nil
			}
		}
		if op.State == "IN_FLIGHT" {
			op.State = "UNKNOWN"
		}
		m.State = "UNKNOWN"
		m.Reason = "启动结果尚未确认；不会重复启动。" + op.Reason
		if found {
			m.Reason += "（已按不可变 owner 关联原生 Session）"
		} else {
			m.Reason += "（无法确认目标 Session 事实）"
		}
		return nil
	})
	return err
}
func (s *Service) cancelStopped(id string) error {
	rows, err := s.ownedSessions(id)
	if err != nil {
		return err
	}
	if _, err = s.mutate(id, func(m *Mission) error {
		for _, r := range rows {
			if r.Metadata.CLAOMissionID == id {
				m.SessionID, m.Workspace, m.ResolvedModel = r.ID, r.Metadata.WorkspacePath, r.Metadata.Model
			} else {
				m.VerifierSessionID = r.ID
			}
		}
		return nil
	}); err != nil {
		return err
	}
	for _, r := range rows {
		if err = s.stopped(id, r.ID); err != nil {
			return err
		}
	}
	// Native SessionManager durably seeds ownership before launching a process.
	_, err = s.phase(id, "CANCELLED", "原生 Session 已确认停止；未重新执行任何指令")
	return err
}

// Recovery observes native rows; it never restarts an ambiguous operation.
func (s *Service) Recover() error {
	rows, err := s.List(s.ctx)
	if err != nil {
		return err
	}
	for _, m := range rows {
		if m.State == "DONE" || m.State == "FAILED" || m.State == "CANCELLED" {
			continue
		}
		owned, err := s.ownedSessions(m.Request.ID)
		if err != nil {
			return err
		}
		_, err = s.mutate(m.Request.ID, func(v *Mission) error {
			v.State = "UNKNOWN"
			v.Reason = "运行被中断，外部结果需确认；不会自动重发"
			for _, r := range owned {
				if r.Metadata.CLAOMissionID == v.Request.ID {
					v.SessionID = r.ID
					v.Workspace = r.Metadata.WorkspacePath
				} else {
					v.VerifierSessionID = r.ID
				}
			}
			for i := range v.Operations {
				if v.Operations[i].State == "IN_FLIGHT" {
					v.Operations[i].State = "UNKNOWN"
				}
			}
			noDispatch := len(v.Operations) == 0 || len(v.Operations) == 1 && v.Operations[0].Kind == "spawn" && v.Operations[0].State != "CONFIRMED_SUCCESS"
			if len(owned) == 0 && v.SessionID == "" && v.VerifierSessionID == "" && v.ResultHead == "" && noDispatch {
				v.State = "FAILED"
				v.Reason = "启动在原生 Session 创建前中断；没有启动 Worker"
				if len(v.Operations) > 0 {
					v.Operations[0].State = "CONFIRMED_FAILURE"
					v.Operations[0].Reason += "; native owner query: no Session was published"
				}
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	return nil
}
func (s *Service) phase(id, state, reason string) (Mission, error) {
	return s.mutate(id, func(m *Mission) error { m.State = state; m.Reason = reason; return nil })
}

var errCancelled = errors.New("cancel_requested")

func (s *Service) operation(id, kind, target string, call func() error) error {
	var index int
	_, err := s.mutate(id, func(m *Mission) error {
		if m.CancelRequested && kind != "stop" {
			return errCancelled
		}
		index = len(m.Operations)
		m.Operations = append(m.Operations, Operation{ID: fmt.Sprintf("%s:%d", id, index), Kind: kind, Target: target, State: "IN_FLIGHT"})
		return nil
	})
	if err != nil {
		return err
	}
	callErr := call()
	_, err = s.mutate(id, func(m *Mission) error {
		if callErr != nil {
			m.Operations[index].State = "UNKNOWN"
			m.Operations[index].Reason = callErr.Error()
			m.State = "UNKNOWN"
			m.Reason = kind + " 结果未确认：" + callErr.Error()
		} else {
			m.Operations[index].State = "CONFIRMED_SUCCESS"
		}
		return nil
	})
	if err != nil {
		return err
	}
	return callErr
}
func (s *Service) stopped(id string, sid domain.SessionID) error {
	return s.operation(id, "stop", string(sid), func() error {
		r, ok, err := s.store.GetSession(s.ctx, sid)
		if err != nil || !ok {
			return fmt.Errorf("session fact unavailable: %v", err)
		}
		if r.Activity.State != domain.ActivityExited && !s.chat.HasLiveChatController(sid) {
			return errors.New("no live controller handle; stopped fact is unknown")
		}
		if r.Activity.State != domain.ActivityExited {
			if _, err = s.sessions.ExitAgent(s.ctx, sid); err != nil {
				return err
			}
		}
		r, ok, err = s.store.GetSession(s.ctx, sid)
		if err != nil || !ok || r.Activity.State != domain.ActivityExited || s.chat.HasLiveChatController(sid) {
			return errors.New("AO has not confirmed controller stopped")
		}
		return nil
	})
}
func (s *Service) waitTurn(id string, sid domain.SessionID, after string) (chatsvc.Snapshot, error) {
	ticker := time.NewTicker(s.Poll)
	defer ticker.Stop()
	timeout := time.NewTimer(s.TurnTimeout)
	defer timeout.Stop()
	for {
		m, err := s.Get(s.ctx, id)
		if err != nil {
			return chatsvc.Snapshot{}, err
		}
		if m.CancelRequested {
			return chatsvc.Snapshot{}, errors.New("cancel_requested")
		}
		snap, err := s.chat.Snapshot(s.ctx, sid)
		if err != nil {
			return snap, err
		}
		for i := len(snap.Turns) - 1; i >= 0; i-- {
			t := snap.Turns[i]
			if t.HandledBySessionID != sid || t.RolledBackAt != nil {
				continue
			}
			if t.ID == after {
				break
			}
			if t.State.Terminal() {
				if t.State != domain.TurnStateCompleted {
					return snap, fmt.Errorf("AO turn %s: %s", t.State, t.ErrorMessage)
				}
				if snap.Controller == ports.ChatControllerReady || snap.Controller == ports.ChatControllerStopped {
					return snap, nil
				}
			}
			break
		}
		if snap.Controller == ports.ChatControllerStopped {
			return snap, errors.New("controller stopped without a confirmed completed turn")
		}
		select {
		case <-s.ctx.Done():
			return snap, s.ctx.Err()
		case <-timeout.C:
			return snap, errors.New("Worker/Verifier 等待超过 30 分钟上限")
		case <-ticker.C:
		}
	}
}
func (s *Service) run(id string) {
	defer func() { s.mu.Lock(); delete(s.running, id); s.mu.Unlock() }()
	if err := s.execute(id); err != nil {
		if errors.Is(err, errCancelled) {
			if stopErr := s.cancelStopped(id); stopErr == nil {
				return
			} else {
				err = stopErr
			}
		}
		s.log.Error("CLAO loop paused", "mission", id, "error", err)
		m, e := s.Get(s.ctx, id)
		if e == nil && len(m.Operations) > 0 {
			op := m.Operations[len(m.Operations)-1]
			if op.Kind == "spawn" || op.Kind == "spawn_verifier" {
				if e = s.reconcileSpawn(id, err); e != nil {
					s.log.Error("CLAO spawn reconciliation failed", "mission", id, "error", e)
					_, _ = s.phase(id, "UNKNOWN", "启动对账失败，不会自动重试："+e.Error()+"；原错误："+err.Error())
				}
				return
			}
		}
		if e == nil && !m.Terminal() {
			_, _ = s.phase(id, "UNKNOWN", err.Error())
		}
	}
}
func (s *Service) execute(id string) error {
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return err
	}
	var worker domain.SessionRecord
	err = s.operation(id, "spawn", "worker", func() error {
		var e error
		// Seed Session numbers can be reused after failed-start rollback, while
		// its Git branch survives. A new mission gets its own branch; no cleanup
		// or history rewrite is needed to create a genuinely new attempt.
		worker, _, _, e = s.sessions.Spawn(ports.WithCLAOOwner(s.ctx, id), ports.SpawnConfig{ProjectID: m.Request.ProjectID, Branch: "clao/" + id + "/worker", Kind: domain.KindWorker, Harness: m.Request.Agent, RequestedMode: domain.SessionModeChat, CLAOMissionID: id, CLAOBaseSHA: m.Base, AgentConfig: ports.AgentConfig{Model: m.Request.Model, Permissions: domain.PermissionModeDefault}, Prompt: workerPrompt(m), DisplayName: "闭环 · " + m.Request.Objective})
		return e
	})
	if err != nil {
		return err
	}
	m, err = s.mutate(id, func(v *Mission) error {
		v.SessionID = worker.ID
		v.ResolvedModel = worker.Metadata.Model
		v.Workspace = worker.Metadata.WorkspacePath
		v.State = "RUNNING"
		v.Reason = "Worker 执行中"
		return nil
	})
	if err != nil {
		return err
	}
	if worker.Metadata.DiffBaseSHA != m.Base {
		if err = s.stopped(id, worker.ID); err != nil {
			return err
		}
		_, err = s.phase(id, "FAILED", "AO workspace base differs from frozen source")
		return err
	}
	lastTurn := ""
	for {
		snap, waitErr := s.waitTurn(id, worker.ID, lastTurn)
		if _, err = s.phase(id, "STOPPING", "等待 AO 确认 Worker 停止"); err != nil {
			return err
		}
		if err = s.stopped(id, worker.ID); err != nil {
			return err
		}
		m, err = s.Get(s.ctx, id)
		if err != nil {
			return err
		}
		if m.CancelRequested {
			_, err = s.phase(id, "CANCELLED", "Worker 已确认停止")
			return err
		}
		if waitErr != nil {
			_, err = s.phase(id, "FAILED", waitErr.Error())
			return err
		}
		if len(snap.Turns) > 0 {
			lastTurn = snap.Turns[len(snap.Turns)-1].ID
		}
		if _, err = s.phase(id, "GATE", "执行 Gate、完整性与范围验收"); err != nil {
			return err
		}
		proof, e := s.acceptance.Check(s.ctx, m, false, "", "")
		if e != nil {
			return e
		}
		m, err = s.mutate(id, func(v *Mission) error { v.Evidence = append(v.Evidence, proof); return nil })
		if err != nil {
			return err
		}
		if m.CancelRequested {
			_, err = s.phase(id, "CANCELLED", "Worker 已停止，取消验收")
			return err
		}
		if !proof.OK {
			if proof.ReadError != "" || !proof.ScopeOK || m.Repairs >= m.Request.MaxRepairs {
				_, err = s.phase(id, "FAILED", "Gate 或确定性范围验收未通过")
				return err
			}
			m, err = s.mutate(id, func(v *Mission) error {
				v.Repairs++
				v.State = "REPAIRING"
				v.Reason = "发送一次有界修复指令"
				return nil
			})
			if err != nil {
				return err
			}
			if err = s.operation(id, "resume", string(worker.ID), func() error {
				_, e := s.sessions.ResumeAgentWithMode(ports.WithCLAOOwner(s.ctx, id), worker.ID)
				return e
			}); err != nil {
				return err
			}
			m, _ = s.Get(s.ctx, id)
			if m.CancelRequested {
				if err = s.stopped(id, worker.ID); err != nil {
					return err
				}
				_, err = s.phase(id, "CANCELLED", "Worker 已停止")
				return err
			}
			if err = s.operation(id, "repair_send", string(worker.ID), func() error {
				_, e := s.chat.Send(ports.WithCLAOOwner(s.ctx, id), worker.ID, ports.ChatUserMessage{Text: "修复以下实际 Gate 失败，不改变目标、范围或验收条件：\n" + string(proof.Records), ClientMessageID: fmt.Sprintf("%s:repair:%d", id, m.Repairs), Origin: domain.MessageOriginAutomation})
				return e
			}); err != nil {
				return err
			}
			if _, err = s.phase(id, "RUNNING", "Worker 修复中"); err != nil {
				return err
			}
			continue
		}
		if _, err = s.phase(id, "MATERIALIZING", "固定验收产物；不写回原项目"); err != nil {
			return err
		}
		frozen, e := s.acceptance.Check(s.ctx, m, true, proof.Digest, "")
		if e != nil {
			return e
		}
		if !frozen.OK || frozen.ResultHead == "" {
			return errors.New("failed to freeze accepted artifact: " + frozen.ReadError)
		}
		m, err = s.mutate(id, func(v *Mission) error {
			v.ResultHead = frozen.ResultHead
			public := frozen
			public.VerifierPrompt = ""
			v.Evidence = append(v.Evidence, public)
			v.State = "VERIFYING"
			v.Reason = "独立原生 Session 进行结构化复核"
			return nil
		})
		if err != nil {
			return err
		}
		return s.verify(id, m, frozen)
	}
}
func (s *Service) verify(id string, m Mission, proof Evidence) error {
	if proof.VerifierPrompt == "" {
		return errors.New("complete verifier evidence unavailable")
	}
	var review domain.SessionRecord
	err := s.operation(id, "spawn_verifier", "verifier", func() error {
		var e error
		review, _, _, e = s.sessions.Spawn(ports.WithCLAOOwner(s.ctx, id), ports.SpawnConfig{ProjectID: m.Request.ProjectID, Branch: "clao/" + id + "/verifier", Kind: domain.KindWorker, Harness: m.Request.Agent, RequestedMode: domain.SessionModeChat, CLAOMissionID: id + ":verifier", CLAOBaseSHA: m.ResultHead, CLAOReview: true, AgentConfig: ports.AgentConfig{Model: m.ResolvedModel, Permissions: domain.PermissionModeDefault}, Prompt: proof.VerifierPrompt, DisplayName: "验收 · " + m.Request.Objective})
		return e
	})
	if err != nil {
		return err
	}
	if _, err = s.mutate(id, func(v *Mission) error { v.VerifierSessionID = review.ID; return nil }); err != nil {
		return err
	}
	snap, waitErr := s.waitTurn(id, review.ID, "")
	if err = s.stopped(id, review.ID); err != nil {
		return err
	}
	m, err = s.Get(s.ctx, id)
	if err != nil {
		return err
	}
	if m.CancelRequested {
		_, err = s.phase(id, "CANCELLED", "执行与复核 Session 均已停止")
		return err
	}
	if waitErr != nil {
		_, err = s.phase(id, "FAILED", "复核失败："+waitErr.Error())
		return err
	}
	text := ""
	turn := ""
	if len(snap.Turns) > 0 {
		turn = snap.Turns[len(snap.Turns)-1].ID
	}
	for _, msg := range snap.Messages {
		if msg.Role == domain.MessageRoleAssistant && !msg.Streaming && msg.TurnID == turn {
			text = msg.Text
		}
	}
	if strings.TrimSpace(text) == "" {
		_, err = s.phase(id, "FAILED", "Verifier 没有提供结构化结果；不能仅凭回合结束确认通过")
		return err
	}
	// The reviewer's separate worktree may never alter the accepted worker tree.
	// Even an engine ignoring the read-only instruction cannot turn edits into PASS.
	check := m
	check.Workspace = review.Metadata.WorkspacePath
	check.Base = m.ResultHead
	clean, e := s.acceptance.Source(s.ctx, check.Workspace)
	if e != nil || clean != m.ResultHead {
		_, err = s.phase(id, "FAILED", "Verifier 工作区发生改动或不可取证")
		return err
	}
	final, e := s.acceptance.Check(s.ctx, m, false, "", text)
	if e != nil {
		return e
	}
	m, err = s.mutate(id, func(v *Mission) error {
		v.Evidence = append(v.Evidence, final)
		if v.CancelRequested {
			v.State = "CANCELLED"
			v.Reason = "已停止"
		} else if final.OK {
			v.State = "DONE"
			v.Reason = "最终 Gate、范围及独立 Verifier PASS"
		} else {
			v.State = "FAILED"
			v.Reason = "最终验收未通过：" + final.ReadError
		}
		return nil
	})
	return err
}
func workerPrompt(m Mission) string {
	b, _ := json.Marshal(m.Request)
	return "CLAO 验收驱动任务。仅在本 Session 隔离工作区执行；不得 push、写回原项目或启动其他 Worker。不得改变验收条件。完成后等待程序运行 Gate；不得把自己的完成声明当作最终验收。范围与 Gate 如下：\n" + string(b)
}
