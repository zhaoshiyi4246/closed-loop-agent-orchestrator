package claoloop

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/process"
)

type LegacyImportRequest struct {
	ConfigPath  string `json:"configPath,omitempty"`
	HistoryPath string `json:"historyPath,omitempty"`
}
type LegacyConnection struct {
	AuthRevision int      `json:"authRevision"`
	AuthPending  bool     `json:"authPending,omitempty"`
	ID           string   `json:"id"`
	Name         string   `json:"name"`
	Service      string   `json:"service"`
	Model        string   `json:"model"`
	Endpoint     string   `json:"endpoint,omitempty"`
	Billing      string   `json:"billing"`
	Compatible   bool     `json:"compatible"`
	Reason       string   `json:"reason"`
	Roles        []string `json:"roles"`
	// Internal/frozen transport configuration contains only an OS reference,
	// never its value. Catalog() explicitly omits it from public listing.
	Profile json.RawMessage `json:"profile,omitempty"`
}
type LegacyItem struct {
	ID         string          `json:"id"`
	Kind       string          `json:"kind"`
	Document   json.RawMessage `json:"document"`
	ImportedAt string          `json:"importedAt,omitempty"`
}
type LegacyCatalog struct {
	Histories      []LegacyItem       `json:"histories"`
	Connections    []LegacyConnection `json:"connections"`
	Configurations []LegacyItem       `json:"configurations"`
	Issues         []string           `json:"issues"`
}
type LegacyCredentialStatus struct {
	AuthRevision int    `json:"authRevision"`
	ID           string `json:"id"`
	Status       string `json:"status"`
}
type LegacyResponse struct {
	OK              bool            `json:"ok"`
	Error           string          `json:"error,omitempty"`
	Category        string          `json:"category,omitempty"`
	Rows            []LegacyItem    `json:"rows,omitempty"`
	Issues          []string        `json:"issues,omitempty"`
	Text            string          `json:"text,omitempty"`
	Configured      bool            `json:"configured,omitempty"`
	ConfirmedModel  string          `json:"confirmedModel,omitempty"`
	ModelFactSource string          `json:"modelFactSource,omitempty"`
	Usage           json.RawMessage `json:"usage,omitempty"`
}
type legacyStore interface {
	ImportCLAORecords(context.Context, []domain.CLAOImportRecord) error
	ListCLAOImports(context.Context) ([]domain.CLAOImportRecord, error)
}
type legacyAuthStore interface {
	UpdateCLAOImportAuth(context.Context, string, int, bool) (int, error)
}

// Reconnection writes a new native-owned generation, leaving old user refs
// intact. A crash can invalidate a draft but cannot substitute a different Key
// into an already frozen request or another connection sharing the old ref.
func bindLegacyAuth(c *LegacyConnection, row domain.CLAOImportRecord) error {
	c.ID, c.AuthRevision, c.AuthPending = row.ID, row.AuthRevision, row.AuthPending
	if row.AuthRevision == 0 {
		return nil
	}
	var profile map[string]any
	if err := json.Unmarshal(c.Profile, &profile); err != nil {
		return err
	}
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s:%d", row.ID, row.AuthRevision)))
	profile["credential_ref"] = fmt.Sprintf("native-%x", digest[:16])
	raw, err := json.Marshal(profile)
	c.Profile = raw
	return err
}

type legacyCore interface {
	Legacy(context.Context, map[string]any) (LegacyResponse, error)
}

func (a PythonAcceptance) Legacy(ctx context.Context, request map[string]any) (LegacyResponse, error) {
	if a.Python == "" || a.CoreRoot == "" {
		return LegacyResponse{}, errors.New("旧版兼容核心未配置")
	}
	raw, err := json.Marshal(request)
	if err != nil {
		return LegacyResponse{}, err
	}
	cmd := process.CommandContext(ctx, a.Python, "-m", "loopcore.ao_legacy")
	cmd.Env = append(gateEnv(), "PYTHONPATH="+filepath.Join(a.CoreRoot, "src"))
	cmd.Dir = a.CoreRoot
	cmd.Stdin = bytes.NewReader(raw)
	var out, stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr
	if err = cmd.Run(); err != nil {
		return LegacyResponse{}, errors.New("旧兼容调用未返回确认；不会回显输入或重发")
	}
	if out.Len() > 8*1024*1024 {
		return LegacyResponse{}, errors.New("旧兼容结果超出读取边界")
	}
	var response LegacyResponse
	if err = json.Unmarshal(out.Bytes(), &response); err != nil {
		return response, errors.New("旧兼容结果无法读取")
	}
	return response, nil
}

