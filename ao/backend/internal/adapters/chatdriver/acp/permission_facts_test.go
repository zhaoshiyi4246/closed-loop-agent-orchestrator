package acp

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/ports"
	acpsdk "github.com/coder/acp-go-sdk"
)

type fixedPermissionInput struct{ input any }

func (*fixedPermissionInput) Update(acpsdk.SessionToolCallUpdate)         {}
func (f *fixedPermissionInput) Decode(acpsdk.ToolCallUpdate) (any, error) { return f.input, nil }

func TestDecodedPermissionRetainsIdentityAndRejectsExplicitConflict(t *testing.T) {
	for _, mutation := range []string{"valid", "input-conflict", "turn", "duplicate", "terminal", "request-session"} {
		t.Run(mutation, func(t *testing.T) {
			c, request, input := rawPermission(t, "Write")
			tool := c.tools[string(request.ToolCall.ToolCallId)]
			tool.rawInput = nil
			tool.inputAccumulator = &fixedPermissionInput{input: input}
			switch mutation {
			case "input-conflict":
				request.ToolCall.RawInput = map[string]any{"path": "check.py"}
			case "turn":
				c.activeTurn = "next"
			case "duplicate":
				tool.approvalUsed = true
			case "terminal":
				tool.status = acpsdk.ToolCallStatusCompleted
			case "request-session":
				request.SessionId = "other"
			}
			mapped, binding, valid := c.permissionTool(request)
			if mutation == "valid" {
				if !valid || binding == nil || !samePermissionInput(mapped.RawInput, input) {
					t.Fatal("decoded original facts were not bound")
				}
			} else if valid {
				t.Fatal("invalid decoded identity admitted")
			}
		})
	}
}

// Generic ACP partial-request fixture: preceding updates provide rawInput.
// Kimi 2.0.2 instead sends canonical rawInput after permission; its decoder
// and official offline consumer are tested in the provider package.
func rawPermission(t *testing.T, name string) (*conversation, acpsdk.RequestPermissionRequest, any) {
	t.Helper()
	c := &conversation{sessionID: "kimi-session", activeTurn: "turn-1",
		tools: map[string]*toolState{}, pending: map[string]*parkedPermission{}, events: make(chan ports.ChatEvent, 16)}
	input := map[string]any{"path": "solution.py", "content": "def add(a, b):\n    return a + b\n"}
	if name == "Edit" {
		input = map[string]any{"path": "solution.py", "old_string": "return a - b", "new_string": "return a + b"}
	}
	for _, update := range []acpsdk.SessionUpdate{
		{ToolCall: &acpsdk.SessionUpdateToolCall{SessionUpdate: "tool_call", ToolCallId: "0:offline-tool-1", Title: name,
			Kind: acpsdk.ToolKindEdit, Status: acpsdk.ToolCallStatusPending}},
		{ToolCallUpdate: &acpsdk.SessionToolCallUpdate{SessionUpdate: "tool_call_update", ToolCallId: "0:offline-tool-1",
			Title: acpsdk.Ptr(name + " solution.py"), Kind: acpsdk.Ptr(acpsdk.ToolKindEdit),
			Status: acpsdk.Ptr(acpsdk.ToolCallStatusInProgress), RawInput: input}},
	} {
		if err := c.SessionUpdate(context.Background(), acpsdk.SessionNotification{SessionId: "kimi-session", Update: update}); err != nil {
			t.Fatal(err)
		}
	}
	for len(c.events) > 0 {
		<-c.events
	}
	return c, acpsdk.RequestPermissionRequest{SessionId: "kimi-session",
		ToolCall: acpsdk.ToolCallUpdate{ToolCallId: "0:offline-tool-1", Title: acpsdk.Ptr(name)},
		Options: []acpsdk.PermissionOption{
			{OptionId: "approve_once", Name: "Approve once", Kind: acpsdk.PermissionOptionKindAllowOnce},
			{OptionId: "approve_always", Name: "Approve for this session", Kind: acpsdk.PermissionOptionKindAllowAlways},
			{OptionId: "reject", Name: "Reject", Kind: acpsdk.PermissionOptionKindRejectOnce},
		}}, input
}

