package kimiacp

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	acpdriver "github.com/aoagents/agent-orchestrator/backend/internal/adapters/chatdriver/acp"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

type fakePlugin struct {
	binary string
	status ports.AgentAuthStatus
}

func (p fakePlugin) ResolveBinary(context.Context) (string, error) { return p.binary, nil }
func (p fakePlugin) AuthStatus(context.Context) (ports.AgentAuthStatus, error) {
	return p.status, nil
}

func TestDriverReusesKimiPluginAndDeclaresNativeFeatures(t *testing.T) {
	driver := New(fakePlugin{binary: "/user/bin/kimi", status: ports.AgentAuthStatusAuthorized}, nil)
	if driver.Harness() != domain.HarnessKimi {
		t.Fatalf("harness = %q, want %q", driver.Harness(), domain.HarnessKimi)
	}
	caps, err := driver.Probe(context.Background())
	if err != nil {
		t.Fatalf("Probe: %v", err)
	}
	for _, capability := range []ports.ChatCapability{
		ports.ChatCapabilityStreaming,
		ports.ChatCapabilityTools,
		ports.ChatCapabilityApprovals,
		ports.ChatCapabilityInterrupt,
		ports.ChatCapabilityResume,
		ports.ChatCapabilityHistory,
		ports.ChatCapabilityPlans,
	} {
		if !caps.Has(capability) {
			t.Errorf("capability %q is false", capability)
		}
	}
}

func TestConfigureLaunchesNativeACPSubcommand(t *testing.T) {
	workspace := t.TempDir()
	dataDir := t.TempDir()
	t.Setenv("KIMI_CODE_HOME", t.TempDir())
	args, env, err := configure(context.Background(), acpdriver.LaunchConfig{
		WorkspacePath: workspace,
		DataDir:       dataDir,
		Model:         "kimi-code/kimi-for-coding", Permissions: ports.PermissionModeDefault,
		SystemPrompt: "AO worker instructions",
	})
	if err != nil {
		t.Fatalf("configure: %v", err)
	}
	if want := []string{"acp"}; !reflect.DeepEqual(args, want) {
		t.Fatalf("args = %#v, want %#v", args, want)
	}
	if len(env) != 1 || env["KIMI_CODE_HOME"] != filepath.Join(dataDir, "kimi") {
		t.Fatal("isolated Kimi environment not prepared")
	}
	instructions, err := os.ReadFile(filepath.Join(workspace, ".kimi", "AGENTS.md"))
	if err != nil {
		t.Fatalf("read Kimi ACP instructions: %v", err)
	}
	for _, want := range []string{
		"<!-- managed by agent-orchestrator: kimi system prompt -->",
		"AO worker instructions",
		"<!-- /managed by agent-orchestrator: kimi system prompt -->",
	} {
		if !strings.Contains(string(instructions), want) {
			t.Errorf("Kimi ACP instructions missing %q:\n%s", want, instructions)
		}
	}
	gitignore, err := os.ReadFile(filepath.Join(workspace, ".kimi", ".gitignore"))
	if err != nil {
		t.Fatalf("read Kimi ACP gitignore: %v", err)
	}
	if !strings.Contains(string(gitignore), "/AGENTS.md\n") {
		t.Fatalf("Kimi ACP instructions are not gitignored:\n%s", gitignore)
	}
}

func TestConfigureRejectsUnsupportedPermissionModes(t *testing.T) {
	for _, mode := range []ports.PermissionMode{
		ports.PermissionModeAcceptEdits,
		ports.PermissionModeAuto,
		ports.PermissionModeBypassPermissions,
	} {
		t.Run(string(mode), func(t *testing.T) {
			_, _, err := configure(context.Background(), acpdriver.LaunchConfig{
				WorkspacePath: t.TempDir(), Permissions: mode,
			})
			if !errors.Is(err, ports.ErrChatPermissionModeUnsupported) {
				t.Fatalf("configure permissions %q error = %v, want typed unsupported-mode error", mode, err)
			}
		})
	}
}

