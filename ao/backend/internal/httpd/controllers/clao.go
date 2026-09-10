package controllers

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"fmt"
	"mime"
	"net"
	"net/http"
	"strings"

	"github.com/aoagents/agent-orchestrator/backend/internal/httpd/envelope"
	"github.com/aoagents/agent-orchestrator/backend/internal/service/claoloop"
	"github.com/go-chi/chi/v5"
)

type CLAOService interface {
	Create(context.Context, claoloop.Request) (claoloop.Mission, error)
	Get(context.Context, string) (claoloop.Mission, error)
	List(context.Context) ([]claoloop.Mission, error)
	Cancel(context.Context, string) (claoloop.Mission, error)
	Continue(context.Context, string) (claoloop.Mission, error)
	PostDirective(context.Context, string, claoloop.DirectiveRequest) (claoloop.Directive, error)
}
type CLAOController struct {
	Svc     CLAOService
	Port    int
	Origins []string
	nonce   string
}

func NewCLAOController(svc CLAOService, port int, origins []string) *CLAOController {
	return &CLAOController{Svc: svc, Port: port, Origins: origins, nonce: rand.Text()}
}

type CLAONonceResponse struct {
	Nonce string `json:"nonce"`
}
type CLAOMissionResponse struct {
	Mission claoloop.Mission `json:"mission"`
}
type CLAOMissionListResponse struct {
	Missions []claoloop.Mission `json:"missions"`
}
type CLAOIDParam struct {
	ID string `path:"id"`
}

func (c *CLAOController) Register(r chi.Router) {
	r.Route("/clao", func(r chi.Router) {
		r.Use(c.boundary)
		r.Get("/session", c.session)
		r.Get("/missions", c.list)
		r.Post("/missions", c.create)
		r.Get("/missions/{id}", c.get)
		r.Post("/missions/{id}/cancel", c.cancel)
		r.Post("/missions/{id}/continue", c.resume)
		r.Post("/missions/{id}/directives", c.directive)
	})
}

type CLAODirectiveResponse struct {
	Directive claoloop.Directive `json:"directive"`
}

func (c *CLAOController) resume(w http.ResponseWriter, r *http.Request) {
	var body struct{}
	if err := decodeJSONStrict(r, &body); err != nil {
		c.fail(w, r, 400, "Invalid JSON")
		return
	}
	m, err := c.Svc.Continue(r.Context(), chi.URLParam(r, "id"))
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 202, CLAOMissionResponse{Mission: m})
}
func (c *CLAOController) directive(w http.ResponseWriter, r *http.Request) {
	var body claoloop.DirectiveRequest
	if err := decodeJSONStrict(r, &body); err != nil {
		c.fail(w, r, 400, "Invalid directive JSON")
		return
	}
	d, err := c.Svc.PostDirective(r.Context(), chi.URLParam(r, "id"), body)
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	status := 202
	if d.State == "rejected" {
		status = 409
	}
	envelope.WriteJSON(w, status, CLAODirectiveResponse{Directive: d})
}
func (c *CLAOController) fail(w http.ResponseWriter, r *http.Request, status int, msg string) {
	envelope.WriteAPIError(w, r, status, "clao_error", "CLAO_REQUEST_REJECTED", msg, nil)
}
func (c *CLAOController) boundary(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, port, err := net.SplitHostPort(r.Host)
		if err != nil || port != fmt.Sprint(c.Port) || (host != "127.0.0.1" && host != "localhost" && host != "::1") {
			c.fail(w, r, 403, "Unsupported local Host")
			return
		}
		origin := r.Header.Get("Origin")
		allowed := origin == "http://"+r.Host || origin == "app://renderer"
		for _, known := range c.Origins {
			if known != "*" && origin == known {
				allowed = true
			}
		}
		if origin != "" && !allowed {
			c.fail(w, r, 403, "Cross-origin request refused")
			return
		}
		if r.Method != http.MethodGet {
			media, _, e := mime.ParseMediaType(r.Header.Get("Content-Type"))
			if origin == "" || !allowed || e != nil || media != "application/json" || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-CLAO-Nonce")), []byte(c.nonce)) != 1 {
				c.fail(w, r, 403, "Local JSON request and current session nonce required")
				return
			}
		}
		if c.Svc == nil {
			c.fail(w, r, 503, "CLAO acceptance service unavailable")
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}
func (c *CLAOController) session(w http.ResponseWriter, r *http.Request) {
	envelope.WriteJSON(w, 200, CLAONonceResponse{Nonce: c.nonce})
}
func (c *CLAOController) create(w http.ResponseWriter, r *http.Request) {
	var in claoloop.Request
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid task JSON")
		return
	}
	m, err := c.Svc.Create(r.Context(), in)
	if err != nil {
		c.fail(w, r, 400, err.Error())
		return
	}
	envelope.WriteJSON(w, 202, CLAOMissionResponse{Mission: m})
}
func (c *CLAOController) get(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if strings.ContainsAny(id, "/\\.\x00") {
		c.fail(w, r, 400, "Invalid mission ID")
		return
	}
	m, err := c.Svc.Get(r.Context(), id)
	if err != nil {
		c.fail(w, r, 404, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, CLAOMissionResponse{Mission: m})
}
func (c *CLAOController) list(w http.ResponseWriter, r *http.Request) {
	ms, err := c.Svc.List(r.Context())
	if err != nil {
		c.fail(w, r, 500, "Acceptance records could not be read")
		return
	}
	envelope.WriteJSON(w, 200, CLAOMissionListResponse{Missions: ms})
}
func (c *CLAOController) cancel(w http.ResponseWriter, r *http.Request) {
	var body struct{}
	if err := decodeJSONStrict(r, &body); err != nil {
		c.fail(w, r, 400, "Invalid JSON")
		return
	}
	m, err := c.Svc.Cancel(r.Context(), chi.URLParam(r, "id"))
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 202, CLAOMissionResponse{Mission: m})
}
