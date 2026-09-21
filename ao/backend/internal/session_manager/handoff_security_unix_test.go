//go:build !windows

package sessionmanager

import (
	"os"
	"path/filepath"
	"testing"
)

func assertPrivateHandoffPermissions(t *testing.T, path string) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("%s mode = %o, want 600", path, info.Mode().Perm())
	}
	if info, err := os.Stat(filepath.Dir(path)); err != nil || info.Mode().Perm() != 0o700 {
		t.Fatalf("handoff directory = (%v, %v), want mode 700", info, err)
	}
}
