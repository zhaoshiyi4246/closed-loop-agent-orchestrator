//go:build windows

package importer

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestWindowsImportRejectsStateJunctionBeforeGitMutation(t *testing.T) {
	base := t.TempDir()
	state := filepath.Join(base, "runtime-state")
	if err := os.MkdirAll(filepath.Join(state, "child"), 0700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(state, "synthetic-state-marker.txt")
	const content = "non-secret state fixture"
	if err := os.WriteFile(marker, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(base, "state-alias")
	// A real directory junction needs no symbolic-link privilege. The target
	// and link are both owned test fixtures, never existing application state.
	if output, err := exec.Command("cmd.exe", "/d", "/c", "mklink", "/J", alias, state).CombinedOutput(); err != nil {
		t.Fatalf("create fixture junction: %v %s", err, output)
	}
	t.Cleanup(func() {
		if err := os.Remove(alias); err != nil {
			t.Error(err)
		}
	})
	svc := New(Deps{Store: newFakeStore(), StateDir: state})
	ctx := context.Background()
	for _, tc := range []struct {
		name     string
		path     string
		stateDir string
	}{
		{name: "direct junction", path: alias, stateDir: state},
		{name: "junction ancestor", path: filepath.Join(alias, "child"), stateDir: state},
		{name: "state configured through junction", path: state, stateDir: alias},
		{name: "state child configured through junction", path: filepath.Join(state, "child"), stateDir: alias},
	} {
		t.Run(tc.name, func(t *testing.T) {
			svc := New(Deps{Store: newFakeStore(), StateDir: tc.stateDir})
			validation, err := svc.Validate(ctx, ImportValidationInput{ImportKind: ImportKindProject, Path: tc.path})
			if err != nil || validation.IsValid || validation.NextStep != ImportNextStepError {
				t.Fatalf("unsafe validation = %#v, %v", validation, err)
			}
			wantActions(t, validation.BlockingErrors, []string{"IMPORT_PATH_UNSAFE"})
			prepared, err := svc.PrepareGit(ctx, GitPreparationInput{
				ImportKind: ImportKindProject, Path: tc.path,
				ApprovedActions: []string{GitPreparationActionInit, GitPreparationActionCommit, GitPreparationActionSetRemote},
				RemoteURL:       "https://example.invalid/synthetic.git",
			})
			if err != nil || prepared.Validation.IsValid || len(prepared.Events) != 0 {
				t.Fatalf("unsafe preparation = %#v, %v", prepared, err)
			}
			for _, target := range []string{state, filepath.Join(state, "child")} {
				if _, err := os.Stat(filepath.Join(target, ".git")); !errors.Is(err, os.ErrNotExist) {
					t.Fatalf("state Git metadata was created: %v", err)
				}
			}
			if got, err := os.ReadFile(marker); err != nil || string(got) != content {
				t.Fatalf("state marker was modified: %v", err)
			}
		})
	}
	ordinary := filepath.Join(base, "runtime-state-project")
	if err := os.Mkdir(ordinary, 0755); err != nil {
		t.Fatal(err)
	}
	validation, err := svc.Validate(ctx, ImportValidationInput{ImportKind: ImportKindProject, Path: ordinary})
	if err != nil || !validation.IsValid {
		t.Fatalf("ordinary prefix sibling rejected: %#v, %v", validation, err)
	}
}
