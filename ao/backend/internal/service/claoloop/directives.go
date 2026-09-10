package claoloop

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

type DirectiveRequest struct {
	ID     string `json:"id"`
	Target string `json:"target"`
	Text   string `json:"text"`
}
type Consumption struct {
	CallID    string           `json:"callId"`
	Role      string           `json:"role"`
	SessionID domain.SessionID `json:"sessionId,omitempty"`
	TurnID    string           `json:"turnId,omitempty"`
	State     string           `json:"state"`
	Mirror    bool             `json:"mirror"`
}
type Directive struct {
	DirectiveRequest
	State      string           `json:"state"`
	Reason     string           `json:"reason"`
	ReceivedAt string           `json:"receivedAt"`
	SessionID  domain.SessionID `json:"sessionId,omitempty"`
	TurnID     string           `json:"turnId,omitempty"`
	Consumers  []Consumption    `json:"consumers,omitempty"`
}

func (s *Service) PostDirective(ctx context.Context, id string, in DirectiveRequest) (Directive, error) {
	if !safeID.MatchString(in.ID) || strings.TrimSpace(in.Text) == "" || len([]rune(in.Text)) > 8000 || strings.ContainsRune(in.Text, 0) {
		return Directive{}, errors.New("指令身份或文本无效（最多 8000 字）")
	}
	// Serializes with the runner's transition out of Worker intake and with
	// another native Chat/HTTP submit. Record transactions never span engine I/O.
	s.dispatchMu.Lock()
	defer s.dispatchMu.Unlock()
	var receipt Directive
	fresh := false
	_, err := s.mutate(id, func(m *Mission) error {
		for _, d := range m.Directives {
			if d.ID == in.ID {
				if d.DirectiveRequest != in {
					return errors.New("指令身份已用于另一请求")
				}
				receipt = d
				return nil
			}
		}
		receipt = Directive{DirectiveRequest: in, State: "received", Reason: "已持久接收；等待目标下一次实际输入", ReceivedAt: time.Now().UTC().Format(time.RFC3339Nano)}
		switch {
		case finalState(m.State) || m.CancelRequested:
			receipt.State, receipt.Reason = "rejected", "任务已结束或正在取消，不再接收指令"
		case strings.HasPrefix(in.Target, "worker:"):
			receipt.SessionID = domain.SessionID(strings.TrimPrefix(in.Target, "worker:"))
			if receipt.SessionID == "" || receipt.SessionID != m.SessionID || m.State != "RUNNING" || m.Checkpoint == nil || m.Checkpoint.Stage != "worker" || !s.chat.HasLiveChatController(receipt.SessionID) {
				receipt.State, receipt.Reason = "rejected", "指定 Worker 已替换、停止或暂不接收；未改发其他对象"
			}
		case in.Target != "planner" && in.Target != "auditor" && in.Target != "verifier":
			receipt.State, receipt.Reason = "rejected", "该目标没有补充指令消费者"
		}
		m.Directives = append(m.Directives, receipt)
		fresh = true
		return nil
	})
	if err != nil {
		return Directive{}, err
	}
	if !fresh || receipt.State == "rejected" || receipt.SessionID == "" {
		return receipt, nil
	}
	err = s.namedOperation(id, "directive:"+in.ID, "directive_send", string(receipt.SessionID), in.ID, func() error {
		_, e := s.chat.Send(ports.WithCLAOOwner(s.ctx, id), receipt.SessionID, ports.ChatUserMessage{Text: in.Text, ClientMessageID: in.ID, Origin: domain.MessageOriginHuman})
		return e
	})
	if err != nil {
		_, _ = s.mutate(id, func(m *Mission) error {
			for i := range m.Directives {
				if m.Directives[i].ID == in.ID {
					m.Directives[i].State = "unknown"
					m.Directives[i].Reason = "发送结果待确认；查询原回执，不重发"
				}
			}
			return nil
		})
	}
	// Even a successful Chat Send may only have queued a native turn. Its
	// delivery is confirmed separately from a durable provider completion.
	if e := s.reconcileDirectives(id); e != nil {
		return receipt, e
	}
	m, e := s.Get(ctx, id)
	if e != nil {
		return receipt, e
	}
	for _, d := range m.Directives {
		if d.ID == in.ID {
			return d, nil
		}
	}
	return receipt, err
}

