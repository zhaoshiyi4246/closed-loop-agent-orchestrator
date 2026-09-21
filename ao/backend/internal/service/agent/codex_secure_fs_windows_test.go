//go:build windows

package agent

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"golang.org/x/sys/windows"
)

func windowsCodexTestDirectory(t *testing.T) string {
	t.Helper()
	// The machine's shared TEMP may intentionally grant sandbox identities
	// mutation rights. Do not weaken those checks or edit the existing ACLs.
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	root, err := os.MkdirTemp(home, ".clao-security-test-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(root); err != nil {
			t.Error(err)
		}
	})
	if err := ensurePrivateDirectory(root); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestWindowsCodexBootstrapUsesPrivateUserDirectory(t *testing.T) {
	// Real handle/security/volume checks against a newly-created user temporary
	// directory. Only the provider is substituted; no existing credential is read.
	root := windowsCodexTestDirectory(t)
	factory := &fakeCodexAccountFactory{open: func(account ports.CodexAccountContext) (ports.CodexAccountClient, error) {
		return &fakeCodexAccountClient{read: ports.CodexAccountObservation{Authentication: domain.AgentAuthenticationUnauthorized}}, nil
	}}
	manager := newCodexAccountManager(context.Background(), filepath.Join(root, "accounts"), filepath.Join(root, "pending"), filepath.Join(root, "staging"), filepath.Join(root, "device"), factory, nil, nil)
	service := &Service{codexAccounts: manager}
	if err := service.WaitCodexAccountBootstrap(context.Background()); err != nil {
		t.Fatalf("empty private account preparation failed: %v", err)
	}
	private := filepath.Join(root, "accounts", "private-check")
	if err := ensurePrivateDirectory(private); err != nil {
		t.Fatal(err)
	}
	if err := validateCodexDirectory(private, true); err != nil {
		t.Fatal(err)
	}
	credential := filepath.Join(private, codexCredentialFilename)
	if err := writePrivateFileAtomic(credential, []byte("synthetic-private-test")); err != nil {
		t.Fatal(err)
	}
	got, err := readOpaqueCredential(credential)
	if err != nil || string(got) != "synthetic-private-test" {
		t.Fatalf("private round trip failed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "device", codexCredentialFilename)); !os.IsNotExist(err) {
		t.Fatal("empty device home was changed", err)
	}
}

func TestWindowsRootExceptionRequiresActualVolumeHandle(t *testing.T) {
	child := windowsCodexTestDirectory(t)
	root := filepath.VolumeName(child) + string(filepath.Separator)
	rootHandle, _, _, _, _, err := openCodexWindowsPath(root, true, false)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.CloseHandle(rootHandle)
	if !codexWindowsLocalVolumeRoot(root, rootHandle) {
		t.Fatal("system temporary directory is not on a verifiable local fixed volume")
	}
	childHandle, _, _, _, _, err := openCodexWindowsPath(child, true, false)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.CloseHandle(childHandle)
	if codexWindowsLocalVolumeRoot(root, childHandle) || codexWindowsLocalVolumeRoot(child, childHandle) ||
		codexWindowsLocalVolumeRoot(`\\server\share\`, rootHandle) {
		t.Fatal("non-root/remote/substituted handle received volume-root policy")
	}
	// The root-only policy is unavailable when no trusted child has been
	// verified. The standard system root itself must not become a vault.
	if err := validateCodexDirectory(root, true); err == nil {
		t.Fatal("system root was accepted as a private user vault")
	}
}

func TestWindowsOwnerRightsDACLProtectsOnlyItsCurrentOwner(t *testing.T) {
	root := windowsCodexTestDirectory(t)
	private := filepath.Join(root, "owner-rights")
	if err := os.Mkdir(private, 0o700); err != nil {
		t.Fatal(err)
	}
	// Match the owner-relative DACL used by Python's Windows mode-0700
	// directories. Only this newly created test directory is changed.
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	handle, _, ownerCurrent, _, _, err := openCodexWindowsPathWithAccess(private, true, windows.WRITE_DAC|windows.READ_CONTROL, false)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.CloseHandle(handle)
	if !ownerCurrent {
		t.Fatal("fixture directory is not owned by the test user")
	}
	if err := windows.SetSecurityInfo(handle, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil); err != nil {
		t.Fatal(err)
	}
	if err := validateCodexDirectory(private, true); err != nil {
		t.Fatal("safe OWNER RIGHTS DACL rejected", err)
	}
	// Children inherit the same owner-relative rule. Account preparation must
	// protect its new vault without treating the owner as a public principal.
	if err := ensurePrivateDirectory(filepath.Join(private, "vault")); err != nil {
		t.Fatal(err)
	}
}
