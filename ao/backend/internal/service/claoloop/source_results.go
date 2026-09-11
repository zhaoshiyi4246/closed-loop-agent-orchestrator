package claoloop

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/process"
)

type SourceExcluded struct {
	Path   string `json:"path"`
	Reason string `json:"reason"`
}
type SourcePreview struct {
	ProjectID    domain.ProjectID `json:"projectId"`
	OriginalPath string           `json:"originalPath"`
	Kind         string           `json:"kind"`
	Revision     string           `json:"revision"`
	Policy       string           `json:"policy"`
	FileCount    int              `json:"fileCount"`
	Bytes        int64            `json:"bytes"`
	Excluded     []SourceExcluded `json:"excluded"`
}
type SourceSnapshot struct {
	ProjectID    domain.ProjectID `json:"projectId"`
	OriginalPath string           `json:"originalPath"`
	ProjectPath  string           `json:"projectPath"`
	Revision     string           `json:"revision"`
	Base         string           `json:"base"`
	Policy       string           `json:"policy"`
	FileCount    int              `json:"fileCount"`
	Bytes        int64            `json:"bytes"`
	Excluded     []SourceExcluded `json:"excluded"`
}
type IntegrationResult struct {
	Identity   string `json:"identity"`
	Workspace  string `json:"workspace"`
	ResultHead string `json:"resultHead"`
}
type ResultPackage struct {
	Identity     string `json:"identity"`
	SHA256       string `json:"sha256"`
	Bytes        int64  `json:"bytes"`
	CreatedAt    string `json:"created_at"`
	BaseCommit   string `json:"base_commit"`
	ResultCommit string `json:"result_commit"`
	Accepted     bool   `json:"accepted"`
	Status       string `json:"status,omitempty"`
	Reason       string `json:"reason,omitempty"`
}
type ResultLocation struct {
	Status string `json:"status"`
	Path   string `json:"path"`
}
type ResultView struct {
	MissionID     string          `json:"missionId"`
	Status        string          `json:"status"`
	Reason        string          `json:"reason,omitempty"`
	Location      ResultLocation  `json:"location"`
	Evidence      json.RawMessage `json:"evidence"`
	Changes       json.RawMessage `json:"changes"`
	Exports       []ResultPackage `json:"exports"`
	BaseCommit    string          `json:"baseCommit,omitempty"`
	ResultCommit  string          `json:"resultCommit,omitempty"`
	Diff          string          `json:"diff,omitempty"`
	DiffTruncated bool            `json:"diffTruncated"`
	DiffBytes     int64           `json:"diffBytes"`
	DiffSHA256    string          `json:"diffSHA256,omitempty"`
	NoChanges     bool            `json:"noChanges"`
}
type materialOutput struct {
	OK            bool              `json:"ok"`
	ReadError     string            `json:"readError"`
	SourcePreview SourcePreview     `json:"sourcePreview"`
	Source        SourceSnapshot    `json:"source"`
	Integration   IntegrationResult `json:"integration"`
	Result        ResultView        `json:"result"`
	Package       ResultPackage     `json:"package"`
}

