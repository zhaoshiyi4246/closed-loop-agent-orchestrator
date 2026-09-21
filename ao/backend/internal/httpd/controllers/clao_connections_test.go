package controllers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/service/claoloop"
)

type connectionErrorService struct {
	CLAOService
	err error
}

func (s connectionErrorService) CreateConnection(context.Context, claoloop.ConnectionRequest) (claoloop.ConnectionResponse, error) {
	return claoloop.ConnectionResponse{}, s.err
}

func TestConnectionResponseDistinguishesUnconfirmedWrite(t *testing.T) {
	for _, tc := range []struct {
		err    error
		status int
	}{{claoloop.ErrConnectionSaveUnconfirmed, http.StatusServiceUnavailable}, {domain.ErrCLAOImportConflict, http.StatusConflict}} {
		c := NewCLAOController(connectionErrorService{err: tc.err}, 7341, nil)
		r := httptest.NewRequest(http.MethodPost, "/connections", strings.NewReader(`{"id":"01234567-89ab-cdef-0123-456789abcdef","name":"test","service":"bigmodel_general","model":"glm-5.3"}`))
		w := httptest.NewRecorder()
		c.createConnection(w, r)
		if w.Code != tc.status {
			t.Fatalf("%v: got %d want %d", tc.err, w.Code, tc.status)
		}
	}
}
