package acp

import (
	"bytes"
	"encoding/json"

	acpsdk "github.com/coder/acp-go-sdk"
)

type permissionBinding struct {
	sessionID, turnID, toolID string
	kind                      acpsdk.ToolKind
	input                     []byte
	tool                      *toolState
}

func samePermissionInput(a, b any) bool {
	x, err := json.Marshal(a)
	if err != nil {
		return false
	}
	y, err := json.Marshal(b)
	return err == nil && bytes.Equal(x, y)
}

func permissionToolActive(status acpsdk.ToolCallStatus) bool {
	return status == acpsdk.ToolCallStatusPending || status == acpsdk.ToolCallStatusInProgress
}

// ACP ToolCallUpdate is partial, including inside request_permission (pinned
// acp-go-sdk v0.13.5). Only original facts for this controller's active tool can
// fill missing fields. Titles, displayed diffs and locations never supply input.
func (c *conversation) permissionTool(params acpsdk.RequestPermissionRequest) (acpsdk.ToolCallUpdate, *permissionBinding, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	request := params.ToolCall
	if c.sessionID != "" && string(params.SessionId) != c.sessionID {
		return request, nil, false
	}
	tool := c.tools[string(request.ToolCallId)]
	if tool == nil {
		// Preserve standalone provider requests. Missing raw facts remain missing
		// and cannot pass CLAO's existing approval scope policy.
		return request, nil, true
	}
	if c.closed || c.sessionID == "" || string(params.SessionId) != c.sessionID || c.activeTurn == "" ||
		tool.turnID != c.activeTurn || tool.approvalUsed || !permissionToolActive(tool.status) ||
		(request.Status != nil && !permissionToolActive(*request.Status)) {
		return request, nil, false
	}
	if request.Kind != nil && tool.kind != "" && *request.Kind != tool.kind ||
		request.RawInput != nil && tool.rawInput != nil && !samePermissionInput(request.RawInput, tool.rawInput) ||
		request.Locations != nil && tool.locations != nil && !samePermissionInput(request.Locations, tool.locations) {
		return request, nil, false
	}
	if tool.kind == "" || tool.rawInput == nil {
		return request, nil, true
	}
	input, err := json.Marshal(tool.rawInput)
	if err != nil {
		return request, nil, false
	}
	if request.Kind == nil {
		kind := tool.kind
		request.Kind = &kind
	}
	if request.RawInput == nil {
		// Copy the JSON value: later updates must not mutate a parked request.
		if json.Unmarshal(input, &request.RawInput) != nil {
			return request, nil, false
		}
	}
	tool.approvalUsed = true
	return request, &permissionBinding{sessionID: c.sessionID, turnID: c.activeTurn,
		toolID: tool.id, kind: tool.kind, input: input, tool: tool}, true
}

// Called with c.mu held, both while parking and immediately before resolution.
func (c *conversation) permissionBindingCurrent(binding *permissionBinding) bool {
	tool := c.tools[binding.toolID]
	if c.closed || c.sessionID != binding.sessionID || c.activeTurn != binding.turnID || tool == nil ||
		tool != binding.tool || tool.turnID != binding.turnID || tool.approvalInvalid || !permissionToolActive(tool.status) || tool.kind != binding.kind {
		return false
	}
	input, err := json.Marshal(tool.rawInput)
	return err == nil && bytes.Equal(input, binding.input)
}
