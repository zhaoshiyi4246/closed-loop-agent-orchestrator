//go:build windows

package codexappserver

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/codexsecurity"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"golang.org/x/sys/windows"
)

func managedAccountTestHome(t *testing.T) string {
	t.Helper()
	userHome, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	home, err := os.MkdirTemp(userHome, ".clao-managed-test-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(home); err != nil {
			t.Error(err)
		}
	})
	if err := codexsecurity.ProtectPrivateDirectory(home); err != nil {
		t.Fatal(err)
	}
	if err := codexsecurity.ValidateDirectory(home, true); err != nil {
		t.Fatal(err)
	}
	return home
}

func TestWindowsManagedAccountFactoryRejectsUnsafeHomesBeforeResolution(t *testing.T) {
	root := managedAccountTestHome(t)
	weak := filepath.Join(root, "public-readable")
	if err := os.Mkdir(weak, 0700); err != nil {
		t.Fatal(err)
	}
	// Mutate only the new fixture: everybody can read, but cannot write it.
	// Private account homes must reject even this read-only disclosure.
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GR;;;WD)")
	if err != nil {
		t.Fatal(err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		t.Fatal(err)
	}
	handle, _, _, _, _, err := codexsecurity.OpenWindowsPathWithAccess(weak, true, windows.WRITE_DAC|windows.READ_CONTROL, false)
	if err != nil {
		t.Fatal(err)
	}
	err = windows.SetSecurityInfo(handle, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, dacl, nil)
	windows.CloseHandle(handle)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root, "target")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(target, "child"), 0700); err != nil {
		t.Fatal(err)
	}
	junction := filepath.Join(root, "junction")
	// Directory junctions exercise a real reparse point without requiring
	// symbolic-link privilege. The target is another empty owned fixture.
	if output, err := exec.Command("cmd.exe", "/d", "/c", "mklink", "/J", junction, target).CombinedOutput(); err != nil {
		t.Fatalf("create fixture junction: %v %s", err, output)
	}
	t.Cleanup(func() {
		if err := os.Remove(junction); err != nil {
			t.Error(err)
		}
	})
	for _, home := range []string{weak, junction, filepath.Join(junction, "child"), filepath.Join(root, "missing")} {
		t.Run(filepath.Base(home), func(t *testing.T) {
			factory := NewAccountFactoryWithResolver(func(context.Context) (string, error) {
				t.Fatal("unsafe home reached binary resolution")
				return "", nil
			}, nil)
			if client, err := factory.Open(context.Background(), ports.CodexAccountContext{Home: home, Managed: true}); err == nil {
				client.Close()
				t.Fatal("unsafe managed home accepted")
			}
		})
	}
}