func (s *Service) LegacyCatalog(ctx context.Context) (LegacyCatalog, error) {
	out := LegacyCatalog{Histories: []LegacyItem{}, Connections: []LegacyConnection{}, Configurations: []LegacyItem{}, Issues: []string{}}
	st, ok := s.store.(legacyStore)
	if !ok {
		return out, errors.New("当前存储不支持旧记录导入")
	}
	rows, err := st.ListCLAOImports(ctx)
	if err != nil {
		return out, err
	}
	for _, r := range rows {
		item := LegacyItem{ID: r.ID, Kind: r.Kind, Document: json.RawMessage(r.Document), ImportedAt: r.CreatedAt}
		switch r.Kind {
		case "history":
			out.Histories = append(out.Histories, item)
		case "configuration":
			out.Configurations = append(out.Configurations, item)
		case "connection":
			var c LegacyConnection
			if err = json.Unmarshal([]byte(r.Document), &c); err != nil {
				return out, errors.New("已导入连接记录不可读取")
			}
			c.ID = r.ID
			c.AuthRevision, c.AuthPending = r.AuthRevision, r.AuthPending
			c.Profile = nil
			out.Connections = append(out.Connections, c)
		default:
			return out, errors.New("未知旧导入记录类型")
		}
	}
	return out, nil
}

func (s *Service) ImportLegacy(ctx context.Context, r LegacyImportRequest) (LegacyCatalog, error) {
	st, ok := s.store.(legacyStore)
	if !ok {
		return LegacyCatalog{}, errors.New("旧记录导入不可用")
	}
	core, ok := s.acceptance.(legacyCore)
	if !ok {
		return LegacyCatalog{}, errors.New("旧版兼容核心不可用")
	}
	for _, p := range []string{r.ConfigPath, r.HistoryPath} {
		if p != "" && (!filepath.IsAbs(p) || strings.ContainsAny(p, "\x00\r\n")) {
			return LegacyCatalog{}, errors.New("请选择明确的本地旧配置或 runtime 路径")
		}
	}
	if r.ConfigPath == "" && r.HistoryPath == "" {
		return LegacyCatalog{}, errors.New("请明确选择要导入的旧文件；不会自动扫描")
	}
	result, err := core.Legacy(ctx, map[string]any{"action": "import", "configPath": r.ConfigPath, "historyPath": r.HistoryPath})
	if err != nil {
		return LegacyCatalog{}, err
	}
	if !result.OK {
		return LegacyCatalog{}, errors.New(result.Error)
	}
	rows := []domain.CLAOImportRecord{}
	for _, item := range result.Rows {
		if !safeID.MatchString(item.ID) || item.Kind != "history" && item.Kind != "connection" && item.Kind != "configuration" || !json.Valid(item.Document) {
			return LegacyCatalog{}, errors.New("导入投影无效；未写入")
		}
		// Canonical JSON makes repeat import independent of map key order.
		var value any
		if err = json.Unmarshal(item.Document, &value); err != nil {
			return LegacyCatalog{}, err
		}
		doc, _ := json.Marshal(value)
		rows = append(rows, domain.CLAOImportRecord{ID: item.ID, Kind: item.Kind, Document: string(doc), CreatedAt: time.Now().UTC().Format(time.RFC3339Nano)})
	}
	if err = st.ImportCLAORecords(ctx, rows); err != nil {
		return LegacyCatalog{}, err
	}
	out, err := s.LegacyCatalog(ctx)
	out.Issues = result.Issues
	return out, err
}

