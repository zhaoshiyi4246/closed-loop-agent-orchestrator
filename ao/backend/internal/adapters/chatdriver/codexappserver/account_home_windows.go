//go:build windows

package codexappserver

import "github.com/aoagents/agent-orchestrator/backend/internal/codexsecurity"

// Windows file modes do not express ACL privacy. Recheck the actual directory
// handle and every ancestor even when the catalog already prepared this home.
func validateManagedAccountHome(path string) error {
	return codexsecurity.ValidateDirectory(path, true)
}
