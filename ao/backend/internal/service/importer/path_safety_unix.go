//go:build !windows

package importer

import "path/filepath"

func unsafeImportReparsePath(string) bool { return false }

func resolveImportFilesystemPath(path string) (string, error) { return filepath.EvalSymlinks(path) }
