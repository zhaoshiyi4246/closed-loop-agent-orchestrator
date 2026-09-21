package claoloop

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type LocalProjectRequest struct {
	Path   string `json:"path"`
	Name   string `json:"name"`
	Create bool   `json:"create"`
}
type LocalProject struct {
	ID   string `json:"id"`
	Path string `json:"path"`
	Name string `json:"name"`
}

func (s *Service) OpenProject(ctx context.Context, in LocalProjectRequest) (LocalProject, error) {
	if !filepath.IsAbs(in.Path) || strings.ContainsAny(in.Path, "\x00\r\n") || strings.HasPrefix(in.Path, `\\`) || strings.TrimSpace(in.Name) == "" || len(in.Name) > 160 {
		return LocalProject{}, errors.New("请填写本机绝对目录和项目名称")
	}
	path := filepath.Clean(in.Path)
	if in.Create {
		if err := os.Mkdir(path, 0700); err != nil && !os.IsExist(err) {
			return LocalProject{}, errors.New("无法创建项目目录")
		}
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return LocalProject{}, errors.New("项目目录不存在或不可读取")
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return LocalProject{}, errors.New("请选择项目目录")
	}
	writer, ok := s.store.(interface {
		ListProjects(context.Context) ([]domain.ProjectRecord, error)
		UpsertProject(context.Context, domain.ProjectRecord) error
	})
	if !ok {
		return LocalProject{}, errors.New("原生项目登记不可用")
	}
	rows, err := writer.ListProjects(ctx)
	if err != nil {
		return LocalProject{}, err
	}
	for _, r := range rows {
		if strings.EqualFold(filepath.Clean(r.Path), resolved) {
			return LocalProject{r.ID, r.Path, r.DisplayName}, nil
		}
	}
	id := fmt.Sprintf("clao-local-%x", sha256.Sum256([]byte(strings.ToLower(resolved))))[:27]
	if _, exists, err := s.store.GetProject(ctx, id); err != nil {
		return LocalProject{}, err
	} else if exists {
		return LocalProject{}, errors.New("项目身份已存在，不覆盖原记录")
	}
	// Scratch is the native plain-directory shape; CLAO alone snapshots it and
	// supplies an explicit private Git source to native workspace creation.
	row := domain.ProjectRecord{ID: id, Path: resolved, DisplayName: strings.TrimSpace(in.Name), RegisteredAt: time.Now(), Kind: domain.ProjectKindScratch}
	if err := writer.UpsertProject(ctx, row); err != nil {
		return LocalProject{}, err
	}
	return LocalProject{id, resolved, row.DisplayName}, nil
}
