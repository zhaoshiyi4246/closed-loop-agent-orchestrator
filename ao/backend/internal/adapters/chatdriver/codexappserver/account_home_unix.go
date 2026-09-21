//go:build !windows

package codexappserver

import (
	"errors"
	"os"
)

func validateManagedAccountHome(path string) error {
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0o700 {
		return errors.New("managed Codex account home is unavailable")
	}
	return nil
}