func TestPartialPermissionUsesCurrentOriginalFactsAndOfferedOnce(t *testing.T) {
	for _, name := range []string{"Write", "Edit"} {
		t.Run(name, func(t *testing.T) {
			c, request, input := rawPermission(t, name)
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			done := make(chan acpsdk.RequestPermissionResponse, 1)
			go func() { result, _ := c.RequestPermission(ctx, request); done <- result }()
			event := nextEvent(t, c.events)
			if event.Kind != ports.ChatEventApprovalRequested || event.ActivityKind != domain.ActivityKindFileChange || event.ProviderTurnID != "turn-1" {
				t.Fatalf("event = %#v", event)
			}
			var detail map[string]any
			if err := json.Unmarshal(event.Detail, &detail); err != nil {
				t.Fatal(err)
			}
			if detail["protocol"] != "acp" || detail["toolKind"] != "edit" || detail["subjectKind"] != "file_change" || !samePermissionInput(detail["input"], input) {
				t.Fatalf("detail = %s", event.Detail)
			}
			if err := c.ResolveRequest(ctx, event.RequestID, ports.ChatDecision{ID: "approve_once"}); err != nil {
				t.Fatal(err)
			}
			if response := <-done; response.Outcome.Selected == nil || response.Outcome.Selected.OptionId != "approve_once" {
				t.Fatalf("response = %#v", response)
			}
			if _, _, valid := c.permissionTool(request); valid {
				t.Fatal("same tool permission replay accepted")
			}
		})
	}
}

func TestPartialPermissionRejectsForeignStaleConflictingAndTerminalFacts(t *testing.T) {
	for _, mutation := range []string{"session", "turn", "idle", "closed", "terminal", "unknown-status", "kind", "input", "locations", "duplicate", "update-only"} {
		t.Run(mutation, func(t *testing.T) {
			c, request, _ := rawPermission(t, "Write")
			tool := c.tools[string(request.ToolCall.ToolCallId)]
			switch mutation {
			case "session":
				request.SessionId = "other-session"
			case "turn":
				c.activeTurn = "turn-2"
			case "idle":
				c.activeTurn = ""
			case "closed":
				c.closed = true
			case "terminal":
				tool.status = acpsdk.ToolCallStatusCompleted
			case "unknown-status":
				tool.status = "future-status"
			case "kind":
				request.ToolCall.Kind = acpsdk.Ptr(acpsdk.ToolKindExecute)
			case "input":
				request.ToolCall.RawInput = map[string]any{"path": "check.py"}
			case "locations":
				tool.locations = []acpsdk.ToolCallLocation{{Path: "solution.py"}}
				request.ToolCall.Locations = []acpsdk.ToolCallLocation{{Path: "check.py"}}
			case "duplicate":
				tool.approvalUsed = true
			case "update-only":
				tool.turnID = ""
			}
			if _, _, valid := c.permissionTool(request); valid {
				t.Fatal("unsafe permission facts admitted")
			}
		})
	}
}

func TestPartialPermissionDoesNotInventMissingOrUnknownInput(t *testing.T) {
	for _, missing := range []string{"unknown", "input", "kind"} {
		c, request, _ := rawPermission(t, "Edit")
		tool := c.tools[string(request.ToolCall.ToolCallId)]
		switch missing {
		case "unknown":
			delete(c.tools, tool.id)
		case "input":
			tool.rawInput = nil
		case "kind":
			tool.kind = ""
		}
		completed, binding, _ := c.permissionTool(request)
		if completed.RawInput != nil || completed.Kind != nil || binding != nil {
			t.Fatalf("%s: invented input from title/diff", missing)
		}
	}
}

func TestPermissionKeepsExplicitMatchingOriginalInput(t *testing.T) {
	c, request, input := rawPermission(t, "Write")
	request.ToolCall.RawInput = input
	request.ToolCall.Kind = acpsdk.Ptr(acpsdk.ToolKindEdit)
	completed, binding, valid := c.permissionTool(request)
	if !valid || binding == nil || !samePermissionInput(completed.RawInput, input) || *completed.Kind != acpsdk.ToolKindEdit {
		t.Fatal("matching original permission input was not retained")
	}
}

