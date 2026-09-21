//go:build !windows

package sessionmanager

import (
	"errors"
	"fmt"
	"os"
)

func ensurePrivateHandoffDirectory(path string) error {
	err := os.Mkdir(path, 0o700)
	if err != nil && !errors.Is(err, os.ErrExist) {
		return fmt.Errorf("agent switch: create handoff directory %s: %w", path, err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("agent switch: inspect handoff directory %s: %w", path, err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("agent switch: handoff path %s is not a real directory", path)
	}
	if err := os.Chmod(path, 0o700); err != nil { //nolint:gosec // Owner traversal is required for this private directory.
		return fmt.Errorf("agent switch: secure handoff directory %s: %w", path, err)
	}
	return nil
}

func validatePrivateHandoffDirectory(string) error { return nil }
func validatePrivateHandoffFile(*os.File) error    { return nil }
