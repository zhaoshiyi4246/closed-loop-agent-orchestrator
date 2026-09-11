package controllers

import (
	"context"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/httpd/envelope"
	"github.com/aoagents/agent-orchestrator/backend/internal/service/claoloop"
	"github.com/go-chi/chi/v5"
	"net/http"
)

type CLAOProjectParam struct {
	ProjectID string `path:"projectId"`
}
type CLAOPackageParam struct {
	ID       string `path:"id"`
	Identity string `path:"identity"`
}
type CLAOSourceResponse struct {
	Source claoloop.SourcePreview `json:"source"`
}
type CLAOResultResponse struct {
	Result claoloop.ResultView `json:"result"`
}
type CLAOExportResponse struct {
	Package claoloop.ResultPackage `json:"package"`
}
type CLAOLocationResponse struct {
	Location claoloop.ResultLocation `json:"location"`
}
type CLAOProjectResponse struct {
	Project claoloop.LocalProject `json:"project"`
}
type CLAOCredentialRequest struct {
	APIKey string `json:"apiKey"`
}

func (c *CLAOController) reconnectLegacy(w http.ResponseWriter, r *http.Request) {
	var in CLAOCredentialRequest
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid credential JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		ReconnectLegacy(context.Context, string, string) (claoloop.LegacyCredentialStatus, error)
	})
	if !ok {
		c.fail(w, r, 503, "Connection unavailable")
		return
	}
	out, err := svc.ReconnectLegacy(r.Context(), chi.URLParam(r, "id"), in.APIKey)
	in.APIKey = ""
	if err != nil {
		c.fail(w, r, 400, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, out)
}

func (c *CLAOController) previewSource(w http.ResponseWriter, r *http.Request) {
	svc, ok := c.Svc.(interface {
		PreviewSource(context.Context, domain.ProjectID) (claoloop.SourcePreview, error)
	})
	if !ok {
		c.fail(w, r, 503, "Source unavailable")
		return
	}
	v, err := svc.PreviewSource(r.Context(), domain.ProjectID(chi.URLParam(r, "projectId")))
	if err != nil {
		c.fail(w, r, 400, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, CLAOSourceResponse{v})
}
func (c *CLAOController) result(w http.ResponseWriter, r *http.Request) {
	svc, ok := c.Svc.(interface {
		Result(context.Context, string) (claoloop.ResultView, error)
	})
	if !ok {
		c.fail(w, r, 503, "Result unavailable")
		return
	}
	v, err := svc.Result(r.Context(), chi.URLParam(r, "id"))
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, CLAOResultResponse{v})
}
func (c *CLAOController) exportResult(w http.ResponseWriter, r *http.Request) {
	var in struct{}
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		Export(context.Context, string) (claoloop.ResultPackage, error)
	})
	if !ok {
		c.fail(w, r, 503, "Export unavailable")
		return
	}
	v, err := svc.Export(r.Context(), chi.URLParam(r, "id"))
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, CLAOExportResponse{v})
}
func (c *CLAOController) downloadResult(w http.ResponseWriter, r *http.Request) {
	svc, ok := c.Svc.(interface {
		Download(context.Context, string, string) ([]byte, error)
	})
	if !ok {
		c.fail(w, r, 503, "Download unavailable")
		return
	}
	b, err := svc.Download(r.Context(), chi.URLParam(r, "id"), chi.URLParam(r, "identity"))
	if err != nil {
		c.fail(w, r, 404, err.Error())
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="clao-result.zip"`)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(200)
	_, _ = w.Write(b)
}
func (c *CLAOController) openResult(w http.ResponseWriter, r *http.Request) {
	var in struct{}
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		OpenResult(context.Context, string) (claoloop.ResultLocation, error)
	})
	if !ok {
		c.fail(w, r, 503, "Open unavailable")
		return
	}
	v, err := svc.OpenResult(r.Context(), chi.URLParam(r, "id"))
	if err != nil {
		c.fail(w, r, 409, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, CLAOLocationResponse{v})
}
func (c *CLAOController) openProject(w http.ResponseWriter, r *http.Request) {
	var in claoloop.LocalProjectRequest
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid project JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		OpenProject(context.Context, claoloop.LocalProjectRequest) (claoloop.LocalProject, error)
	})
	if !ok {
		c.fail(w, r, 503, "Project unavailable")
		return
	}
	v, err := svc.OpenProject(r.Context(), in)
	if err != nil {
		c.fail(w, r, 400, err.Error())
		return
	}
	envelope.WriteJSON(w, 201, CLAOProjectResponse{v})
}
func (c *CLAOController) imports(w http.ResponseWriter, r *http.Request) {
	svc, ok := c.Svc.(interface {
		LegacyCatalog(context.Context) (claoloop.LegacyCatalog, error)
	})
	if !ok {
		c.fail(w, r, 503, "Legacy import unavailable")
		return
	}
	v, err := svc.LegacyCatalog(r.Context())
	if err != nil {
		c.fail(w, r, 500, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, v)
}
func (c *CLAOController) importLegacy(w http.ResponseWriter, r *http.Request) {
	var in claoloop.LegacyImportRequest
	if err := decodeJSONStrict(r, &in); err != nil {
		c.fail(w, r, 400, "Invalid import JSON")
		return
	}
	svc, ok := c.Svc.(interface {
		ImportLegacy(context.Context, claoloop.LegacyImportRequest) (claoloop.LegacyCatalog, error)
	})
	if !ok {
		c.fail(w, r, 503, "Legacy import unavailable")
		return
	}
	v, err := svc.ImportLegacy(r.Context(), in)
	if err != nil {
		c.fail(w, r, 400, err.Error())
		return
	}
	envelope.WriteJSON(w, 200, v)
}
