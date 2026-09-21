package kimi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/aoagents/agent-orchestrator/backend/internal/adapters/agent/hookutil"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"github.com/aoagents/agent-orchestrator/backend/internal/privatefile"
	"github.com/pelletier/go-toml/v2"
)

const (
	kimiInstructionsDirName  = ".kimi"
	kimiInstructionsFileName = "AGENTS.md"
	kimiInstructionsSentinel = "<!-- managed by agent-orchestrator: kimi system prompt -->"
	kimiInstructionsEnd      = "<!-- /managed by agent-orchestrator: kimi system prompt -->"

	kimiHooksSentinelStart = "# managed by agent-orchestrator: kimi hooks"
	kimiHooksSentinelEnd   = "# /managed by agent-orchestrator: kimi hooks"
)

// GetAgentHooks installs AO's standing system prompt through Kimi's
// project-level instruction file. Kimi has no system-prompt argv flag, and its
// user-level config lives outside AO's data dir, so a gitignored worktree-local
// instruction file is the least invasive session-scoped injection point. It
// also installs Kimi lifecycle hooks into the AO-managed Kimi config so AO can
// capture Kimi's native session id for true resume without mutating the user's
// global Kimi profile.
func (p *Plugin) GetAgentHooks(ctx context.Context, cfg ports.WorkspaceHookConfig) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if strings.TrimSpace(cfg.WorkspacePath) == "" {
		return errors.New("kimi.GetAgentHooks: WorkspacePath is required")
	}

	if err := installKimiConfigHooks(ctx, cfg); err != nil {
		return fmt.Errorf("kimi.GetAgentHooks: %w", err)
	}

	systemPrompt, err := kimiSystemPromptText(cfg.SystemPrompt, cfg.SystemPromptFile)
	if err != nil {
		return fmt.Errorf("kimi.GetAgentHooks: %w", err)
	}
	if err := PrepareACPInstructions(ctx, cfg.WorkspacePath, systemPrompt); err != nil {
		return fmt.Errorf("kimi.GetAgentHooks: %w", err)
	}
	return nil
}

