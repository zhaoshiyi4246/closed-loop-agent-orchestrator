//go:build windows

package agent

import (
	"github.com/aoagents/agent-orchestrator/backend/internal/codexsecurity"
	"os"
)

func codexPrivateFileMode(os.FileInfo) bool { return true }
func openCodexFileNoFollow(path string) (*os.File, error) {
	return codexsecurity.OpenFileNoFollow(path)
}
func validateCodexDirectory(path string, private bool) error {
	return codexsecurity.ValidateDirectory(path, private)
}
func validateCodexDirectoryAncestors(path string) error {
	return codexsecurity.ValidateDirectoryAncestors(path)
}
func protectCodexPrivateDirectory(path string) error {
	return codexsecurity.ProtectPrivateDirectory(path)
}
func protectCodexPrivateFile(path string, file *os.File) error {
	return codexsecurity.ProtectPrivateFile(path, file)
}
func syncDirectory(path string) error { return codexsecurity.SyncDirectory(path) }
