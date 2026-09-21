package kimiacp

import (
	"encoding/json"
	"testing"

	acpdriver "github.com/aoagents/agent-orchestrator/backend/internal/adapters/chatdriver/acp"
	acpsdk "github.com/coder/acp-go-sdk"
)

func argumentContent(text string) []acpsdk.ToolCallContent {
	return []acpsdk.ToolCallContent{{Content: &acpsdk.ToolCallContentContent{Type: "content", Content: acpsdk.TextBlock(text)}}}
}

func inputFixture(t *testing.T, name, text string) acpdriver.PermissionInputAccumulator {
	t.Helper()
	factory := kimiPermissionInputDecoder(acpsdk.InitializeResponse{AgentInfo: &acpsdk.Implementation{Name: "Kimi Code CLI", Version: "2.0.2"}})
	return factory(acpsdk.SessionUpdateToolCall{ToolCallId: "0:tool", Title: name, Kind: acpsdk.ToolKindEdit, Status: acpsdk.ToolCallStatusPending, Content: argumentContent(text)})
}

func inputUpdate(text string) acpsdk.SessionToolCallUpdate {
	return acpsdk.SessionToolCallUpdate{ToolCallId: "0:tool", Status: acpsdk.Ptr(acpsdk.ToolCallStatusInProgress), Content: argumentContent(text)}
}

func TestKimi202InputExactVersionAndStandardRawFacts(t *testing.T) {
	for _, info := range []*acpsdk.Implementation{nil, {Name: "Other", Version: "2.0.2"}, {Name: "Kimi Code CLI", Version: "2.0.3"}} {
		if kimiPermissionInputDecoder(acpsdk.InitializeResponse{AgentInfo: info}) != nil {
			t.Fatal("unverified provider enabled")
		}
	}
	factory := kimiPermissionInputDecoder(acpsdk.InitializeResponse{AgentInfo: &acpsdk.Implementation{Name: "Kimi Code CLI", Version: "2.0.2"}})
	if factory(acpsdk.SessionUpdateToolCall{Title: "Write", RawInput: map[string]any{"path": "a"}}) != nil {
		t.Fatal("standard rawInput path replaced")
	}
}

func TestKimi202InputDecodesCompleteAndFragmentedOriginalArguments(t *testing.T) {
	for _, name := range []string{"Write", "Edit"} {
		text := `{"path":"solution.py","content":"replacement","mode":"overwrite"}`
		if name == "Edit" {
			text = `{"path":"solution.py","old_string":"old","new_string":"new","replace_all":false}`
		}
		for _, fragmented := range []bool{false, true} {
			a := inputFixture(t, name, text)
			if fragmented {
				a = inputFixture(t, name, "")
				for i := 1; i <= len(text); i++ {
					a.Update(inputUpdate(text[:i]))
				}
			}
			input, err := a.Decode(acpsdk.ToolCallUpdate{ToolCallId: "0:tool", Title: acpsdk.Ptr(name)})
			if err != nil {
				t.Fatal(err)
			}
			var want any
			_ = json.Unmarshal([]byte(text), &want)
			x, _ := json.Marshal(input)
			y, _ := json.Marshal(want)
			if string(x) != string(y) {
				t.Fatal("original input changed")
			}
		}
	}
}