func TestPermissionBindingRejectsChangesWhileApprovalIsParked(t *testing.T) {
	for _, mutation := range []string{"session", "turn", "terminal", "input", "kind", "replacement", "changed-back", "argument-content-changed-back"} {
		t.Run(mutation, func(t *testing.T) {
			c, request, input := rawPermission(t, "Write")
			_, binding, valid := c.permissionTool(request)
			if !valid || binding == nil {
				t.Fatal("missing binding")
			}
			c.pending["request"] = &parkedPermission{options: map[string]json.RawMessage{"approve_once": nil}, result: make(chan string, 1), binding: binding}
			parked := c.pending["request"]
			tool := c.tools[binding.toolID]
			switch mutation {
			case "session":
				c.sessionID = "other"
			case "turn":
				c.activeTurn = "next"
			case "terminal":
				tool.status = acpsdk.ToolCallStatusCompleted
			case "input":
				tool.rawInput = map[string]any{"path": "check.py"}
			case "kind":
				tool.kind = acpsdk.ToolKindExecute
			case "replacement":
				clone := *tool
				c.tools[binding.toolID] = &clone
			case "changed-back":
				c.mergeToolUpdate(&acpsdk.SessionToolCallUpdate{ToolCallId: request.ToolCall.ToolCallId, RawInput: map[string]any{"path": "check.py"}})
				c.mergeToolUpdate(&acpsdk.SessionToolCallUpdate{ToolCallId: request.ToolCall.ToolCallId, RawInput: input})
			case "argument-content-changed-back":
				tool.inputAccumulator = &fixedPermissionInput{input: input}
				original := tool.content
				c.mergeToolUpdate(&acpsdk.SessionToolCallUpdate{ToolCallId: request.ToolCall.ToolCallId, Content: []acpsdk.ToolCallContent{{Content: &acpsdk.ToolCallContentContent{Content: acpsdk.TextBlock("changed")}}}})
				c.mergeToolUpdate(&acpsdk.SessionToolCallUpdate{ToolCallId: request.ToolCall.ToolCallId, Content: original})
			}
			if err := c.ResolveRequest(context.Background(), "request", ports.ChatDecision{ID: "approve_once"}); err != ports.ErrChatRequestNotPending {
				t.Fatalf("resolution = %v", err)
			}
			if selected := <-parked.result; selected != "" {
				t.Fatalf("changed request allowed: %q", selected)
			}
		})
	}
}

func TestPermissionMappedRawFactsPassActualCLAOAcceptance(t *testing.T) {
	python := os.Getenv("CLAO_TEST_PYTHON")
	if python == "" {
		t.Skip("set CLAO_TEST_PYTHON to the project venv for actual acceptance integration")
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	core := filepath.Clean(filepath.Join(cwd, "../../../../../../clao/src"))
	for _, scenario := range []string{"Write", "Edit", "forbidden", "outside", "missing"} {
		t.Run(scenario, func(t *testing.T) {
			c, request, _ := rawPermission(t, scenario)
			tool, _, _ := c.permissionTool(request)
			if scenario == "missing" {
				tool.RawInput = nil
			}
			if scenario == "forbidden" {
				tool.RawInput = map[string]any{"path": "check.py", "content": "changed"}
			}
			if scenario == "outside" {
				tool.RawInput = map[string]any{"path": "../escape.py", "content": "changed"}
			}
			var detail map[string]any
			if err := json.Unmarshal(approvalToolDetail(tool, activityKindFromTool(pointerValue(tool.Kind))), &detail); err != nil {
				t.Fatal(err)
			}
			detail["decisions"] = []any{map[string]any{"id": "approve_once", "kind": "allow_once"}, map[string]any{"id": "approve_always", "kind": "allow_always"}, map[string]any{"id": "reject", "kind": "reject_once"}}
			payload, _ := json.Marshal(map[string]any{"workspace": t.TempDir(), "base": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"task": map[string]any{"task_id": "synthetic", "project_id": "synthetic", "objective": "fix addition", "allowed_paths": []string{"solution.py"}, "forbidden_paths": []string{"check.py"},
					"acceptance_criteria": []any{map[string]any{"id": "AC1", "description": "addition"}}, "gate_commands": []string{"python check.py"}},
				"approval": map[string]any{"activityKind": "approval", "status": "pending", "requestId": "current-request", "detail": detail}})
			cmd := exec.Command(python, "-B", "-m", "loopcore.ao_acceptance")
			for _, key := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"} {
				if value, ok := os.LookupEnv(key); ok {
					cmd.Env = append(cmd.Env, key+"="+value)
				}
			}
			cmd.Env = append(cmd.Env, "PYTHONPATH="+core, "PYTHONUTF8=1")
			cmd.Stdin = bytes.NewReader(payload)
			output, err := cmd.CombinedOutput()
			if err != nil {
				t.Fatalf("acceptance: %v: %s", err, output)
			}
			var result struct {
				OK bool `json:"ok"`
			}
			if err := json.Unmarshal(output, &result); err != nil {
				t.Fatalf("acceptance JSON: %v: %s", err, output)
			}
			if result.OK != (scenario == "Write" || scenario == "Edit") {
				t.Fatalf("acceptance %s: %s", scenario, output)
			}
		})
	}
}
