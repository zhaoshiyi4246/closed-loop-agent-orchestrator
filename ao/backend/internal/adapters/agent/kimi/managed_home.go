package kimi

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/aoagents/agent-orchestrator/backend/internal/privatefile"
	"github.com/pelletier/go-toml/v2"
)

var managedHomeMu sync.Mutex

const managedKeyPrefix = "CLAO_KIMI_PROVIDER_KEY_"

// PrepareACPHome seeds the official isolated home before ACP starts. Returned
// credentials are launch-only environment values, never persisted config.
func PrepareACPHome(ctx context.Context, dataDir string, env map[string]string) (map[string]string, error) {
	if strings.TrimSpace(dataDir) == "" {
		return nil, errors.New("kimi: managed data directory is required")
	}
	return prepareManagedKimiHome(ctx, kimiCodeHomeDir(dataDir), env, false)
}

func prepareManagedKimiHome(ctx context.Context, home string, env map[string]string, hooks bool) (map[string]string, error) {
	managedHomeMu.Lock()
	defer managedHomeMu.Unlock()
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if sourceHome, ok := kimiCodeHome(); ok && sameKimiConfigPath(sourceHome, home) {
		return nil, errors.New("kimi: managed home must differ from the user profile")
	}
	if err := kimiRealAncestors(filepath.Dir(home)); err != nil {
		return nil, err
	}
	if err := privatefile.EnsureDirectory(home); err != nil {
		return nil, fmt.Errorf("kimi: managed home must be private: %w", err)
	}
	path := filepath.Join(home, "config.toml")
	existing, err := readManagedKimiFile(path, true)
	if err != nil {
		return nil, err
	}
	var source []byte
	if sourceHome, ok := kimiCodeHome(); ok && !sameKimiConfigPath(sourceHome, home) {
		source, err = readManagedKimiFile(filepath.Join(sourceHome, "config.toml"), false)
		if err != nil {
			return nil, err
		}
	}
	data, bindings, err := kimiConfigProjection(existing, source, env)
	if err != nil {
		return nil, err
	}
	// Finish all configuration checks before copying any native OAuth tokens.
	if err := seedKimiCredentials(home, data); err != nil {
		return nil, err
	}
	if hooks {
		data = []byte(mergeKimiHooksConfig(string(data)))
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if string(data) != string(existing) {
		if err := writeManagedKimiFile(path, data, false); err != nil {
			return nil, err
		}
	}
	bindings[kimiCodeHomeEnv] = home
	return bindings, nil
}

func kimiRealAncestors(path string) error {
	path, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	for {
		if err := privatefile.ValidateDirectoryPath(path); err != nil {
			return errors.New("kimi: home ancestry is unavailable or linked")
		}
		parent := filepath.Dir(path)
		if parent == path {
			return nil
		}
		path = parent
	}
}

func readManagedKimiFile(path string, private bool) ([]byte, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil || !info.Mode().IsRegular() {
		return nil, errors.New("kimi: configuration or credential is not a regular file")
	}
	if err := kimiRealAncestors(filepath.Dir(path)); err != nil {
		return nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, errors.New("kimi: configuration or credential cannot be opened")
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return nil, errors.New("kimi: configuration or credential changed while opening")
	}
	if private {
		if err := privatefile.ValidateFile(f); err != nil {
			return nil, err
		}
	}
	data, err := io.ReadAll(io.LimitReader(f, 2*1024*1024+1))
	if err != nil || len(data) > 2*1024*1024 {
		return nil, errors.New("kimi: configuration or credential exceeds read bound")
	}
	return data, nil
}

func writeManagedKimiFile(path string, data []byte, firstOnly bool) error {
	if err := privatefile.ValidateDirectory(filepath.Dir(path)); err != nil {
		return err
	}
	existing, err := readManagedKimiFile(path, true)
	if err != nil {
		return err
	} else if existing != nil && firstOnly {
		return nil
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".clao-kimi-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if err := privatefile.ValidateFile(f); err != nil {
		return err
	}
	if existing != nil {
		if err := privatefile.CopyPermissions(path, f); err != nil {
			return err
		}
	}
	if _, err := f.Write(data); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if firstOnly {
		if err := os.Link(f.Name(), path); err != nil {
			if _, inspect := readManagedKimiFile(path, true); inspect != nil {
				return inspect
			}
			if _, stat := os.Lstat(path); stat == nil {
				return nil
			}
			return err
		}
		return nil
	}
	return os.Rename(f.Name(), path)
}

func parseKimiConfig(data []byte) (map[string]any, error) {
	config := map[string]any{}
	if err := toml.Unmarshal(data, &config); err != nil {
		return nil, errors.New("kimi: config TOML is invalid; content withheld")
	}
	return config, nil
}

func kimiConfigProjection(existing, source []byte, env map[string]string) ([]byte, map[string]string, error) {
	seed := kimiConfigCanSeed(existing)
	input := existing
	if seed && len(source) > 0 {
		input = source
	}
	config, err := parseKimiConfig(input)
	if err != nil {
		return nil, nil, err
	}
	bindings := map[string]string{}
	projected := false
	providers, _ := config["providers"].(map[string]any)
	for name, raw := range providers {
		provider, ok := raw.(map[string]any)
		if !ok {
			return nil, nil, errors.New("kimi: provider configuration is unsupported")
		}
		for _, field := range []string{"type", "base_url"} {
			if value := provider[field]; value != nil {
				if _, ok := value.(string); !ok {
					return nil, nil, errors.New("kimi: provider configuration is unsupported")
				}
			}
		}
		key, _ := provider["api_key"].(string)
		ref, _ := provider["api_key_env"].(string)
		providerEnv, _ := provider["env"].(map[string]any)
		fallback, _ := providerEnv["KIMI_API_KEY"].(string)
		if key != "" && fallback != "" {
			return nil, nil, errors.New("kimi: conflicting provider credentials")
		}
		if key == "" {
			key = fallback
		}
		if key != "" {
			if !seed || ref != "" || provider["oauth"] != nil {
				return nil, nil, errors.New("kimi: inline credential mapping is ambiguous; use official api_key_env")
			}
			sum := sha256.Sum256([]byte(name))
			ref = fmt.Sprintf("%s%x", managedKeyPrefix, sum[:12])
			provider["api_key_env"] = ref
			delete(provider, "api_key")
			delete(providerEnv, "KIMI_API_KEY")
			bindings[ref] = key
			projected = true
		}
		if ref != "" && bindings[ref] == "" {
			if strings.HasPrefix(ref, managedKeyPrefix) {
				// Re-resolve a prior projection only against the same named provider
				// and endpoint, never bind a rotated source to a different service.
				sourceConfig, err := parseKimiConfig(source)
				if err != nil {
					return nil, nil, err
				}
				sourceProviders, _ := sourceConfig["providers"].(map[string]any)
				original, _ := sourceProviders[name].(map[string]any)
				sum := sha256.Sum256([]byte(name))
				if original == nil || ref != fmt.Sprintf("%s%x", managedKeyPrefix, sum[:12]) || original["type"] != provider["type"] || original["base_url"] != provider["base_url"] || original["oauth"] != nil || original["api_key_env"] != nil {
					return nil, nil, errors.New("kimi: projected credential source changed; reconnect explicitly")
				}
				key, _ = original["api_key"].(string)
				if key == "" {
					originalEnv, _ := original["env"].(map[string]any)
					key, _ = originalEnv["KIMI_API_KEY"].(string)
				}
				if key == "" {
					return nil, nil, errors.New("kimi: projected credential is unavailable; use official api_key_env")
				}
				bindings[ref] = key
			} else if env[ref] == "" && os.Getenv(ref) == "" {
				return nil, nil, errors.New("kimi: configured api_key_env is unavailable")
			}
		}
	}
	if kimiLiteralCredential(config) {
		return nil, nil, errors.New("kimi: unsupported inline credential; use official provider api_key_env")
	}
	if !seed || !projected {
		return input, bindings, nil
	}
	data, err := toml.Marshal(config)
	if err != nil {
		return nil, nil, errors.New("kimi: configuration cannot be projected")
	}
	return data, bindings, nil
}

func kimiLiteralCredential(value any) bool {
	switch value := value.(type) {
	case map[string]any:
		for key, item := range value {
			name := strings.ReplaceAll(strings.ToUpper(key), "-", "_")
			// Custom authentication headers have no supported launch-env mapping.
			if (name == "CUSTOM_HEADERS" || name == "CUSTOMHEADERS") && item != nil {
				if headers, ok := item.(map[string]any); !ok || len(headers) > 0 {
					return true
				}
			}
			if text, ok := item.(string); ok && strings.TrimSpace(text) != "" && (name == "API_KEY" || name == "APIKEY" || name == "AUTHORIZATION" || name == "COOKIE" || strings.HasSuffix(name, "_API_KEY") || strings.HasSuffix(name, "_TOKEN")) {
				return true
			}
			if kimiLiteralCredential(item) {
				return true
			}
		}
	case []any:
		for _, item := range value {
			if kimiLiteralCredential(item) {
				return true
			}
		}
	}
	return false
}