func TestConfigurePreparesExistingLoginAndLaunchOnlyAPIKey(t *testing.T) {
	for _, oauth := range []bool{true, false} {
		t.Run(map[bool]string{true: "oauth", false: "inline-api"}[oauth], func(t *testing.T) {
			source := t.TempDir()
			t.Setenv("KIMI_CODE_HOME", source)
			config := "default_model = 'selected'\n[providers.official]\ntype = 'kimi'\nbase_url = 'https://api.example.invalid/v1'\n"
			if oauth {
				config += "[providers.official.oauth]\nstorage = 'file'\nkey = 'oauth/kimi-code'\n"
				if err := os.Mkdir(filepath.Join(source, "credentials"), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(source, "credentials", "kimi-code.json"), []byte(`{"refresh_token":"synthetic-oauth"}`), 0o600); err != nil {
					t.Fatal(err)
				}
			} else {
				config += "api_key = 'synthetic-launch-only'\n"
			}
			if err := os.WriteFile(filepath.Join(source, "config.toml"), []byte(config), 0o600); err != nil {
				t.Fatal(err)
			}
			dataDir := t.TempDir()
			_, env, err := configure(context.Background(), acpdriver.LaunchConfig{WorkspacePath: t.TempDir(), DataDir: dataDir, Permissions: ports.PermissionModeDefault})
			if err != nil {
				t.Fatal(err)
			}
			if env["KIMI_CODE_HOME"] != filepath.Join(dataDir, "kimi") {
				t.Fatal("managed home not returned to ACP launcher")
			}
			managed, err := os.ReadFile(filepath.Join(env["KIMI_CODE_HOME"], "config.toml"))
			if err != nil {
				t.Fatal(err)
			}
			if oauth {
				if string(managed) != config {
					t.Fatal("official OAuth configuration changed")
				}
				credential, err := os.ReadFile(filepath.Join(env["KIMI_CODE_HOME"], "credentials", "kimi-code.json"))
				if err != nil || string(credential) != `{"refresh_token":"synthetic-oauth"}` {
					t.Fatal("OAuth credential not available to ACP")
				}
			} else {
				found := false
				for name, value := range env {
					if strings.HasPrefix(name, "CLAO_KIMI_PROVIDER_KEY_") && value == "synthetic-launch-only" {
						found = true
					}
				}
				if !found || strings.Contains(string(managed), "synthetic-launch-only") || !strings.Contains(string(managed), "api_key_env") {
					t.Fatal("API key launch-only contract violated")
				}
			}
			original, err := os.ReadFile(filepath.Join(source, "config.toml"))
			if err != nil || string(original) != config {
				t.Fatal("official source config changed")
			}
		})
	}
}

func TestSessionOptionsMapModelsButDoNotInventPermissionModes(t *testing.T) {
	tests := []struct {
		name     string
		settings ports.ChatTurnSettings
		want     []acpdriver.SessionOption
	}{
		{name: "empty"},
		{
			name:     "model",
			settings: ports.ChatTurnSettings{Model: "kimi-code/kimi-for-coding"},
			want:     []acpdriver.SessionOption{{ID: "model", Value: "kimi-code/kimi-for-coding"}},
		},
		{
			name:     "accept edits",
			settings: ports.ChatTurnSettings{Approval: ports.PermissionModeAcceptEdits},
		},
		{
			name:     "auto",
			settings: ports.ChatTurnSettings{Approval: ports.PermissionModeAuto},
		},
		{
			name:     "bypass",
			settings: ports.ChatTurnSettings{Approval: ports.PermissionModeBypassPermissions},
		},
		{
			name: "model and permission",
			settings: ports.ChatTurnSettings{
				Model: "kimi-code/kimi-for-coding", Approval: ports.PermissionModeBypassPermissions,
			},
			want: []acpdriver.SessionOption{
				{ID: "model", Value: "kimi-code/kimi-for-coding"},
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := sessionOptions(tc.settings); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("sessionOptions(%#v) = %#v, want %#v", tc.settings, got, tc.want)
			}
		})
	}
}

func TestLiveKimiACPReceivesLaunchSystemPrompt(t *testing.T) {
	if os.Getenv("AO_KIMI_ACP_INTEGRATION") != "1" {
		t.Skip("set AO_KIMI_ACP_INTEGRATION=1 to run the live Kimi ACP prompt-delivery contract")
	}
	bin, err := exec.LookPath("kimi")
	if err != nil {
		t.Fatalf("find kimi: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	driver := New(fakePlugin{binary: bin, status: ports.AgentAuthStatusAuthorized},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	conv, err := driver.Start(ctx, ports.ChatStartConfig{
		WorkspacePath: t.TempDir(),
		SystemPrompt: "When the user sends AO_KIMI_PROMPT_HANDSHAKE, reply with exactly " +
			"AO_KIMI_PROMPT_RECEIVED and no other text.",
	})
	if err != nil {
		t.Fatalf("start live Kimi ACP: %v", err)
	}
	defer conv.Close()

	for {
		select {
		case event := <-conv.Events():
			if event.Kind == ports.ChatEventControllerState && event.ControllerState == ports.ChatControllerReady {
				goto ready
			}
		case <-ctx.Done():
			t.Fatalf("wait for Kimi ready: %v", ctx.Err())
		}
	}

ready:
	ref, err := conv.SendTurn(ctx, ports.ChatUserMessage{Text: "AO_KIMI_PROMPT_HANDSHAKE"})
	if err != nil {
		t.Fatalf("send Kimi handshake: %v", err)
	}
	if err := conv.(ports.ChatDeferredTurnStarter).StartDeferredTurn(ref.ProviderTurnID); err != nil {
		t.Fatalf("start Kimi handshake: %v", err)
	}

	answer := ""
	for {
		select {
		case event := <-conv.Events():
			if event.Kind == ports.ChatEventMessageCompleted {
				answer = event.Text
			}
			if event.Kind == ports.ChatEventTurnCompleted {
				if strings.TrimSpace(answer) != "AO_KIMI_PROMPT_RECEIVED" {
					t.Fatalf("Kimi response = %q, want system-prompt handshake", answer)
				}
				return
			}
		case <-ctx.Done():
			t.Fatalf("wait for Kimi handshake: %v", ctx.Err())
		}
	}
}
