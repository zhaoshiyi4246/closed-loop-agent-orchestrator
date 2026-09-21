//go:build windows

package agent

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/adapters/chatdriver/codexappserver"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"github.com/aoagents/agent-orchestrator/backend/internal/service/shellterm"
)

// The real factory launches this test executable as a bounded synthetic Codex
// app-server. No installed CLI, network, or existing credential is accessed.
func TestMain(m *testing.M) {
	if os.Getenv("CLAO_MANAGED_FACTORY_TEST_PROCESS") == "1" && len(os.Args) > 1 && os.Args[len(os.Args)-1] == "app-server" {
		if !pathWithin(os.Getenv("CLAO_MANAGED_FACTORY_TEST_ROOT"), os.Getenv("CODEX_HOME")) {
			os.Exit(3)
		}
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			var request struct {
				ID     json.RawMessage `json:"id"`
				Method string          `json:"method"`
			}
			if json.Unmarshal(scanner.Bytes(), &request) != nil {
				os.Exit(4)
			}
			if len(request.ID) == 0 {
				continue
			}
			var result any
			switch request.Method {
			case "initialize":
				result = map[string]any{}
			case "account/read":
				result = map[string]any{"account": map[string]any{"type": "chatgpt", "email": "managed@example.com", "planType": "pro"}, "requiresOpenaiAuth": true}
			default:
				os.Exit(5)
			}
			response, _ := json.Marshal(map[string]any{"id": request.ID, "result": result})
			fmt.Println(string(response))
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestWindowsManagedLoginUsesRealFactoryAndPrivateCredentialHome(t *testing.T) {
	root := windowsCodexTestDirectory(t)
	t.Setenv("CLAO_MANAGED_FACTORY_TEST_PROCESS", "1")
	t.Setenv("CLAO_MANAGED_FACTORY_TEST_ROOT", root)
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	factory := codexappserver.NewAccountFactoryWithResolver(func(context.Context) (string, error) { return executable, nil }, nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	manager := newCodexAccountManager(ctx, filepath.Join(root, "accounts"), filepath.Join(root, "pending"), filepath.Join(root, "staging"), filepath.Join(root, "device"), factory, nil, nil)
	manager.newID = func() string { return "b60a377d-da68-4a61-86f2-f31f04c571f2" }
	manager.catalog.newID = func() string { return testAccountID }
	manager.executable = func() (string, error) { return executable, nil }
	terminal := &fakeCodexLoginTerminal{writeCredential: true, result: shellterm.ShellTerminal{HandleID: "synthetic-login", Title: "Add Codex account"}}
	manager.terminal = terminal
	started, err := manager.openLoginTerminal(ctx, "")
	if err != nil {
		t.Fatal(err)
	}
	pendingHome := terminal.opened[0].Env["CODEX_HOME"]
	if err := validateCodexDirectory(pendingHome, true); err != nil {
		t.Fatal(err)
	}
	completed, err := manager.verifyLogin(ctx, started.Operation.OperationID)
	if err != nil {
		t.Fatal(err)
	}
	if completed.Status != domain.CodexAccountLoginCompleted || completed.Account == nil || completed.Account.ID != testAccountID || completed.Account.Label != "managed@example.com" {
		t.Fatalf("login result = %#v", completed)
	}
	home := filepath.Join(manager.catalog.root, testAccountID, codexCredentialHomeDirectory)
	credential, err := readOpaqueCredential(filepath.Join(home, codexCredentialFilename))
	if err != nil || string(credential) != "opaque-login-credential" {
		t.Fatalf("private credential not committed: %v", err)
	}
	// The catalog path also uses Managed=true for later account reads.
	client, err := factory.Open(ctx, ports.CodexAccountContext{Home: home, Managed: true})
	if err != nil {
		t.Fatal(err)
	}
	observation, err := client.Read(ctx, false)
	_ = client.Close()
	if err != nil || observation.Authentication != domain.AgentAuthenticationAuthorized {
		t.Fatalf("saved managed home read failed: %v", err)
	}
	if _, err := os.Stat(pendingHome); !os.IsNotExist(err) {
		t.Fatalf("pending credential home remains: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "device", codexCredentialFilename)); !os.IsNotExist(err) {
		t.Fatal("isolated unmanaged device credential was changed")
	}
}