// PrepareACPInstructions installs AO's standing instructions where Kimi Code
// discovers project-level AGENTS.md files. Chat sessions call this immediately
// before launching `kimi acp`; unlike TUI sessions, they do not run
// GetAgentHooks during workspace preparation.
func PrepareACPInstructions(ctx context.Context, workspacePath, systemPrompt string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if strings.TrimSpace(systemPrompt) == "" {
		return nil
	}
	if strings.TrimSpace(workspacePath) == "" {
		return errors.New("kimi: workspace path is required for ACP instructions")
	}
	instructionsPath := kimiInstructionsPath(workspacePath)
	var existing []byte
	existing, err := os.ReadFile(instructionsPath) //nolint:gosec // path built from caller-owned workspace dir
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("kimi: read ACP instructions %s: %w", instructionsPath, err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}

	if err := os.MkdirAll(filepath.Dir(instructionsPath), 0o750); err != nil {
		return fmt.Errorf("kimi: create ACP instruction dir: %w", err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	body := mergeKimiInstructionFile(string(existing), systemPrompt)
	if err := hookutil.AtomicWriteFile(instructionsPath, []byte(body), 0o600); err != nil {
		return fmt.Errorf("kimi: write ACP instructions %s: %w", instructionsPath, err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := hookutil.EnsureWorkspaceGitignore(filepath.Dir(instructionsPath), kimiInstructionsFileName); err != nil {
		return fmt.Errorf("kimi: gitignore ACP instructions: %w", err)
	}
	return ctx.Err()
}

func kimiInstructionsPath(workspacePath string) string {
	return filepath.Join(workspacePath, kimiInstructionsDirName, kimiInstructionsFileName)
}

func installKimiConfigHooks(ctx context.Context, cfg ports.WorkspaceHookConfig) error {
	home, ok := kimiCodeHomeFromEnv(cfg.Env)
	if !ok {
		return errors.New("kimi: AO-managed Kimi Code home is unavailable")
	}
	bindings, err := prepareManagedKimiHome(ctx, home, cfg.Env, true)
	if err != nil {
		return err
	}
	for key, value := range bindings {
		cfg.Env[key] = value
	}
	return nil
}

func seedKimiCredentials(targetHome string, selectedConfig []byte) error {
	sourceHome, ok := kimiCodeHome()
	if !ok {
		return nil
	}
	var config kimiAuthConfig
	if err := toml.Unmarshal(selectedConfig, &config); err != nil {
		return errors.New("kimi: source config is invalid; content withheld")
	}
	var sourcePaths []string
	for _, provider := range config.Providers {
		if provider.OAuth == nil {
			continue
		}
		if provider.OAuth.Storage != "" && provider.OAuth.Storage != "file" {
			return errors.New("kimi: unsupported OAuth storage")
		}
		name := strings.TrimPrefix(provider.OAuth.Key, "oauth/")
		if name == "" || name != filepath.Base(name) || strings.ContainsAny(name, `/\\`) || strings.HasPrefix(name, ".") {
			return errors.New("kimi: unsupported OAuth credential name")
		}
		sourcePaths = append(sourcePaths, filepath.Join(sourceHome, "credentials", name+".json"))
	}
	if len(config.Providers) == 0 {
		// Preserve the legacy credential-only seed path for profiles created by
		// Kimi versions that did not persist an OAuth reference in config.toml.
		sourcePaths = []string{filepath.Join(sourceHome, "credentials", "kimi-code.json")}
	}
	for _, sourcePath := range sourcePaths {
		targetPath := filepath.Join(targetHome, "credentials", filepath.Base(sourcePath))
		if err := seedKimiCredential(sourcePath, targetPath); err != nil {
			return err
		}
	}
	return nil
}

func seedKimiCredential(sourcePath, targetPath string) error {
	if sameKimiConfigPath(sourcePath, targetPath) {
		return nil
	}
	if _, err := os.Lstat(filepath.Dir(targetPath)); err == nil {
		if err := privatefile.ValidateDirectory(filepath.Dir(targetPath)); err != nil {
			return err
		}
	}
	if existing, err := readManagedKimiFile(targetPath, true); err != nil {
		return err
	} else if existing != nil {
		return nil
	}
	data, err := readManagedKimiFile(sourcePath, false)
	if err != nil {
		return err
	}
	if data == nil {
		return nil
	}
	var credential struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.Unmarshal(data, &credential); err != nil {
		return errors.New("kimi: source OAuth credential is invalid; content withheld")
	}
	if strings.TrimSpace(credential.AccessToken) == "" && strings.TrimSpace(credential.RefreshToken) == "" {
		return nil
	}
	if err := privatefile.EnsureDirectory(filepath.Dir(targetPath)); err != nil {
		return err
	}
	return writeManagedKimiFile(targetPath, data, true)
}

func kimiCodeHomeFromEnv(env map[string]string) (string, bool) {
	if env != nil {
		if home := strings.TrimSpace(env[kimiCodeHomeEnv]); home != "" {
			return home, true
		}
	}
	return "", false
}

func kimiConfigCanSeed(existing []byte) bool {
	text := strings.TrimSpace(string(existing))
	if text == "" {
		return true
	}
	return strings.TrimSpace(removeKimiManagedHooks(text)) == ""
}

func removeKimiManagedHooks(existing string) string {
	start := strings.Index(existing, kimiHooksSentinelStart)
	if start < 0 {
		return existing
	}
	afterStart := existing[start+len(kimiHooksSentinelStart):]
	endRel := strings.Index(afterStart, kimiHooksSentinelEnd)
	if endRel < 0 {
		return strings.TrimRight(existing[:start], "\n")
	}
	end := start + len(kimiHooksSentinelStart) + endRel + len(kimiHooksSentinelEnd)
	return existing[:start] + existing[end:]
}

func sameKimiConfigPath(a, b string) bool {
	absA, errA := filepath.Abs(a)
	absB, errB := filepath.Abs(b)
	if errA == nil && errB == nil {
		if absA == absB || (runtime.GOOS == "windows" && strings.EqualFold(absA, absB)) {
			return true
		}
		infoA, errA := os.Stat(absA)
		infoB, errB := os.Stat(absB)
		return errA == nil && errB == nil && os.SameFile(infoA, infoB)
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

func mergeKimiHooksConfig(existing string) string {
	block := kimiHooksConfigBlock()
	start := strings.Index(existing, kimiHooksSentinelStart)
	if start < 0 {
		return joinKimiConfigParts(existing, block, "")
	}
	afterStart := existing[start+len(kimiHooksSentinelStart):]
	endRel := strings.Index(afterStart, kimiHooksSentinelEnd)
	if endRel < 0 {
		return joinKimiConfigParts(existing[:start], block, "")
	}
	end := start + len(kimiHooksSentinelStart) + endRel + len(kimiHooksSentinelEnd)
	return joinKimiConfigParts(existing[:start], block, existing[end:])
}

func kimiHooksConfigBlock() string {
	return kimiHooksSentinelStart + "\n\n" +
		kimiHookEntry("SessionStart", "startup", "ao hooks kimi session-start") +
		kimiHookEntry("UserPromptSubmit", "", "ao hooks kimi user-prompt-submit") +
		kimiHookEntry("PermissionRequest", "", "ao hooks kimi permission-request") +
		kimiHookEntry("Stop", "", "ao hooks kimi stop") +
		kimiHooksSentinelEnd + "\n"
}

func kimiHookEntry(event, matcher, command string) string {
	var b strings.Builder
	b.WriteString("[[hooks]]\n")
	b.WriteString("event = ")
	b.WriteString(quoteTOMLString(event))
	b.WriteByte('\n')
	if matcher != "" {
		b.WriteString("matcher = ")
		b.WriteString(quoteTOMLString(matcher))
		b.WriteByte('\n')
	}
	b.WriteString("command = ")
	b.WriteString(quoteTOMLString(command))
	b.WriteByte('\n')
	b.WriteString("timeout = 5\n\n")
	return b.String()
}

func quoteTOMLString(s string) string {
	return fmt.Sprintf("%q", s)
}

func joinKimiConfigParts(prefix, block, suffix string) string {
	var b strings.Builder
	prefix = strings.TrimRight(prefix, "\n")
	if prefix != "" {
		b.WriteString(prefix)
		b.WriteString("\n\n")
	}
	b.WriteString(block)
	suffix = strings.TrimLeft(suffix, "\n")
	if suffix != "" {
		b.WriteString("\n")
		b.WriteString(suffix)
	}
	return b.String()
}

func kimiSystemPromptText(inline, file string) (string, error) {
	if strings.TrimSpace(inline) != "" {
		return strings.TrimRight(inline, "\n"), nil
	}
	if strings.TrimSpace(file) == "" {
		return "", nil
	}
	data, err := os.ReadFile(file) //nolint:gosec // path is AO-owned launch config
	if err != nil {
		return "", fmt.Errorf("read system prompt file: %w", err)
	}
	return strings.TrimRight(string(data), "\n"), nil
}

func kimiInstructionFile(systemPrompt string) string {
	return kimiInstructionsSentinel + "\n\n" +
		"# Agent Orchestrator Session Instructions\n\n" +
		strings.TrimRight(systemPrompt, "\n") + "\n\n" +
		kimiInstructionsEnd + "\n"
}

func mergeKimiInstructionFile(existing, systemPrompt string) string {
	block := kimiInstructionFile(systemPrompt)
	start := strings.Index(existing, kimiInstructionsSentinel)
	if start < 0 {
		return joinKimiInstructionParts(existing, block, "")
	}

	afterStart := existing[start+len(kimiInstructionsSentinel):]
	endRel := strings.Index(afterStart, kimiInstructionsEnd)
	if endRel < 0 {
		// Older AO-managed files did not have an end marker. Treat the marker as
		// owning the rest of the file so stale AO instructions are replaced.
		return joinKimiInstructionParts(existing[:start], block, "")
	}

	end := start + len(kimiInstructionsSentinel) + endRel + len(kimiInstructionsEnd)
	return joinKimiInstructionParts(existing[:start], block, existing[end:])
}

func joinKimiInstructionParts(prefix, block, suffix string) string {
	var b strings.Builder
	prefix = strings.TrimRight(prefix, "\n")
	if prefix != "" {
		b.WriteString(prefix)
		b.WriteString("\n\n")
	}
	b.WriteString(block)
	suffix = strings.TrimLeft(suffix, "\n")
	if suffix != "" {
		b.WriteString("\n")
		b.WriteString(suffix)
	}
	return b.String()
}