// Explicit user action only. Service and OS reference come exclusively from
// the selected immutable imported connection, never from browser parameters.
func (s *Service) ReconnectLegacy(ctx context.Context, id, key string) (LegacyCredentialStatus, error) {
	out := LegacyCredentialStatus{ID: id}
	if !safeID.MatchString(id) || len(key) < 1 || len(key) > 2048 {
		return out, errors.New("连接标识或 API Key 格式不合法")
	}
	for _, c := range key {
		if c < 33 || c > 126 {
			return out, errors.New("API Key 不能包含空白或控制字符")
		}
	}
	st, ok := s.store.(legacyStore)
	if !ok {
		return out, errors.New("旧连接存储不可用")
	}
	core, ok := s.acceptance.(legacyCore)
	if !ok {
		return out, errors.New("系统凭据入口不可用")
	}
	rows, err := st.ListCLAOImports(ctx)
	if err != nil {
		return out, err
	}
	for _, r := range rows {
		if r.ID != id || r.Kind != "connection" {
			continue
		}
		var c LegacyConnection
		if err = json.Unmarshal([]byte(r.Document), &c); err != nil || !c.Compatible || c.Billing != "standard_api" {
			return out, errors.New("旧连接不能安全映射，请选择原生服务或导入受支持的配置")
		}
		auth, ok := s.store.(legacyAuthStore)
		if !ok {
			return out, errors.New("连接认证版本存储不可用")
		}
		revision, e := auth.UpdateCLAOImportAuth(ctx, id, r.AuthRevision, true)
		if e != nil {
			return out, e
		}
		r.AuthRevision, r.AuthPending = revision, true
		if e = bindLegacyAuth(&c, r); e != nil {
			return out, e
		}
		result, e := core.Legacy(ctx, map[string]any{"action": "credential", "profile": c.Profile, "apiKey": key})
		if e != nil || !result.OK || !result.Configured {
			return out, errors.New("系统凭据保存失败；未标记已配置，未回显密钥")
		}
		if _, e = auth.UpdateCLAOImportAuth(ctx, id, revision, false); e != nil {
			return out, e
		}
		out.AuthRevision = revision
		out.Status = "configured"
		return out, nil
	}
	return out, errors.New("所选旧连接不存在")
}

func (s *Service) freezeLegacyRole(ctx context.Context, role string, chosen RoleChoice, consent []string) (FrozenRole, error) {
	if role != "planner" && role != "auditor" && role != "verifier" {
		return FrozenRole{}, errors.New("标准 API 连接不能作为编码 Worker")
	}
	st, ok := s.store.(legacyStore)
	if !ok {
		return FrozenRole{}, errors.New("旧连接存储不可用")
	}
	rows, err := st.ListCLAOImports(ctx)
	if err != nil {
		return FrozenRole{}, err
	}
	for _, r := range rows {
		if r.ID != chosen.ConnectionID || r.Kind != "connection" {
			continue
		}
		var c LegacyConnection
		if err = json.Unmarshal([]byte(r.Document), &c); err != nil || !c.Compatible || len(c.Profile) == 0 {
			return FrozenRole{}, errors.New("旧连接未兼容，请使用重新连接入口")
		}
		if r.AuthPending || chosen.ConnectionRevision != r.AuthRevision {
			return FrozenRole{}, errors.New("连接账号已变化或保存尚未确认，请重新选择并确认本次外发范围")
		}
		if err = bindLegacyAuth(&c, r); err != nil {
			return FrozenRole{}, err
		}
		if c.Billing != "standard_api" || c.Service != "bigmodel_general" && c.Service != "moonshot_cn" {
			return FrozenRole{}, errors.New("旧连接计费/服务不能映射为标准 API")
		}
		allowed := false
		for _, service := range consent {
			if service == c.Service {
				allowed = true
			}
		}
		if !allowed {
			return FrozenRole{}, fmt.Errorf("请确认本次 %s 将向 %s 发送任务和验收材料", role, c.Service)
		}
		core, ok := s.acceptance.(legacyCore)
		if !ok {
			return FrozenRole{}, errors.New("旧语义传输不可用")
		}
		result, e := core.Legacy(ctx, map[string]any{"action": "check", "profile": c.Profile})
		if e != nil {
			return FrozenRole{}, e
		}
		if !result.OK || !result.Configured {
			return FrozenRole{}, errors.New("该服务的系统凭据未配置或不可读取，请重新连接；未改用其他服务")
		}
		// The semantic HTTP consumer does not use an AgentHarness or native
		// Session. No fake native executor is synthesized for this selection.
		return FrozenRole{RoleChoice: RoleChoice{ConnectionID: c.ID, ConnectionRevision: c.AuthRevision, Model: c.Model}, Connection: &c}, nil
	}
	return FrozenRole{}, errors.New("所选旧连接不存在")
}

