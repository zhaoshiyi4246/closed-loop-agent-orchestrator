//go:build windows

package sessionmanager

import (
	"github.com/aoagents/agent-orchestrator/backend/internal/privatefile"
	"os"
)

func ensurePrivateHandoffDirectory(path string) error   { return privatefile.EnsureDirectory(path) }
func validatePrivateHandoffDirectory(path string) error { return privatefile.ValidateDirectory(path) }
func validatePrivateHandoffFile(file *os.File) error    { return privatefile.ValidateFile(file) }
