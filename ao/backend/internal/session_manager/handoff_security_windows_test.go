//go:build windows

package sessionmanager

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"unsafe"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"golang.org/x/sys/windows"
)

func handoffTestDescriptor(t *testing.T, path string) *windows.SECURITY_DESCRIPTOR {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatal(err)
	}
	return sd
}

func assertPrivateHandoffPermissions(t *testing.T, path string) {
	t.Helper()
	token, err := windows.OpenCurrentProcessToken()
	if err != nil {
		t.Fatal(err)
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	for _, object := range []string{path, filepath.Dir(path)} {
		sd := handoffTestDescriptor(t, object)
		owner, _, err := sd.Owner()
		if err != nil || owner == nil || !owner.Equals(user.User.Sid) {
			t.Fatalf("unexpected handoff owner: %v", err)
		}
		acl, _, err := sd.DACL()
		if err != nil || acl == nil || acl.AceCount != 3 {
			t.Fatalf("want exactly three private ACEs: %v", err)
		}
		seen := map[string]bool{}
		for i := uint32(0); i < uint32(acl.AceCount); i++ {
			var ace *windows.ACCESS_ALLOWED_ACE
			if err := windows.GetAce(acl, i, &ace); err != nil {
				t.Fatal(err)
			}
			const fileAllAccess = 0x1f01ff // Win32 FILE_ALL_ACCESS, including WRITE_DAC/WRITE_OWNER.
			if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE || uint32(ace.Mask)&fileAllAccess != fileAllAccess {
				t.Fatal("expected full-control allow entry")
			}
			seen[(*windows.SID)(unsafe.Pointer(&ace.SidStart)).String()] = true
		}
		if !seen[user.User.Sid.String()] || !seen["S-1-5-18"] || !seen["S-1-5-32-544"] {
			t.Fatal("handoff grants an unexpected principal")
		}
		if object == filepath.Dir(path) {
			control, _, err := sd.Control()
			if err != nil || control&windows.SE_DACL_PROTECTED == 0 {
				t.Fatal("handoff directory inherits external permissions")
			}
		}
	}
}

// This changes only a fresh test-owned object, never a profile or app directory.
func allowEveryoneReadHandoffFixture(t *testing.T, path string, inheritance string) {
	t.Helper()
	token, err := windows.OpenCurrentProcessToken()
	if err != nil {
		t.Fatal(err)
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;" + user.User.Sid.String() + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;" + inheritance + ";FR;;;WD)")
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil); err != nil {
		t.Fatal(err)
	}
}

func TestWindowsHandoffPrivateUnderReadableParent(t *testing.T) {
	root := t.TempDir()
	allowEveryoneReadHandoffFixture(t, root, "OICI")
	before := handoffTestDescriptor(t, root).String()
	// Reproduce the old mode-only behavior on an empty synthetic sibling.
	legacy := filepath.Join(root, "legacy-mode-only")
	if err := os.Mkdir(legacy, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(legacy, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := validatePrivateHandoffDirectory(legacy); err == nil {
		t.Fatal("mode 0700 unexpectedly removed inherited Everyone read access")
	}
	m := &Manager{dataDir: root}
	candidate, _, err := m.prepareAgentHandoffPaths(context.Background(), "demo-1", "switch-1")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(candidate, []byte(`{"synthetic":"context"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	assertPrivateHandoffPermissions(t, candidate)
	written, err := m.writeAgentHandoffFile(context.Background(), "demo-1", "switch-1", json.RawMessage(`{"synthetic":"context"}`))
	if err != nil {
		t.Fatal(err)
	}
	assertPrivateHandoffPermissions(t, written.Path)
	finalized, err := m.writeFinalizedHandoffFile(context.Background(), domain.AgentSwitch{ID: "switch-1", SessionID: "demo-1"}, "synthetic final continuation")
	if err != nil {
		t.Fatal(err)
	}
	assertPrivateHandoffPermissions(t, finalized.Path)
	if got := handoffTestDescriptor(t, root).String(); got != before {
		t.Fatal("existing data directory ACL changed")
	}
}

func TestWindowsHandoffRejectsExistingOpenDirectoryWithoutRepermission(t *testing.T) {
	for _, inheritance := range []string{"OICI", "OICIIO"} {
		t.Run(inheritance, func(t *testing.T) {
			root := t.TempDir()
			handoffs := filepath.Join(root, "handoffs")
			if err := os.Mkdir(handoffs, 0o700); err != nil {
				t.Fatal(err)
			}
			allowEveryoneReadHandoffFixture(t, handoffs, inheritance)
			before := handoffTestDescriptor(t, handoffs).String()
			m := &Manager{dataDir: root}
			if _, _, err := m.prepareAgentHandoffPaths(context.Background(), "demo-1", "switch-1"); err == nil {
				t.Fatal("open existing directory accepted")
			}
			if got := handoffTestDescriptor(t, handoffs).String(); got != before {
				t.Fatal("existing directory ACL was repaired")
			}
			if _, err := os.Stat(filepath.Join(handoffs, "demo-1")); !os.IsNotExist(err) {
				t.Fatalf("created child in unsafe directory: %v", err)
			}
		})
	}
}

func TestWindowsHandoffRejectsFileACLChangedAfterPublication(t *testing.T) {
	m := &Manager{dataDir: t.TempDir()}
	body := json.RawMessage(`{"synthetic":"context"}`)
	written, err := m.writeAgentHandoffFile(context.Background(), "demo-1", "switch-1", body)
	if err != nil {
		t.Fatal(err)
	}
	allowEveryoneReadHandoffFixture(t, written.Path, "")
	before := handoffTestDescriptor(t, written.Path).String()
	if _, err := m.writeAgentHandoffFile(context.Background(), "demo-1", "switch-1", body); err == nil {
		t.Fatal("idempotent write accepted publicly readable file")
	}
	sw := domain.AgentSwitch{ID: "switch-1", SessionID: "demo-1", AgentHandoffPath: written.Path, AgentHandoffHash: written.Hash, AgentHandoffStatus: domain.AgentHandoffReceived}
	if _, ok := m.readVerifiedAgentHandoffForDelivery(context.Background(), sw); ok {
		t.Fatal("delivery accepted publicly readable file")
	}
	if got := handoffTestDescriptor(t, written.Path).String(); got != before {
		t.Fatal("existing file ACL was repaired")
	}
	data, err := os.ReadFile(written.Path)
	if err != nil || string(data) != string(body)+"\n" {
		t.Fatal("rejected file contents changed")
	}
}

func TestWindowsHandoffRejectsJunctionDirectory(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "outside-handoffs")
	if err := ensurePrivateHandoffDirectory(target); err != nil {
		t.Fatal(err)
	}
	data := filepath.Join(root, "data")
	if err := os.Mkdir(data, 0o700); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(data, "handoffs")
	// Junction creation needs no symbolic-link privilege. All paths are fresh
	// fixture children, and no target contents or permissions are modified.
	if out, err := exec.Command("cmd.exe", "/c", "mklink", "/J", link, target).CombinedOutput(); err != nil {
		t.Fatalf("create fixture junction: %v: %s", err, out)
	}
	defer func() { _ = os.Remove(link) }()
	m := &Manager{dataDir: data}
	if _, _, err := m.prepareAgentHandoffPaths(context.Background(), "demo-1", "switch-1"); err == nil {
		t.Fatal("junction accepted as a handoff directory")
	}
	if entries, err := os.ReadDir(target); err != nil || len(entries) != 0 {
		t.Fatalf("junction target changed: %v %v", entries, err)
	}
}
