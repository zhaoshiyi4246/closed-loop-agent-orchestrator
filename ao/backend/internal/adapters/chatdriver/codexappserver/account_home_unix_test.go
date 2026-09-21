//go:build !windows

package codexappserver

import (
	"os"
	"testing"
)

func managedAccountTestHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	if err := os.Chmod(home, 0700); err != nil {
		t.Fatal(err)
	}
	return home
}
