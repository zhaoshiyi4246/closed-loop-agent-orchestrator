// Controlled external OpenCode/Codex process for native AO integration tests.
// No AO service, storage, Session or workspace implementation is replaced.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type message struct {
	ID     any            `json:"id"`
	Method string         `json:"method"`
	Params map[string]any `json:"params"`
	Result map[string]any `json:"result"`
}

var encoder = json.NewEncoder(os.Stdout)
var workspace string
var session = "fixture-session"
var pending *message

func reply(id any, value any) {
	_ = encoder.Encode(map[string]any{"jsonrpc": "2.0", "id": id, "result": value})
}
func event(method string, value any) {
	_ = encoder.Encode(map[string]any{"jsonrpc": "2.0", "method": method, "params": value})
}
func trace(kind, text string) {
	p := os.Getenv("CLAO_FIXTURE_TRACE")
	if p == "" {
		return
	}
	f, e := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if e == nil {
		defer f.Close()
		_ = json.NewEncoder(f).Encode(map[string]string{"kind": kind, "workspace": workspace, "text": text})
	}
}
func options() []any {
	return []any{map[string]any{"id": "model", "name": "Model", "type": "select", "currentValue": "test/native", "options": []any{map[string]any{"value": "test/native", "name": "Native fixture"}, map[string]any{"value": "test/second", "name": "Second fixture"}}}}
}
func promptText(params map[string]any) string { b, _ := json.Marshal(params); return string(b) }
func roleInput(text string) map[string]any {
	for i := 0; i < len(text); i++ {
		if text[i] == '{' {
			var obj map[string]any
			if json.NewDecoder(strings.NewReader(text[i:])).Decode(&obj) == nil && (obj["evidence_bundle"] != nil && obj["audit_id"] != nil || obj["audit_result"] != nil && obj["action_id"] != nil || obj["verifier_input"] != nil && obj["verify_id"] != nil) {
				return obj
			}
		}
	}
	return nil
}
func roleResult(in map[string]any, text string) string {
	var out map[string]any
	if in["audit_id"] != nil {
		decision := "LOCAL_FIX"
		if strings.Contains(text, "PLAN_HUMAN") {
			decision = "HUMAN"
		}
		out = map[string]any{"audit_id": in["audit_id"], "task_id": in["task_id"], "decision": decision, "diagnosis": "实际 Gate 失败；按输入中的差异和失败输出定位", "confidence": 0.9, "failed_criteria": []any{}, "evidence": []any{map[string]any{"type": "test_failure", "summary": "Gate did not accept result.txt", "reference": "evidence_bundle.evidence.test_output"}}, "recommended_action": "Fix result.txt without changing check.py"}
	} else {
		action := "SEND_LOCAL_FIX"
		for marker, choice := range map[string]string{"PLAN_REPLACE": "REPLAN_SPAWN", "PLAN_HUMAN": "HUMAN", "PLAN_CANDIDATE": "CANDIDATE_DONE", "PLAN_CONTINUE": "CONTINUE"} {
			if strings.Contains(text, marker) {
				action = choice
			}
		}
		out = map[string]any{"action_id": in["action_id"], "task_id": in["task_id"], "action": action, "reason": "使用本次审核证据与剩余预算"}
		if action == "SEND_LOCAL_FIX" {
			out["target_session_id"] = in["target_session_id"]
			out["message"] = "Fix result.txt to accepted; retain original constraints."
		}
		if action == "REPLAN_SPAWN" {
			out["replacement_task_spec"] = map[string]any{"objective": "replacement-pass: rebuild accepted result under original contract"}
		}
	}
	if strings.Contains(text, "BAD_ROLE_ID") {
		out["task_id"] = "wrong-task"
	}
	b, _ := json.Marshal(out)
	return string(b)
}
func reviewResult(text string) string {
	// The prompt contains the normal retained VerifierInput JSON. Find the
	// correlated identity from its trailing object rather than fabricate an ID.
	for i := 0; i < len(text); i++ {
		if text[i] != '{' {
			continue
		}
		var in map[string]any
		if json.NewDecoder(strings.NewReader(text[i:])).Decode(&in) != nil {
			continue
		}
		id, _ := in["verify_id"].(string)
		task, _ := in["task_id"].(string)
		if id == "" || in["verifier_input"] == nil {
			continue
		}
		checks := []any{}
		v, _ := in["verifier_input"].(map[string]any)
		spec, _ := v["task_spec"].(map[string]any)
		acs, _ := spec["acceptance_criteria"].([]any)
		for _, raw := range acs {
			ac := raw.(map[string]any)
			checks = append(checks, map[string]any{"ac_id": ac["id"], "verdict": "PASS", "note": "checked provided complete evidence"})
		}
		b, _ := json.Marshal(map[string]any{"verify_id": id, "task_id": task, "verdict": "PASS", "ac_checks": checks, "anti_gaming": []any{}, "summary": "fixture independent review"})
		return string(b)
	}
	return "{}"
}
func extractText(params map[string]any) string {
	parts := []string{}
	for _, key := range []string{"prompt", "input"} {
		if arr, ok := params[key].([]any); ok {
			for _, raw := range arr {
				if m, ok := raw.(map[string]any); ok {
					if s, ok := m["text"].(string); ok {
						parts = append(parts, s)
					}
				}
			}
		}
	}
	return strings.Join(parts, "\n")
}
func complete(m message, codex bool) {
	text := extractText(m.Params)
	trace("prompt", text)
	// Hold only the initial Worker at the external protocol boundary so a test
	// can change project defaults before any subsequent role/repair/replacement.
	if roleInput(text) == nil && strings.Contains(text, "HOLD_CONFIG") && !strings.Contains(text, "replacement-pass") {
		trace("config_wait", "waiting for test release")
		wait := 20 * time.Second
		if os.Getenv("CLAO_FIXTURE_LONG_HOLD") == "1" {
			wait = 90 * time.Second
		}
		deadline := time.Now().Add(wait)
		for {
			if _, err := os.Stat(os.Getenv("CLAO_FIXTURE_RELEASE_CONFIG")); err == nil {
				break
			}
			if time.Now().After(deadline) {
				panic("test configuration release not received")
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	answer := "Worker turn complete; await program acceptance."
	if in := roleInput(text); in != nil && (in["audit_id"] != nil || in["action_id"] != nil) {
		answer = roleResult(in, text)
	} else if strings.Contains(text, "verify_id") && strings.Contains(text, "verifier_input") {
		answer = reviewResult(text)
		if strings.Contains(text, "EMPTY_REVIEW") {
			answer = ""
		}
	} else {
		value := "accepted\n"
		if strings.Contains(text, "REPAIR_ONCE") || strings.Contains(text, "PLAN_") || strings.Contains(text, "BAD_ROLE_ID") || strings.Contains(text, "HOLD_") {
			value = "broken\n"
		}
		if strings.Contains(text, "replacement-pass") {
			value = "accepted\n"
		}
		if strings.Contains(text, "FAIL_GATE") {
			value = "broken\n"
			_ = os.WriteFile(filepath.Join(workspace, ".fixture-failure"), []byte("fail"), 0600)
		}
		if _, err := os.Stat(filepath.Join(workspace, ".fixture-failure")); err == nil {
			value = "broken\n"
		}
		_ = os.WriteFile(filepath.Join(workspace, "result.txt"), []byte(value), 0600)
	}
	if codex {
		tid := fmt.Sprintf("turn-%d", time.Now().UnixNano())
		reply(m.ID, map[string]any{"turn": map[string]any{"id": tid, "status": "inProgress", "items": []any{}}})
		event("turn/started", map[string]any{"threadId": session, "turn": map[string]any{"id": tid, "status": "inProgress", "items": []any{}}})
		event("item/completed", map[string]any{"threadId": session, "turnId": tid, "item": map[string]any{"id": "answer-" + tid, "type": "agentMessage", "text": answer}})
		event("turn/completed", map[string]any{"threadId": session, "turn": map[string]any{"id": tid, "status": "completed", "items": []any{}}})
	} else {
		if strings.Contains(text, "REPORT_MODEL") {
			opts := options()
			opts[0].(map[string]any)["currentValue"] = "test/provider-confirmed"
			event("session/update", map[string]any{"sessionId": session, "update": map[string]any{"sessionUpdate": "config_option_update", "configOptions": opts}})
		}
		event("session/update", map[string]any{"sessionId": session, "update": map[string]any{"sessionUpdate": "agent_message_chunk", "content": map[string]any{"type": "text", "text": answer}}})
		reply(m.ID, map[string]any{"stopReason": "end_turn"})
	}
}
func main() {
	args := strings.Join(os.Args[1:], " ")
	if strings.Contains(args, "--version") {
		fmt.Println("0.150.1")
		return
	}
	if strings.Contains(args, "auth list") {
		fmt.Println("test API key")
		return
	}
	if strings.Contains(args, "login status") {
		fmt.Println("Logged in using ChatGPT")
		return
	}
	if strings.Contains(args, "models") && !strings.Contains(args, "app-server") {
		fmt.Println("test/native\ntest/second")
		return
	}
	codex := strings.Contains(strings.ToLower(filepath.Base(os.Args[0])), "codex")
	workspace, _ = os.Getwd()
	trace("policy", os.Getenv("OPENCODE_CONFIG_CONTENT"))
	scan := bufio.NewScanner(os.Stdin)
	scan.Buffer(make([]byte, 4096), 4<<20)
	for scan.Scan() {
		var m message
		if json.Unmarshal(scan.Bytes(), &m) != nil {
			continue
		}
		if m.Method == "" {
			if pending != nil {
				p := *pending
				pending = nil
				b, _ := json.Marshal(m.Result)
				trace("approval", string(b))
				if strings.Contains(string(b), "allow") {
					complete(p, codex)
				} else {
					reply(p.ID, map[string]any{"stopReason": "cancelled"})
				}
			}
			continue
		}
		switch m.Method {
		case "initialize":
			if codex {
				reply(m.ID, map[string]any{"userAgent": "codex/0.150.1"})
			} else {
				reply(m.ID, map[string]any{"protocolVersion": 1, "agentInfo": map[string]any{"name": "opencode", "version": "1.2.0"}, "agentCapabilities": map[string]any{"loadSession": true, "promptCapabilities": map[string]any{}}, "authMethods": []any{}})
			}
		case "initialized":
		case "model/list":
			reply(m.ID, map[string]any{"data": []any{map[string]any{"id": "test/native", "model": "test/native", "displayName": "Native fixture", "isDefault": true, "supportedReasoningEfforts": []any{}}}, "nextCursor": nil})
		case "config/read":
			reply(m.ID, map[string]any{"config": map[string]any{}})
		case "account/read":
			reply(m.ID, map[string]any{"account": map[string]any{"type": "chatgpt", "email": "fixture@example.invalid", "planType": "plus"}, "requiresOpenaiAuth": false})
		case "session/new", "session/load", "session/resume":
			// Isolated test switch at the external protocol boundary, before any
			// initial prompt. Production AO creation/rollback stays real.
			if marker := os.Getenv("CLAO_FIXTURE_FAIL_START"); marker != "" {
				if _, err := os.Stat(marker); err == nil {
					trace("start_rejected", "controlled session/new failure")
					_ = encoder.Encode(map[string]any{"jsonrpc": "2.0", "id": m.ID, "error": map[string]any{"code": -32603, "message": "controlled session/new failure"}})
					continue
				}
			}
			if cwd, ok := m.Params["cwd"].(string); ok {
				workspace = cwd
			}
			if id, ok := m.Params["sessionId"].(string); ok {
				session = id
			}
			trace(m.Method, promptText(m.Params))
			reply(m.ID, map[string]any{"sessionId": session, "configOptions": options(), "models": map[string]any{"currentModelId": "test/native", "availableModels": []any{map[string]any{"modelId": "test/native", "name": "Native fixture"}}}})
		case "session/set_config_option", "session/set_model", "session/set_mode":
			trace("selection", promptText(m.Params))
			reply(m.ID, map[string]any{"configOptions": options()})
		case "thread/start", "thread/resume":
			if cwd, ok := m.Params["cwd"].(string); ok {
				workspace = cwd
			}
			reply(m.ID, map[string]any{"thread": map[string]any{"id": session, "turns": []any{}, "cwd": workspace}, "model": "test/native", "modelProvider": "fixture", "cwd": workspace})
		case "session/prompt", "turn/start":
			text := extractText(m.Params)
			role := roleInput(text)
			waitRole := role != nil && (role["audit_id"] != nil && strings.Contains(text, "HOLD_AUDITOR") || role["action_id"] != nil && strings.Contains(text, "HOLD_PLANNER"))
			if strings.Contains(text, "WAIT_CANCEL") || waitRole {
				pending = &m
				trace("waiting", text)
				continue
			}
			if !codex && strings.Contains(text, "NEED_APPROVAL") && !strings.Contains(text, "verifier_input") {
				pending = &m
				tool := map[string]any{"toolCallId": "tool-1", "title": "python check.py", "kind": "execute", "status": "pending", "rawInput": map[string]any{"command": "python check.py", "cwd": workspace}}
				if strings.Contains(text, "DANGEROUS") {
					tool["rawInput"] = map[string]any{"command": "git reset --hard", "cwd": workspace}
				}
				if strings.Contains(text, "FORBIDDEN") {
					tool["kind"] = "edit"
					tool["rawInput"] = map[string]any{"file_path": filepath.Join(workspace, "private", "secret.txt"), "content": "test"}
				}
				if strings.Contains(text, "GIT_CONTROL") {
					tool["kind"] = "edit"
					tool["rawInput"] = map[string]any{"file_path": filepath.Join(workspace, ".git"), "content": "test"}
				}
				_ = encoder.Encode(map[string]any{"jsonrpc": "2.0", "id": 901, "method": "session/request_permission", "params": map[string]any{"sessionId": session, "toolCall": tool, "options": []any{map[string]any{"optionId": "allow", "name": "Allow once", "kind": "allow_once"}, map[string]any{"optionId": "always", "name": "Always allow", "kind": "allow_always"}, map[string]any{"optionId": "reject", "name": "Reject", "kind": "reject_once"}}}})
				continue
			}
			complete(m, codex)
		case "session/cancel", "turn/interrupt":
			if pending != nil {
				reply(pending.ID, map[string]any{"stopReason": "cancelled"})
				pending = nil
			}
			if m.ID != nil {
				reply(m.ID, map[string]any{})
			}
		default:
			if m.ID != nil {
				reply(m.ID, map[string]any{})
			}
		}
	}
}
