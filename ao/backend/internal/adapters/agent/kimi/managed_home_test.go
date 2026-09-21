package kimi

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	"github.com/aoagents/agent-orchestrator/backend/internal/privatefile"
)

func privateKimiHome(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "managed")
	if err := privatefile.EnsureDirectory(path); err != nil {
		t.Fatal(err)
	}
	return path
}

func assertKimiPrivateFile(t *testing.T, path string) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := privatefile.ValidateFile(f); err != nil {
		t.Fatal(err)
	}
	if err := privatefile.ValidateDirectory(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		info, err := f.Stat()
		if err != nil || info.Mode().Perm() != 0o600 {
			t.Fatal("credential mode is not 0600")
		}
	}
}

const managedAPIConfig = "default_model = 'chosen'\n[providers.example]\ntype = 'kimi'\nbase_url = 'https://api.example.invalid/v1'\napi_key = 'synthetic-inline-secret'\n[models.chosen]\nprovider = 'example'\nmodel = 'model-id'\nmax_context_size = 32000\n"

func TestPrepareACPHomeSeedsOfficialOAuthProfileWithoutChangingSource(t *testing.T) {
	source := t.TempDir()
	t.Setenv(kimiCodeHomeEnv, source)
	token := []byte(`{"access_token":"synthetic-access","refresh_token":"synthetic-refresh","expires_at":9999999999}`)
	writeKimiOAuthProfile(t, source, token)
	data := t.TempDir()
	env, err := PrepareACPHome(context.Background(), data, nil)
	if err != nil {
		t.Fatal(err)
	}
	home := filepath.Join(data, "kimi")
	if len(env) != 1 || env[kimiCodeHomeEnv] != home {
		t.Fatal("ACP home not bound")
	}
	for _, rel := range []string{"config.toml", "credentials/kimi-code.json"} {
		want, _ := os.ReadFile(filepath.Join(source, rel))
		got, err := os.ReadFile(filepath.Join(home, rel))
		if err != nil || string(got) != string(want) {
			t.Fatal("official configuration or credential content changed")
		}
		assertKimiPrivateFile(t, filepath.Join(home, rel))
	}
	if err := os.WriteFile(filepath.Join(source, "credentials/kimi-code.json"), []byte(`{"refresh_token":"new-source-token"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := PrepareACPHome(context.Background(), data, nil); err != nil {
		t.Fatal(err)
	}
	retained, _ := os.ReadFile(filepath.Join(home, "credentials/kimi-code.json"))
	if string(retained) != string(token) {
		t.Fatal("existing managed OAuth was overwritten")
	}
	unchanged, _ := os.ReadFile(filepath.Join(source, "config.toml"))
	if string(unchanged) != kimiOAuthUserConfig {
		t.Fatal("source configuration mutated")
	}
}

func TestManagedKimiInlineKeyIsLaunchOnlyAcrossACPAndTUI(t *testing.T) {
	for _, tui := range []bool{false, true} {
		t.Run(map[bool]string{false: "ACP", true: "TUI"}[tui], func(t *testing.T) {
			source := t.TempDir()
			t.Setenv(kimiCodeHomeEnv, source)
			if err := os.WriteFile(filepath.Join(source, "config.toml"), []byte(managedAPIConfig), 0o600); err != nil {
				t.Fatal(err)
			}
			data := t.TempDir()
			home := filepath.Join(data, "kimi")
			launch := func() map[string]string {
				if tui {
					env := map[string]string{kimiCodeHomeEnv: home}
					if err := (&Plugin{}).GetAgentHooks(context.Background(), ports.WorkspaceHookConfig{WorkspacePath: t.TempDir(), Env: env}); err != nil {
						t.Fatal(err)
					}
					return env
				}
				env, err := PrepareACPHome(context.Background(), data, nil)
				if err != nil {
					t.Fatal(err)
				}
				return env
			}
			env := launch()
			config, err := os.ReadFile(filepath.Join(home, "config.toml"))
			if err != nil {
				t.Fatal(err)
			}
			parsed, err := parseKimiConfig(config)
			if err != nil {
				t.Fatal(err)
			}
			providers := parsed["providers"].(map[string]any)
			provider := providers["example"].(map[string]any)
			ref, _ := provider["api_key_env"].(string)
			if !strings.HasPrefix(ref, managedKeyPrefix) || env[ref] != "synthetic-inline-secret" || provider["api_key"] != nil || parsed["default_model"] != "chosen" {
				t.Fatal("selected provider/model/launch binding not preserved")
			}
			if err := filepath.WalkDir(data, func(path string, entry os.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if !entry.IsDir() {
					contents, err := os.ReadFile(path)
					if err != nil {
						return err
					}
					if strings.Contains(string(contents), "synthetic-inline-secret") {
						t.Fatal("key persisted in managed data")
					}
				}
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			assertKimiPrivateFile(t, filepath.Join(home, "config.toml"))
			if second := launch(); second[ref] != env[ref] {
				t.Fatal("subsequent launch lost in-memory key binding")
			}
			again, _ := os.ReadFile(filepath.Join(home, "config.toml"))
			if string(again) != string(config) {
				t.Fatal("existing configuration not preserved")
			}
			original, _ := os.ReadFile(filepath.Join(source, "config.toml"))
			if string(original) != managedAPIConfig {
				t.Fatal("source changed")
			}
			if err := os.WriteFile(filepath.Join(source, "config.toml"), []byte(strings.ReplaceAll(managedAPIConfig, "api.example.invalid", "other.example.invalid")), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := PrepareACPHome(context.Background(), data, nil); err == nil {
				t.Fatal("changed endpoint adopted old credential reference")
			}
		})
	}
}

func TestManagedKimiRejectsAmbiguousInlineCredentialsWithoutPersisting(t *testing.T) {
	for _, config := range []string{"api_key = 'synthetic-inline-secret'\n", strings.Replace(managedAPIConfig, "api_key =", "api_key_env = 'OTHER'\napi_key =", 1), managedAPIConfig + "[providers.example.oauth]\nkey='oauth/kimi-code'\n"} {
		source := t.TempDir()
		t.Setenv(kimiCodeHomeEnv, source)
		if err := os.WriteFile(filepath.Join(source, "config.toml"), []byte(config), 0o600); err != nil {
			t.Fatal(err)
		}
		data := t.TempDir()
		if _, err := PrepareACPHome(context.Background(), data, nil); err == nil || strings.Contains(err.Error(), "synthetic-inline-secret") {
			t.Fatal("ambiguous credentials accepted or leaked")
		}
		if _, err := os.Stat(filepath.Join(data, "kimi/config.toml")); !os.IsNotExist(err) {
			t.Fatal("rejected config was persisted")
		}
	}
}

func TestManagedKimiReusesOfficialAPIKeyEnvWithoutCopyingValue(t *testing.T) {
	source := t.TempDir()
	t.Setenv(kimiCodeHomeEnv, source)
	config := strings.Replace(managedAPIConfig, "api_key = 'synthetic-inline-secret'", "api_key_env = 'KIMI_TEST_SELECTED_KEY'", 1)
	if err := os.WriteFile(filepath.Join(source, "config.toml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	data := t.TempDir()
	if _, err := PrepareACPHome(context.Background(), data, nil); err == nil {
		t.Fatal("missing env reference accepted")
	}
	env, err := PrepareACPHome(context.Background(), data, map[string]string{"KIMI_TEST_SELECTED_KEY": "synthetic-env-key"})
	if err != nil {
		t.Fatal(err)
	}
	if len(env) != 1 {
		t.Fatal("existing launch reference was copied unnecessarily")
	}
	saved, _ := os.ReadFile(filepath.Join(data, "kimi/config.toml"))
	if string(saved) != config {
		t.Fatal("official environment-reference config changed")
	}
}

func TestManagedKimiRejectsUnmappedCredentialHeaders(t *testing.T) {
	for _, header := range []string{"Authorization", "X-API-Key", "X-Token"} {
		config := managedAPIConfig + "[providers.example.custom_headers]\n" + header + " = 'synthetic-header-secret'\n"
		if _, _, err := kimiConfigProjection(nil, []byte(config), nil); err == nil || strings.Contains(err.Error(), "synthetic-header-secret") {
			t.Fatal("unmapped credential header accepted or leaked")
		}
	}
}

func TestManagedKimiRejectsExistingInlineWithoutChangingBytes(t *testing.T) {
	t.Setenv(kimiCodeHomeEnv, t.TempDir())
	home := privateKimiHome(t)
	path := filepath.Join(home, "config.toml")
	if err := os.WriteFile(path, []byte(managedAPIConfig), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareManagedKimiHome(context.Background(), home, nil, false); err == nil {
		t.Fatal("existing inline configuration silently rewritten")
	}
	data, _ := os.ReadFile(path)
	if string(data) != managedAPIConfig {
		t.Fatal("existing configuration modified")
	}
}
