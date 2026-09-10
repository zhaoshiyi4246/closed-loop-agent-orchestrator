package ports

import (
	"reflect"
	"testing"
)

func TestMissingCapabilitiesForPermissions(t *testing.T) {
	caps := ChatCapabilities{
		ChatCapabilityStreaming: true,
		ChatCapabilityInterrupt: true,
		ChatCapabilityResume:    true,
	}

	if got := MissingCapabilitiesForPermissions(caps, PermissionModeDefault); !reflect.DeepEqual(
		got, []ChatCapability{ChatCapabilityApprovals},
	) {
		t.Fatalf("default missing = %v, want approvals", got)
	}
	if got := MissingCapabilitiesForPermissions(caps, PermissionModeBypassPermissions); len(got) != 0 {
		t.Fatalf("bypass missing = %v, want none", got)
	}

	delete(caps, ChatCapabilityInterrupt)
	if got := MissingCapabilitiesForPermissions(caps, PermissionModeBypassPermissions); !reflect.DeepEqual(
		got, []ChatCapability{ChatCapabilityInterrupt},
	) {
		t.Fatalf("bypass missing = %v, want interrupt", got)
	}
}

func TestCLAORequiresExplicitReadOnlyCapability(t *testing.T) {
	caps := ChatCapabilities{ChatCapabilityStreaming: true, ChatCapabilityInterrupt: true, ChatCapabilityResume: true, ChatCapabilityApprovals: true}
	if got := MissingCapabilitiesForPermissions(caps, PermissionModeReadOnly); !reflect.DeepEqual(got, []ChatCapability{ChatCapabilityReadOnly}) {
		t.Fatal(got)
	}
	caps[ChatCapabilityReadOnly] = true
	if got := MissingCapabilitiesForPermissions(caps, PermissionModeReadOnly); len(got) != 0 {
		t.Fatal(got)
	}
	if NormalizePermissionMode(PermissionModeReadOnly) != PermissionModeReadOnly {
		t.Fatal("read-only fell back to default")
	}
}
