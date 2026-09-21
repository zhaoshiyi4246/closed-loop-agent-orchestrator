//go:build windows

package kimi

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"unsafe"

	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"golang.org/x/sys/windows"
)

func kimiTestDACL(t *testing.T, path string) *windows.SECURITY_DESCRIPTOR {
	t.Helper()
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatal(err)
	}
	return sd
}

func TestWindowsManagedKimiTUIRetainsExistingPrivateDACL(t *testing.T) {
	t.Setenv(kimiCodeHomeEnv, t.TempDir())
	home := privateKimiHome(t)
	path := filepath.Join(home, "config.toml")
	if err := os.WriteFile(path, []byte("default_model = 'chosen'\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	token, err := windows.OpenCurrentProcessToken()
	if err != nil {
		t.Fatal(err)
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	sd, err := windows.SecurityDescriptorFromString("D:P(A;;FA;;;" + user.User.Sid.String() + ")")
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
	before := kimiTestDACL(t, path).String()
	err = (&Plugin{}).GetAgentHooks(context.Background(), ports.WorkspaceHookConfig{WorkspacePath: t.TempDir(), Env: map[string]string{kimiCodeHomeEnv: home}})
	if err != nil {
		t.Fatal(err)
	}
	if kimiTestDACL(t, path).String() != before {
		t.Fatal("existing private config ACL changed")
	}
	data, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(data), "default_model = 'chosen'") || !strings.Contains(string(data), "managed by agent-orchestrator") {
		t.Fatal("TUI configuration or managed hooks missing")
	}
}

func kimiTestEveryoneReadable(t *testing.T, path string) {
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
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;" + user.User.Sid.String() + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;WD)")
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

func kimiAssertPrivateDACL(t *testing.T, path string) {
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
	dacl, _, err := kimiTestDACL(t, path).DACL()
	if err != nil || dacl == nil || dacl.AceCount != 3 {
		t.Fatal("expected exactly private user/system/admin entries")
	}
	seen := map[string]bool{}
	for i := uint32(0); i < uint32(dacl.AceCount); i++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			t.Fatal(err)
		}
		if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE {
			t.Fatal("unexpected ACE")
		}
		seen[(*windows.SID)(unsafe.Pointer(&ace.SidStart)).String()] = true
	}
	if !seen[user.User.Sid.String()] || !seen["S-1-5-18"] || !seen["S-1-5-32-544"] {
		t.Fatal("unexpected credential principal")
	}
}

func TestWindowsManagedKimiPrivateOAuthUnderReadableParent(t *testing.T) {
	source := t.TempDir()
	t.Setenv(kimiCodeHomeEnv, source)
	writeKimiOAuthProfile(t, source, []byte(`{"refresh_token":"synthetic-oauth"}`))
	data := t.TempDir()
	kimiTestEveryoneReadable(t, data)
	before := kimiTestDACL(t, data).String()
	if _, err := PrepareACPHome(context.Background(), data, nil); err != nil {
		t.Fatal(err)
	}
	home := filepath.Join(data, "kimi")
	for _, rel := range []string{".", "config.toml", "credentials", "credentials/kimi-code.json"} {
		kimiAssertPrivateDACL(t, filepath.Join(home, rel))
	}
	if kimiTestDACL(t, data).String() != before {
		t.Fatal("existing parent ACL changed")
	}
	credential := filepath.Join(home, "credentials/kimi-code.json")
	kimiTestEveryoneReadable(t, credential)
	openedACL := kimiTestDACL(t, credential).String()
	if _, err := PrepareACPHome(context.Background(), data, nil); err == nil {
		t.Fatal("existing open credential accepted")
	}
	if kimiTestDACL(t, credential).String() != openedACL {
		t.Fatal("existing credential ACL repaired")
	}
	contents, _ := os.ReadFile(credential)
	if string(contents) != `{"refresh_token":"synthetic-oauth"}` {
		t.Fatal("existing credential bytes changed")
	}
}

func TestWindowsManagedKimiRejectsOpenExistingHome(t *testing.T) {
	t.Setenv(kimiCodeHomeEnv, t.TempDir())
	data := t.TempDir()
	home := filepath.Join(data, "kimi")
	if err := os.Mkdir(home, 0o700); err != nil {
		t.Fatal(err)
	}
	kimiTestEveryoneReadable(t, home)
	before := kimiTestDACL(t, home).String()
	if _, err := PrepareACPHome(context.Background(), data, nil); err == nil {
		t.Fatal("open home accepted")
	}
	if kimiTestDACL(t, home).String() != before {
		t.Fatal("existing home ACL changed")
	}
}

func TestWindowsManagedKimiRejectsJunctionsAndSourceAlias(t *testing.T) {
	for _, sourceLink := range []bool{false, true} {
		t.Run(map[bool]string{false: "target", true: "source"}[sourceLink], func(t *testing.T) {
			root := t.TempDir()
			outside := privateKimiHome(t)
			link := filepath.Join(root, "kimi")
			if out, err := exec.Command("cmd.exe", "/c", "mklink", "/J", link, outside).CombinedOutput(); err != nil {
				t.Fatalf("fixture junction: %v %s", err, out)
			}
			defer os.Remove(link)
			t.Setenv(kimiCodeHomeEnv, t.TempDir())
			data := root
			if sourceLink {
				t.Setenv(kimiCodeHomeEnv, link)
				data = t.TempDir()
				if err := os.WriteFile(filepath.Join(outside, "config.toml"), []byte(managedAPIConfig), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			before := kimiTestDACL(t, outside).String()
			if _, err := PrepareACPHome(context.Background(), data, nil); err == nil {
				t.Fatal("junction accepted")
			}
			if kimiTestDACL(t, outside).String() != before {
				t.Fatal("junction target ACL changed")
			}
		})
	}
	home := privateKimiHome(t)
	t.Setenv(kimiCodeHomeEnv, strings.ToUpper(home))
	if _, err := prepareManagedKimiHome(context.Background(), home, nil, false); err == nil {
		t.Fatal("case alias to official home accepted")
	}
	if entries, err := os.ReadDir(home); err != nil || len(entries) != 0 {
		t.Fatal("official home alias modified")
	}
}