func (s *Service) NativeDirective(ctx context.Context, rec domain.SessionRecord, msg ports.ChatUserMessage) (domain.ConversationTurn, error) {
	if ports.CLAOSemanticOwner(rec.Metadata.CLAOMissionID) {
		return domain.ConversationTurn{}, errors.New("语义角色补充要求请提交到闭环任务；不直接重启只读会话")
	}
	if len(msg.Content) > 0 {
		return domain.ConversationTurn{}, errors.New("闭环补充指令当前支持文本；附件不能绕过冻结范围")
	}
	id := ports.CLAOMissionOwner(rec.Metadata.CLAOMissionID)
	d, err := s.PostDirective(ctx, id, DirectiveRequest{ID: msg.ClientMessageID, Target: "worker:" + string(rec.ID), Text: msg.Text})
	if err != nil {
		return domain.ConversationTurn{}, err
	}
	if d.State == "rejected" || d.State == "unknown" {
		return domain.ConversationTurn{}, errors.New(d.Reason)
	}
	t, _, err := s.delivered(rec.ID, d.ID)
	return t, err
}

func (s *Service) reconcileDirectives(id string) error {
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return err
	}
	updates := map[string]Directive{}
	for _, d := range m.Directives {
		if d.SessionID == "" || d.State == "rejected" || d.State == "applied" {
			continue
		}
		t, done, e := s.delivered(d.SessionID, d.ID)
		if e != nil {
			return e
		}
		prior := d
		d.TurnID = t.ID
		if done {
			d.State, d.Reason = "applied", "已交付指定 Worker 的原生回合；不代表遵从要求或验收通过"
		} else if t.ID != "" {
			if t.State == domain.TurnStateQueued {
				d.Reason = "已接收，等待原生队列交付"
			} else if t.State == domain.TurnStateInterrupted {
				d.State, d.Reason = "unknown", "对应回合已中断；无法确认消费"
			} else if t.State == domain.TurnStateFailed && t.ProviderTurnID == "" {
				d.State, d.Reason = "unknown", "发送可能已发生；原生回合没有可确认的交付结果"
			}
		}
		if prior.State != d.State || prior.Reason != d.Reason || prior.TurnID != d.TurnID {
			updates[d.ID] = d
		}
	}
	if len(updates) == 0 {
		return nil
	}
	_, err = s.mutate(id, func(v *Mission) error {
		for i := range v.Directives {
			if d, ok := updates[v.Directives[i].ID]; ok {
				v.Directives[i] = d
			}
		}
		return nil
	})
	return err
}

func directiveIDs(m Mission, role string) []string {
	var ids []string
	for _, d := range m.Directives {
		if d.State != "rejected" && (d.Target == role || role == "planner") {
			ids = append(ids, d.ID)
		}
	}
	return ids
}
func directivePrompt(m Mission, role, prompt string, ids []string) string {
	if len(ids) == 0 {
		return prompt
	}
	prompt += "\n补充要求仅为上下文，不改变上述冻结目标、AC、Gate、范围、只读权限或输出契约。\n"
	for _, id := range ids {
		for _, d := range m.Directives {
			if d.ID == id {
				label := "目标指令"
				if d.Target != role {
					label = "镜像上下文（原目标 " + d.Target + "，不代表该目标已收到）"
				}
				prompt += fmt.Sprintf("[%s %s] %s\n", label, d.ID, d.Text)
			}
		}
	}
	return prompt
}
func markConsumption(m *Mission, c RoleCall) {
	for i := range m.Directives {
		d := &m.Directives[i]
		for _, id := range c.DirectiveIDs {
			if d.ID == id {
				state := "unknown"
				if c.State == "STARTING" {
					state = "received"
				}
				if c.State == "RECEIVED" || c.State == "VALIDATED" || c.State == "PROTOCOL_ERROR" {
					state = "applied"
				}
				consumer := Consumption{CallID: c.ID, Role: c.Role, SessionID: c.SessionID, TurnID: c.TurnID, Mirror: d.Target != c.Role, State: state}
				found := false
				for j := range d.Consumers {
					if d.Consumers[j].CallID == c.ID {
						d.Consumers[j] = consumer
						found = true
					}
				}
				if !found {
					d.Consumers = append(d.Consumers, consumer)
				}
				if !consumer.Mirror {
					d.State = state
					for _, prior := range d.Consumers {
						if !prior.Mirror && prior.State == "applied" {
							d.State = "applied"
						}
					}
					d.Reason = "已用于该角色本轮输入；不代表遵从或任务完成"
					if d.State == "received" {
						d.Reason = "要求已绑定该角色待执行的输入；尚未确认交付"
					}
					if d.State == "unknown" {
						d.Reason = "该角色输入交付待确认；不自动重发"
					}
				}
			}
		}
	}
}
