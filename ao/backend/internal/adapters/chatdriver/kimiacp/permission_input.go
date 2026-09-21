package kimiacp

import (
	"encoding/json"
	"errors"
	"io"
	"strings"

	acpdriver "github.com/aoagents/agent-orchestrator/backend/internal/adapters/chatdriver/acp"
	acpsdk "github.com/coder/acp-go-sdk"
)

// Kimi Code CLI 2.0.2 streams original tool arguments as cumulative text before
// requesting permission; canonical rawInput arrives only after that decision.
// No other provider/version or displayed diff/title can supply argument values.
func kimiPermissionInputDecoder(init acpsdk.InitializeResponse) func(acpsdk.SessionUpdateToolCall) acpdriver.PermissionInputAccumulator {
	if init.AgentInfo == nil || init.AgentInfo.Name != "Kimi Code CLI" || init.AgentInfo.Version != "2.0.2" {
		return nil
	}
	return func(initial acpsdk.SessionUpdateToolCall) acpdriver.PermissionInputAccumulator {
		if initial.RawInput != nil {
			return nil
		} // Ordinary ACP raw facts retain their existing path.
		if initial.Title != "Write" && initial.Title != "Edit" {
			return nil
		}
		a := &kimiInput{toolID: initial.ToolCallId, name: initial.Title}
		text, ok := kimiArgumentText(initial.Content)
		a.invalid = !ok || initial.ToolCallId == "" || initial.Kind != acpsdk.ToolKindEdit || initial.Status != acpsdk.ToolCallStatusPending || initial.RawOutput != nil || len(initial.Locations) != 0 || len(initial.Meta) != 0
		a.text = text
		return a
	}
}

type kimiInput struct {
	toolID     acpsdk.ToolCallId
	name, text string
	invalid    bool
}

func kimiArgumentText(content []acpsdk.ToolCallContent) (string, bool) {
	if len(content) != 1 || content[0].Content == nil || content[0].Diff != nil || content[0].Terminal != nil {
		return "", false
	}
	block := content[0].Content.Content
	if block.Text == nil || block.Image != nil || block.Audio != nil || block.Resource != nil || block.ResourceLink != nil {
		return "", false
	}
	text := block.Text.Text
	return text, len(text) <= 256*1024
}

func (a *kimiInput) Update(update acpsdk.SessionToolCallUpdate) {
	if a.invalid {
		return
	}
	if update.RawInput != nil {
		// Some agents send canonical input earlier. It cannot contradict bytes
		// already streamed under this identity, and is still checked by ACP.
		input, err := a.Decode(acpsdk.ToolCallUpdate{ToolCallId: update.ToolCallId})
		x, _ := json.Marshal(input)
		y, marshalErr := json.Marshal(update.RawInput)
		if err != nil || marshalErr != nil || string(x) != string(y) || (update.Kind != nil && *update.Kind != acpsdk.ToolKindEdit) || update.RawOutput != nil || (update.Status != nil && *update.Status != acpsdk.ToolCallStatusInProgress) {
			a.invalid = true
		}
		return
	}
	text, ok := kimiArgumentText(update.Content)
	if !ok || update.ToolCallId != a.toolID || update.Title != nil || update.Kind != nil || update.Status == nil || *update.Status != acpsdk.ToolCallStatusInProgress || update.RawOutput != nil || len(update.Locations) != 0 || len(update.Meta) != 0 || len(text) <= len(a.text) || !strings.HasPrefix(text, a.text) {
		a.invalid = true
		return
	}
	a.text = text
}

func (a *kimiInput) Decode(request acpsdk.ToolCallUpdate) (any, error) {
	reject := errors.New("kimi: incomplete or conflicting original tool arguments")
	if a.invalid || request.ToolCallId != a.toolID || (request.Title != nil && *request.Title != a.name) || (request.Kind != nil && *request.Kind != acpsdk.ToolKindEdit) || request.RawOutput != nil || len(request.Locations) != 0 || len(request.Meta) != 0 {
		return nil, reject
	}
	decoder := json.NewDecoder(strings.NewReader(a.text))
	first, err := decoder.Token()
	if err != nil || first != json.Delim('{') {
		return nil, reject
	}
	input := map[string]any{}
	for decoder.More() {
		keyToken, err := decoder.Token()
		key, ok := keyToken.(string)
		if err != nil || !ok {
			return nil, reject
		}
		if _, duplicate := input[key]; duplicate {
			return nil, reject
		}
		var value any
		if decoder.Decode(&value) != nil {
			return nil, reject
		}
		if key == "mode" && a.name == "Write" {
			if value != "overwrite" && value != "append" {
				return nil, reject
			}
		} else if key == "replace_all" && a.name == "Edit" {
			if _, ok := value.(bool); !ok {
				return nil, reject
			}
		} else {
			if key != "path" && !(a.name == "Write" && key == "content") && !(a.name == "Edit" && (key == "old_string" || key == "new_string")) {
				return nil, reject
			}
			if _, ok := value.(string); !ok {
				return nil, reject
			}
		}
		input[key] = value
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return nil, reject
	}
	var trailing any
	if decoder.Decode(&trailing) != io.EOF {
		return nil, reject
	}
	path, ok := input["path"].(string)
	if !ok || strings.TrimSpace(path) == "" {
		return nil, reject
	}
	if a.name == "Write" {
		if _, ok := input["content"]; !ok {
			return nil, reject
		}
	} else {
		old, ok := input["old_string"].(string)
		if !ok || old == "" {
			return nil, reject
		}
		if _, ok := input["new_string"]; !ok {
			return nil, reject
		}
	}
	return input, nil
}
