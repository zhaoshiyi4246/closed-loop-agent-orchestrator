package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
)

type ConnectionModel struct {
	ID    string `json:"id"`
	Label string `json:"label"`
}
type ConnectionService struct {
	ID                  string            `json:"id"`
	Name                string            `json:"name"`
	Billing             string            `json:"billing"`
	Models              []ConnectionModel `json:"models"`
	SupportsCustomModel bool              `json:"supportsCustomModel"`
}
type ConnectionCatalog struct {
	Services []ConnectionService `json:"services"`
}
type ConnectionRequest struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Service string `json:"service"`
	Model   string `json:"model"`
}
type ConnectionResponse struct {
	Connection LegacyConnection `json:"connection"`
}

func (s *Service) ConnectionCatalog(ctx context.Context) (ConnectionCatalog, error) {
	core, ok := s.acceptance.(legacyCore)
	if !ok {
		return ConnectionCatalog{}, errors.New("标准 API 连接核心不可用")
	}
	r, err := core.Legacy(ctx, map[string]any{"action": "catalog"})
	if err != nil {
		return ConnectionCatalog{}, err
	}
	if !r.OK || len(r.Catalog.Services) == 0 {
		return ConnectionCatalog{}, errors.New("无法读取服务型号目录")
	}
	return r.Catalog, nil
}

// Insert-only identity makes an uncertain create response safe to reconcile.
// Credentials keep the same generation boundary as explicitly imported profiles.
func (s *Service) CreateConnection(ctx context.Context, in ConnectionRequest) (ConnectionResponse, error) {
	id := strings.ToLower(strings.ReplaceAll(in.ID, "-", ""))
	if !regexp.MustCompile(`^[a-f0-9]{32}$`).MatchString(id) {
		return ConnectionResponse{}, errors.New("新连接需要稳定的 UUID；请保留原请求重试")
	}
	id = "native-" + id
	core, ok := s.acceptance.(legacyCore)
	if !ok {
		return ConnectionResponse{}, errors.New("标准 API 连接核心不可用")
	}
	st, ok := s.store.(legacyStore)
	if !ok {
		return ConnectionResponse{}, errors.New("连接存储不可用")
	}
	r, err := core.Legacy(ctx, map[string]any{"action": "connection", "id": id, "name": in.Name, "service": in.Service, "model": in.Model})
	if err != nil {
		return ConnectionResponse{}, err
	}
	if !r.OK {
		return ConnectionResponse{}, errors.New(r.Error)
	}
	if len(r.Rows) != 1 || r.Rows[0].ID != id || r.Rows[0].Kind != "connection" {
		return ConnectionResponse{}, errors.New("连接配置未确认；未保存")
	}
	var c LegacyConnection
	if err = json.Unmarshal(r.Rows[0].Document, &c); err != nil || !c.Compatible || c.Billing != "standard_api" || c.Service != in.Service || c.Model != in.Model {
		return ConnectionResponse{}, errors.New("连接配置不一致；未保存")
	}
	var value any
	if err = json.Unmarshal(r.Rows[0].Document, &value); err != nil {
		return ConnectionResponse{}, err
	}
	doc, _ := json.Marshal(value)
	if err = st.ImportCLAORecords(ctx, []domain.CLAOImportRecord{{ID: id, Kind: "connection", Document: string(doc), CreatedAt: time.Now().UTC().Format(time.RFC3339Nano)}}); err != nil {
		return ConnectionResponse{}, err
	}
	catalog, err := s.LegacyCatalog(ctx)
	if err != nil {
		return ConnectionResponse{}, err
	}
	for _, saved := range catalog.Connections {
		if saved.ID == id {
			return ConnectionResponse{Connection: saved}, nil
		}
	}
	return ConnectionResponse{}, errors.New("连接保存结果待确认，请保留原请求重试")
}