func TestKimi202InputRejectsMalformedAmbiguousAndChangedStream(t *testing.T) {
	valid := `{"path":"solution.py","content":"new"}`
	for _, text := range []string{`{"path":"solution.py","path":"check.py","content":"x"}`, valid + `{}`, `[]`, `null`, `{`, `{"path":"solution.py"}`, `{"path":"solution.py","content":"x","command":"bad"}`, `{"path":{},"content":"x"}`, `{"path":"","content":"x"}`, `{"path":"solution.py","content":null}`, `{"path":"solution.py","content":"x","mode":"execute"}`} {
		if _, err := inputFixture(t, "Write", text).Decode(acpsdk.ToolCallUpdate{ToolCallId: "0:tool"}); err == nil {
			t.Fatalf("invalid JSON admitted: %s", text)
		}
	}
	for _, mutation := range []string{"rollback", "replace", "repeat", "title", "kind", "terminal", "raw-output", "locations", "diff", "foreign-id", "raw-conflict"} {
		t.Run(mutation, func(t *testing.T) {
			a := inputFixture(t, "Write", valid)
			u := inputUpdate(valid + " ")
			switch mutation {
			case "rollback":
				u.Content = argumentContent(valid[:4])
			case "replace":
				u.Content = argumentContent(`{"path":"check.py","content":"new"}`)
			case "repeat":
				u.Content = argumentContent(valid)
			case "title":
				u.Title = acpsdk.Ptr("Edit")
			case "kind":
				u.Kind = acpsdk.Ptr(acpsdk.ToolKindExecute)
			case "terminal":
				u.Status = acpsdk.Ptr(acpsdk.ToolCallStatusCompleted)
			case "raw-output":
				u.RawOutput = "output"
			case "locations":
				u.Locations = []acpsdk.ToolCallLocation{{Path: "check.py"}}
			case "diff":
				u.Content = append(u.Content, acpsdk.ToolCallContent{Diff: &acpsdk.ToolCallContentDiff{Path: "solution.py"}})
			case "foreign-id":
				u.ToolCallId = "other"
			case "raw-conflict":
				u.RawInput = map[string]any{"path": "check.py", "content": "new"}
			}
			a.Update(u)
			a.Update(inputUpdate(valid + "  "))
			if _, err := a.Decode(acpsdk.ToolCallUpdate{ToolCallId: "0:tool"}); err == nil {
				t.Fatal("invalid stream recovered")
			}
		})
	}
}

func TestKimi202InputRejectsMalformedInitialAndPermissionFacts(t *testing.T) {
	factory := kimiPermissionInputDecoder(acpsdk.InitializeResponse{AgentInfo: &acpsdk.Implementation{Name: "Kimi Code CLI", Version: "2.0.2"}})
	valid := `{"path":"solution.py","content":"new","mode":"append"}`
	for _, mutation := range []string{"missing-content", "initial-kind", "initial-status", "initial-output", "initial-location", "request-title", "request-kind", "request-id", "request-output", "request-location"} {
		t.Run(mutation, func(t *testing.T) {
			initial := acpsdk.SessionUpdateToolCall{ToolCallId: "0:tool", Title: "Write", Kind: acpsdk.ToolKindEdit, Status: acpsdk.ToolCallStatusPending, Content: argumentContent(valid)}
			request := acpsdk.ToolCallUpdate{ToolCallId: "0:tool", Title: acpsdk.Ptr("Write")}
			switch mutation {
			case "missing-content":
				initial.Content = nil
			case "initial-kind":
				initial.Kind = acpsdk.ToolKindExecute
			case "initial-status":
				initial.Status = acpsdk.ToolCallStatusCompleted
			case "initial-output":
				initial.RawOutput = "out"
			case "initial-location":
				initial.Locations = []acpsdk.ToolCallLocation{{Path: "solution.py"}}
			case "request-title":
				request.Title = acpsdk.Ptr("Edit")
			case "request-kind":
				request.Kind = acpsdk.Ptr(acpsdk.ToolKindExecute)
			case "request-id":
				request.ToolCallId = "foreign"
			case "request-output":
				request.RawOutput = "out"
			case "request-location":
				request.Locations = []acpsdk.ToolCallLocation{{Path: "solution.py"}}
			}
			if _, err := factory(initial).Decode(request); err == nil {
				t.Fatal("ambiguous facts admitted")
			}
		})
	}
	if _, err := inputFixture(t, "Write", valid).Decode(acpsdk.ToolCallUpdate{ToolCallId: "0:tool"}); err != nil {
		t.Fatal("official append mode refused")
	}
}
