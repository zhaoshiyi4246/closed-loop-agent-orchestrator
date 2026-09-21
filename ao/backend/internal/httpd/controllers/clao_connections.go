package controllers

import (
	"context"
	"errors"
	"net/http"

	"github.com/aoagents/agent-orchestrator/backend/internal/httpd/envelope"
	"github.com/aoagents/agent-orchestrator/backend/internal/service/claoloop"
)

func (c *CLAOController) connectionCatalog(w http.ResponseWriter, r *http.Request) {
	svc, ok := c.Svc.(interface {
		ConnectionCatalog(context.Context) (claoloop.ConnectionCatalog, error)
	})
	if !ok {
		c.fail(w, r, 503, "Connection catalog unavailable")
		return
	}
	v, err := svc.ConnectionCatalog(r.Context())
	if err != nil {
		c.fail(w, r, 503, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, v)
}

func (c *CLAOController) createConnection(w http.ResponseWriter, r *http.Request) {
	var in claoloop.ConnectionRequest
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid connection JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		CreateConnection(context.Context, claoloop.ConnectionRequest) (claoloop.ConnectionResponse, error)
	})
	if !ok {
		c.fail(w, r, 503, "Connection creation unavailable")
		return
	}
	v, err := svc.CreateConnection(r.Context(), in)
	if err != nil {
		if errors.Is(err, claoloop.ErrConnectionSaveUnconfirmed) {
			c.fail(w, r, http.StatusServiceUnavailable, err.Error())
			return
		}
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, v)
}