// The native bridge reuses the legacy pure content/patch rules. It does not
// construct a legacy Mission, attach a runtime, or open another database.
func (a PythonAcceptance) materials(ctx context.Context, request map[string]any) (materialOutput, error) {
	if a.Python == "" || a.CoreRoot == "" || a.DataDir == "" {
		return materialOutput{}, errors.New("CLAO 材料核心或独立数据目录未配置")
	}
	request["dataRoot"] = a.DataDir
	data, err := json.Marshal(request)
	if err != nil {
		return materialOutput{}, err
	}
	cmd := process.CommandContext(ctx, a.Python, "-m", "loopcore.ao_acceptance")
	cmd.Dir = a.CoreRoot
	cmd.Env = append(gateEnv(), "PYTHONPATH="+filepath.Join(a.CoreRoot, "src"))
	cmd.Stdin = bytes.NewReader(data)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		return materialOutput{}, fmt.Errorf("材料读取进程失败：%w", err)
	}
	var value materialOutput
	if err := json.Unmarshal(stdout.Bytes(), &value); err != nil {
		return value, fmt.Errorf("材料事实不可读取：%w", err)
	}
	if !value.OK {
		return value, errors.New(value.ReadError)
	}
	return value, nil
}
func (a PythonAcceptance) SourcePreview(ctx context.Context, projectID domain.ProjectID, path string) (SourcePreview, error) {
	r, err := a.materials(ctx, map[string]any{"materials": "source_preview", "projectId": projectID, "path": path})
	return r.SourcePreview, err
}
func (a PythonAcceptance) FreezeSource(ctx context.Context, projectID domain.ProjectID, path, missionID, revision string) (SourceSnapshot, error) {
	r, err := a.materials(ctx, map[string]any{"materials": "source_freeze", "projectId": projectID, "path": path, "missionId": missionID, "revision": revision})
	return r.Source, err
}
func (a PythonAcceptance) Integrate(ctx context.Context, m Mission, children []Mission) (IntegrationResult, error) {
	if m.Source == nil {
		return IntegrationResult{}, errors.New("集成缺少本次私有来源")
	}
	inputs := make([]map[string]string, 0, len(children))
	for _, child := range children {
		if child.Base != m.Base || child.ResultHead == "" {
			return IntegrationResult{}, errors.New("子任务固定成果与任务基线不一致")
		}
		inputs = append(inputs, map[string]string{"workspace": child.Workspace, "resultHead": child.ResultHead})
	}
	r, err := a.materials(ctx, map[string]any{"materials": "integrate", "missionId": m.Request.ID, "source": m.Source.ProjectPath, "base": m.Base, "children": inputs})
	return r.Integration, err
}

func resultFacts(m Mission) map[string]any {
	// Prompts, directives, configuration, credentials and role input are not
	// needed for a portable result and never enter this subprocess request.
	proofs := make([]map[string]any, 0, len(m.Evidence))
	for _, child := range m.Subtasks {
		for _, e := range child.Evidence {
			proofs = append(proofs, map[string]any{"records": e.Records})
		}
	}
	for _, e := range m.Evidence {
		proofs = append(proofs, map[string]any{"records": e.Records, "verification": e.Verification})
	}
	return map[string]any{"request": map[string]any{"id": m.Request.ID, "projectId": m.Request.ProjectID,
		"objective": m.Request.Objective, "criteria": m.Request.Criteria}, "state": m.State, "reason": m.Reason,
		"source": m.Source, "base": m.Base, "resultHead": m.ResultHead, "workspace": m.Workspace,
		"evidence": proofs, "exports": m.Exports, "coordinatorId": m.CoordinatorID}
}
func (a PythonAcceptance) Results(ctx context.Context, m Mission) (ResultView, error) {
	r, err := a.materials(ctx, map[string]any{"materials": "results", "mission": resultFacts(m)})
	return r.Result, err
}
func (a PythonAcceptance) ExportResult(ctx context.Context, m Mission) (ResultPackage, error) {
	r, err := a.materials(ctx, map[string]any{"materials": "export", "mission": resultFacts(m)})
	return r.Package, err
}

