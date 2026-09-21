package claoloop

import (
	"strings"
	"testing"
)

func TestRecoveryRejectsConfirmedRoleFailureBeforeSourceShortcuts(t *testing.T) {
	for _, stage := range []string{"source", "decompose", "children", "verify", "final"} {
		for _, state := range []string{"FAILED", "PROTOCOL_ERROR"} {
			t.Run(stage+"/"+state, func(t *testing.T) {
				m := Mission{State: "PAUSED", Source: &SourceSnapshot{}, ResultHead: "frozen",
					Checkpoint: &Checkpoint{Stage: stage},
					Roles:      map[string]FrozenRole{"worker": {}, "planner": {}, "auditor": {}, "verifier": {}},
					RoleCalls:  []RoleCall{{ID: "recorded-role", State: state}}}
				if err := (&Service{}).recoveryCheck(m); err == nil || !strings.Contains(err.Error(), "角色调用") {
					t.Fatalf("recoveryCheck = %v; confirmed failed result must not be reprocessed", err)
				}
			})
		}
	}
}

func TestRecoveryKeepsUnfailedSourceCheckpointResumable(t *testing.T) {
	for _, state := range []string{"STARTING", "RECEIVED", "VALIDATED"} {
		m := Mission{State: "PAUSED", Source: &SourceSnapshot{}, Checkpoint: &Checkpoint{Stage: "source"},
			Roles:     map[string]FrozenRole{"worker": {}, "planner": {}, "auditor": {}, "verifier": {}},
			RoleCalls: []RoleCall{{State: state}}}
		if err := (&Service{}).recoveryCheck(m); err != nil {
			t.Fatalf("unfailed source checkpoint %s: %v", state, err)
		}
	}
}
