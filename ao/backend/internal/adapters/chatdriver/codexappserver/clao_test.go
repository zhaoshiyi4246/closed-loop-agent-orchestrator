package codexappserver

import (
	"encoding/json"
	"testing"
)

func TestCLAOApprovalRetainsAuthorizationContext(t *testing.T) {
	params := json.RawMessage(`{"threadId":"t","turnId":"turn","itemId":"i","command":"python check.py","cwd":"C:/work","environmentId":"remote","additionalPermissions":{"network":true},"availableDecisions":["accept","decline"]}`)
	opts, _, detail, turn := parseApproval("item/commandExecution/requestApproval", params)
	var got struct {
		ApprovalRequest json.RawMessage `json:"approvalRequest"`
	}
	if err := json.Unmarshal(detail, &got); err != nil {
		t.Fatal(err)
	}
	var original, retained any
	if err := json.Unmarshal(params, &original); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(got.ApprovalRequest, &retained); err != nil {
		t.Fatal(err)
	}
	a, _ := json.Marshal(original)
	b, _ := json.Marshal(retained)
	if string(a) != string(b) || len(opts) != 2 || turn != "turn" {
		t.Fatal("approval facts or native decisions lost")
	}
}