func (s *Service) PreviewSource(ctx context.Context, projectID domain.ProjectID) (SourcePreview, error) {
	p, found, err := s.store.GetProject(ctx, string(projectID))
	if err != nil {
		return SourcePreview{}, err
	}
	if !found || p.Path == "" || p.Kind.WithDefault() == domain.ProjectKindWorkspace {
		return SourcePreview{}, errors.New("请选择本机项目目录；多仓库项目不能作为同一来源")
	}
	core, ok := s.acceptance.(interface {
		SourcePreview(context.Context, domain.ProjectID, string) (SourcePreview, error)
	})
	if !ok {
		return SourcePreview{}, errors.New("来源确认不可用")
	}
	return core.SourcePreview(ctx, projectID, p.Path)
}
func (s *Service) Result(ctx context.Context, id string) (ResultView, error) {
	m, err := s.Get(ctx, id)
	if err != nil {
		return ResultView{}, err
	}
	core, ok := s.acceptance.(interface {
		Results(context.Context, Mission) (ResultView, error)
	})
	if !ok {
		return ResultView{}, errors.New("结果读取不可用")
	}
	return core.Results(ctx, m)
}
func (s *Service) Export(ctx context.Context, id string) (ResultPackage, error) {
	m, err := s.Get(ctx, id)
	if err != nil {
		return ResultPackage{}, err
	}
	if m.CoordinatorID != "" {
		return ResultPackage{}, errors.New("子任务成果尚不代表 Mission 最终验收，请从原任务导出统一成果")
	}
	if m.ResultHead == "" {
		return ResultPackage{}, errors.New("尚无已保存的固定成果；不会整理仍可能运行的 Worker")
	}
	core, ok := s.acceptance.(interface {
		ExportResult(context.Context, Mission) (ResultPackage, error)
	})
	if !ok {
		return ResultPackage{}, errors.New("结果导出不可用")
	}
	value, err := core.ExportResult(ctx, m)
	if err != nil {
		return value, err
	}
	_, err = s.mutate(id, func(current *Mission) error {
		if current.Base != m.Base || current.ResultHead != m.ResultHead || current.State != m.State {
			return errors.New("结果事实变化，请重新读取后导出")
		}
		for _, prior := range current.Exports {
			if prior.Identity == value.Identity {
				return nil
			}
		}
		current.Exports = append(current.Exports, value)
		return nil
	})
	return value, err
}

var packageID = regexp.MustCompile(`^[0-9a-f]{64}$`)

func checkedMaterialPath(root string, parts ...string) (string, error) {
	if !filepath.IsAbs(root) {
		return "", errors.New("独立材料目录未配置")
	}
	path := filepath.Join(append([]string{root}, parts...)...)
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", errors.New("材料路径不可用")
	}
	want, _ := filepath.Abs(path)
	if filepath.Clean(resolved) != filepath.Clean(want) {
		return "", errors.New("材料路径包含链接或 junction")
	}
	return path, nil
}
func (s *Service) Download(ctx context.Context, id, identity string) ([]byte, error) {
	if !safeID.MatchString(id) || !packageID.MatchString(identity) {
		return nil, errors.New("任务或结果包标识无效")
	}
	m, err := s.Get(ctx, id)
	if err != nil {
		return nil, err
	}
	var found *ResultPackage
	for i := range m.Exports {
		if m.Exports[i].Identity == identity {
			found = &m.Exports[i]
		}
	}
	if found == nil {
		return nil, errors.New("该任务没有此结果包")
	}
	a, ok := s.acceptance.(PythonAcceptance)
	if !ok {
		return nil, errors.New("独立结果存储不可用")
	}
	path, err := checkedMaterialPath(a.DataDir, "clao", "missions", id, "exports", identity+".zip")
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() != found.Bytes || found.Bytes > 300*1024*1024 {
		return nil, errors.New("已保存结果包缺失或大小不匹配")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errors.New("已保存结果包不可读取")
	}
	hash := sha256.Sum256(data)
	if hex.EncodeToString(hash[:]) != found.SHA256 {
		return nil, errors.New("已保存结果包校验失败")
	}
	return data, nil
}

func (s *Service) OpenResult(ctx context.Context, id string) (ResultLocation, error) {
	m, err := s.Get(ctx, id)
	if err != nil {
		return ResultLocation{}, err
	}
	if m.ResultHead == "" || !filepath.IsAbs(m.Workspace) {
		return ResultLocation{}, errors.New("尚无已保存的结果目录")
	}
	path, err := checkedMaterialPath(m.Workspace)
	if err != nil {
		return ResultLocation{}, err
	}
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return ResultLocation{}, errors.New("原结果目录已失效；仍可下载已保存的结果包")
	}
	if runtime.GOOS != "windows" {
		return ResultLocation{}, errors.New("此开发入口仅支持 Windows 打开目录；可以复制路径")
	}
	// A fixed native Mission path, never a browser-supplied command or path.
	cmd := exec.Command("explorer.exe", path)
	if err := cmd.Start(); err != nil {
		return ResultLocation{}, fmt.Errorf("打开结果目录失败：%w", err)
	}
	go func() { _ = cmd.Wait() }()
	return ResultLocation{Status: "opened", Path: path}, nil
}
