package systemexec

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
)

func TestProbeHonorsCanceledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := (Adapter{}).Probe(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("Probe error = %v, want context canceled", err)
	}
}

func TestRunInstallClosesStdinAndSetsControlledEnvironment(t *testing.T) {
	t.Parallel()
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	err = (Adapter{}).RunInstall(context.Background(), ports.InstallCommand{
		Argv: []string{executable, "-test.run=^TestInstallEnvironmentHelper$"},
		Env:  []string{"CI=1", "NONINTERACTIVE=1", "AO_TEST_INSTALL_HELPER=1"},
	}, &output, &output)
	if err != nil {
		t.Fatalf("RunInstall: %v", err)
	}
	got := output.String()
	if !strings.Contains(got, "stdin:eof") || !strings.Contains(got, "ci:1 noninteractive:1") {
		t.Fatalf("output = %q, want closed stdin and controlled env", got)
	}
}

func TestInstallEnvironmentHelper(t *testing.T) {
	if os.Getenv("AO_TEST_INSTALL_HELPER") != "1" {
		return
	}
	data, err := io.ReadAll(os.Stdin)
	if err != nil || len(data) != 0 {
		os.Exit(2)
	}
	fmt.Printf("stdin:eof\nci:%s noninteractive:%s", os.Getenv("CI"), os.Getenv("NONINTERACTIVE"))
	os.Exit(0)
}

func TestPathWritableUsesEffectiveFilesystemPermissions(t *testing.T) {
	t.Parallel()
	writable := t.TempDir()
	got, err := pathWritable(context.Background(), writable)
	if err != nil {
		t.Fatal(err)
	}
	if !got {
		t.Fatalf("PathWritable(%q) = false, want true", writable)
	}
	got, err = pathWritable(context.Background(), writable+"/missing/child")
	if err != nil {
		t.Fatal(err)
	}
	if !got {
		t.Fatalf("PathWritable should accept a missing destination below a writable ancestor")
	}
}
