package claoloop

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
)

// PythonAcceptance runs only the retained pure acceptance/Git core. It has no
// API server, scheduler, model credentials or separate StateStore database.
type PythonAcceptance struct {
	Python   string
	CoreRoot string
}

func gateEnv() []string {
	out := []string{"GIT_OPTIONAL_LOCKS=0", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8"}
	for _, key := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PATHEXT"} {
		if value, ok := os.LookupEnv(key); ok {
			out = append(out, key+"="+value)
		}
	}
	return out
}
func (a PythonAcceptance) Source(ctx context.Context, root string) (string, error) {
	if !filepath.IsAbs(root) {
		return "", errors.New("source path must be absolute")
	}
	probe := func(args ...string) (string, error) {
		cmd := exec.CommandContext(ctx, "git", append([]string{"--no-optional-locks", "-C", root}, args...)...)
		cmd.Env = gateEnv()
		b, err := cmd.Output()
		if err != nil {
			return "", fmt.Errorf("Git source evidence unavailable: %w", err)
		}
		return string(b), nil
	}
	status, err := probe("status", "--porcelain=v1", "-z", "--untracked-files=all")
	if err != nil {
		return "", err
	}
	if status != "" {
		return "", errors.New("项目或复核目录有未提交修改；本轮闭环不静默忽略这些内容")
	}
	head, err := probe("rev-parse", "--verify", "HEAD^{commit}")
	return strings.TrimSpace(head), err
}
func (a PythonAcceptance) Check(ctx context.Context, m Mission, materialize bool, digest, verification string) (Evidence, error) {
	if a.Python == "" || a.CoreRoot == "" {
		return Evidence{}, errors.New("CLAO Python acceptance core is not configured")
	}
	spec := map[string]any{"task_id": m.Request.ID, "project_id": m.Request.ProjectID, "objective": m.Request.Objective, "allowed_paths": m.Request.AllowedPaths, "forbidden_paths": m.Request.ForbiddenPaths, "acceptance_criteria": m.Request.Criteria, "gate_commands": m.Request.GateCommands}
	request := map[string]any{"workspace": m.Workspace, "base": m.Base, "task": spec, "timeout": m.Request.GateTimeout, "outputLimit": 20000, "materialize": materialize, "expectedDigest": digest, "verificationText": verification, "expectedHead": m.ResultHead}
	return a.run(ctx, request)
}

func (a PythonAcceptance) Approval(ctx context.Context, m Mission, activity domain.ConversationActivity) error {
	var detail json.RawMessage = activity.Detail
	request := map[string]any{"workspace": m.Workspace, "base": m.Base,
		"task": map[string]any{"task_id": m.Request.ID, "project_id": m.Request.ProjectID, "objective": m.Request.Objective,
			"allowed_paths": m.Request.AllowedPaths, "forbidden_paths": m.Request.ForbiddenPaths,
			"acceptance_criteria": m.Request.Criteria, "gate_commands": m.Request.GateCommands},
		"approval": map[string]any{"activityKind": "approval", "status": string(activity.Status), "requestId": activity.RequestID, "detail": detail}}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := a.run(ctx, request)
	if err != nil {
		return err
	}
	if !out.OK {
		return fmt.Errorf("闭环范围不允许该审批：%s", out.ReadError)
	}
	return nil
}

func (a PythonAcceptance) run(ctx context.Context, request map[string]any) (Evidence, error) {
	data, err := json.Marshal(request)
	if err != nil {
		return Evidence{}, err
	}
	cmd := exec.CommandContext(ctx, a.Python, "-m", "loopcore.ao_acceptance")
	cmd.Env = append(gateEnv(), "PYTHONPATH="+filepath.Join(a.CoreRoot, "src"))
	cmd.Dir = a.CoreRoot
	cmd.Stdin = bytes.NewReader(data)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err = cmd.Run(); err != nil {
		return Evidence{}, fmt.Errorf("acceptance process failed: %w", err)
	}
	var out Evidence
	if err = json.Unmarshal(stdout.Bytes(), &out); err != nil {
		return out, fmt.Errorf("acceptance result unreadable: %w", err)
	}
	return out, nil
}
