package kimiacp

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	acpdriver "github.com/aoagents/agent-orchestrator/backend/internal/adapters/chatdriver/acp"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

// This opt-in integration runs the installed official CLI with all network
// APIs blocked and a fixed fake SSE stream. It never uses a provider credential.
func TestOfficialKimiOfflineFragmentedPermissionThroughCLAO(t *testing.T) {
	node, cli, python := os.Getenv("CLAO_TEST_NODE"), os.Getenv("CLAO_TEST_KIMI_MAIN"), os.Getenv("CLAO_TEST_PYTHON")
	if node == "" || cli == "" || python == "" {
		t.Skip("set explicit Node, official CLI and project Python for offline protocol integration")
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Clean(filepath.Join(cwd, "../../../../../.."))
	for _, scenario := range []struct{ tool, target string }{{"Write", "solution.py"}, {"Edit", "solution.py"}, {"Edit", "check.py"}} {
		t.Run(scenario.tool+"-"+scenario.target, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
			defer cancel()
			folder := filepath.Join(t.TempDir(), "fixture")
			cmd := exec.CommandContext(ctx, node, filepath.Join(root, "dev/native/prepare-kimi-offline-fixture.cjs"), folder, scenario.tool, scenario.target)
			output, err := cmd.Output()
			if err != nil {
				t.Fatal(err)
			}
			var fixture struct {
				Workspace, PreloadURL, CountPath string
				Env                              map[string]string
			}
			if err := json.Unmarshal(output, &fixture); err != nil {
				t.Fatal(err)
			}
			env := map[string]string{}
			// Empty inherited names before processenv.Merge, then provide only the
			// launch essentials and this entirely synthetic profile.
			for _, entry := range os.Environ() {
				key, _, _ := strings.Cut(entry, "=")
				env[key] = ""
			}
			for _, key := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"} {
				env[key] = os.Getenv(key)
			}
			for key, value := range fixture.Env {
				env[key] = value
			}
			const marker = "offline-fake-key-not-a-credential"
			env["KIMI_MODEL_API_KEY"] = marker
			env["KIMI_API_KEY"] = marker
			driver := acpdriver.New(acpdriver.Config{Harness: domain.HarnessKimi, Capabilities: ports.ChatCapabilities{ports.ChatCapabilityApprovals: true, ports.ChatCapabilityTools: true}, PermissionInputDecoder: kimiPermissionInputDecoder,
				Launch: func(context.Context, acpdriver.LaunchConfig) (acpdriver.Launch, error) {
					return acpdriver.Launch{Command: node, Args: []string{"--import", fixture.PreloadURL, cli, "acp"}, Env: env}, nil
				}}, nil)
			conversation, err := driver.Start(ctx, ports.ChatStartConfig{SessionID: "offline", WorkspacePath: fixture.Workspace, Permissions: ports.PermissionModeDefault})
			if err != nil {
				t.Fatal(err)
			}
			defer conversation.Close()
			turn, err := conversation.SendTurn(ctx, ports.ChatUserMessage{Text: "Use " + scenario.tool + " to correct addition in " + scenario.target + "."})
			if err != nil {
				t.Fatal(err)
			}
			if err := conversation.(ports.ChatDeferredTurnStarter).StartDeferredTurn(turn.ProviderTurnID); err != nil {
				t.Fatal(err)
			}
			approvals := 0
			completed := false
			for !completed {
				select {
				case <-ctx.Done():
					t.Fatal("offline protocol did not complete")
				case event, open := <-conversation.Events():
					if !open {
						t.Fatal("conversation closed before completion")
					}
					if event.Kind == ports.ChatEventTurnCompleted {
						completed = true
						continue
					}
					if event.Kind != ports.ChatEventApprovalRequested {
						continue
					}
					approvals++
					var detail map[string]any
					if err := json.Unmarshal(event.Detail, &detail); err != nil {
						t.Fatal(err)
					}
					input, ok := detail["input"].(map[string]any)
					if !ok || input["path"] != scenario.target {
						t.Fatal("original arguments missing before permission resolution")
					}
					options := []any{}
					allowID, rejectID := "", ""
					for _, option := range event.Decisions {
						options = append(options, map[string]any{"id": option.ID, "kind": option.Kind})
						if option.Kind == "allow_once" {
							allowID = option.ID
						}
						if option.Kind == "reject_once" {
							rejectID = option.ID
						}
					}
					detail["decisions"] = options
					payload, _ := json.Marshal(map[string]any{"workspace": fixture.Workspace, "base": strings.Repeat("a", 40), "task": map[string]any{"task_id": "synthetic", "project_id": "synthetic", "objective": "fix addition", "allowed_paths": []string{"solution.py"}, "forbidden_paths": []string{"check.py"}, "acceptance_criteria": []any{map[string]any{"id": "AC1", "description": "addition"}}, "gate_commands": []string{"python check.py"}}, "approval": map[string]any{"activityKind": "approval", "status": "pending", "requestId": event.RequestID, "detail": detail}})
					accept := exec.CommandContext(ctx, python, "-B", "-m", "loopcore.ao_acceptance")
					for key, value := range env {
						if value != "" && key != "KIMI_MODEL_API_KEY" && key != "KIMI_API_KEY" {
							accept.Env = append(accept.Env, key+"="+value)
						}
					}
					accept.Env = append(accept.Env, "PYTHONPATH="+filepath.Join(root, "clao/src"), "PYTHONUTF8=1")
					accept.Stdin = bytes.NewReader(payload)
					result, err := accept.CombinedOutput()
					if err != nil {
						t.Fatalf("acceptance: %v %s", err, result)
					}
					var acceptance struct {
						OK         bool   `json:"ok"`
						DecisionID string `json:"decision_id"`
					}
					if json.Unmarshal(result, &acceptance) != nil || acceptance.OK != (scenario.target == "solution.py") {
						t.Fatalf("wrong scope decision: %s", result)
					}
					decision := rejectID
					if acceptance.OK {
						decision = allowID
					}
					if decision == "" {
						t.Fatal("required once-only decision not offered")
					}
					if err := conversation.ResolveRequest(ctx, event.RequestID, ports.ChatDecision{ID: decision}); err != nil {
						t.Fatal(err)
					}
				}
			}
			if approvals != 1 {
				t.Fatalf("approvals=%d", approvals)
			}
			if err := conversation.Close(); err != nil {
				t.Fatal(err)
			}
			for _, name := range []string{"solution.py", "check.py"} {
				data, err := os.ReadFile(filepath.Join(fixture.Workspace, name))
				want := "def add(a, b):\n    return a - b\n"
				if name == "solution.py" && scenario.target == name {
					want = "def add(a, b):\n    return a + b\n"
				}
				if err != nil || string(data) != want {
					t.Fatal("file mutation violated approved scope")
				}
			}
			count, err := os.ReadFile(fixture.CountPath)
			var calls struct{ Calls int }
			if err != nil || json.Unmarshal(count, &calls) != nil || calls.Calls != 2 {
				t.Fatal("unexpected offline call count")
			}
			if err := filepath.WalkDir(folder, func(path string, entry os.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if !entry.IsDir() {
					data, err := os.ReadFile(path)
					if err != nil {
						return err
					}
					if bytes.Contains(data, []byte(marker)) {
						t.Fatal("fake credential persisted")
					}
				}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
		})
	}
}