// The operation and structured response are committed together. A crash or
// lost local receipt cannot cause another paid HTTP call on Continue.
func (s *Service) semanticLegacy(id, role string, call RoleCall, prompt string) (string, error) {
	if call.Choice.Connection == nil {
		return "", errors.New("冻结旧连接缺失")
	}
	if call.Text != "" {
		return call.Text, nil
	}
	st, ok := s.store.(legacyStore)
	if !ok {
		return "", errors.New("冻结连接状态不可读取")
	}
	rows, e := st.ListCLAOImports(s.ctx)
	if e != nil {
		return "", e
	}
	matched := false
	for _, r := range rows {
		if r.ID == call.Choice.Connection.ID && r.Kind == "connection" {
			matched = !r.AuthPending && r.AuthRevision == call.Choice.Connection.AuthRevision
		}
	}
	if !matched {
		return "", errors.New("任务冻结的连接账号已变化或不可用；未改用新账号，请创建新尝试")
	}
	core, ok := s.acceptance.(legacyCore)
	if !ok {
		return "", errors.New("旧语义传输不可用")
	}
	opID := call.ID + ":http"
	_, err := s.mutate(id, func(m *Mission) error {
		if m.CancelRequested {
			return errCancelled
		}
		for _, op := range m.Operations {
			if op.ID == opID {
				return errors.New("该 API 调用已有执行事实；结果未确认时不重发")
			}
		}
		m.Operations = append(m.Operations, Operation{ID: opID, Kind: "semantic_http", Target: call.Choice.Connection.Service, State: "IN_FLIGHT"})
		for i := range m.RoleCalls {
			if m.RoleCalls[i].ID == call.ID {
				m.RoleCalls[i].State = "RUNNING"
			}
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	ctx, cancel := context.WithCancel(s.ctx)
	done := make(chan struct{})
	go func() {
		timer := time.NewTicker(50 * time.Millisecond)
		defer timer.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				return
			case <-timer.C:
				m, e := s.Get(s.ctx, id)
				if e != nil || m.CancelRequested {
					cancel()
					return
				}
			}
		}
	}()
	consumerRole := role
	if role == "planner" && strings.HasSuffix(call.ID, ":decompose") {
		consumerRole = "decomposition"
	}
	result, callErr := core.Legacy(ctx, map[string]any{"action": "semantic", "role": consumerRole, "profile": call.Choice.Connection.Profile, "prompt": prompt})
	close(done)
	cancel()
	_, saveErr := s.mutate(id, func(m *Mission) error {
		state, reason := "CONFIRMED_SUCCESS", ""
		roleState := "RECEIVED"
		if m.CancelRequested {
			state, roleState, reason = "UNKNOWN", "CANCELLED", "本地已停止等待；不能确认服务端计算或计费停止"
		} else if callErr != nil || !result.OK {
			state, roleState = "CONFIRMED_FAILURE", "FAILED"
			reason = result.Error
			if callErr != nil {
				reason = "外部调用未返回可确认结果"
			}
			if callErr != nil || result.Category == "NETWORK" || result.Category == "TIMEOUT" {
				state, roleState = "UNKNOWN", "UNKNOWN"
				m.State = "UNKNOWN"
				m.Reason = "外部语义调用结果未知；不重发，可取消并创建新尝试"
			}
		}
		for i := range m.Operations {
			if m.Operations[i].ID == opID {
				m.Operations[i].State = state
				m.Operations[i].Reason = reason
			}
		}
		for i := range m.RoleCalls {
			c := &m.RoleCalls[i]
			if c.ID != call.ID {
				continue
			}
			c.State = roleState
			c.Error = reason
			c.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)
			if state == "CONFIRMED_SUCCESS" {
				c.Text = result.Text
				c.ConfirmedModel = result.ConfirmedModel
				c.ModelFactSource = result.ModelFactSource
			}
			markConsumption(m, *c)
		}
		return nil
	})
	if saveErr != nil {
		return "", saveErr
	}
	m, err := s.Get(s.ctx, id)
	if err != nil {
		return "", err
	}
	if m.CancelRequested {
		return "", errCancelled
	}
	if callErr != nil {
		return "", callErr
	}
	if !result.OK {
		return "", errors.New(result.Error)
	}
	return result.Text, nil
}
