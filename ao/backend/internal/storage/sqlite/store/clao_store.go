package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
	"github.com/aoagents/agent-orchestrator/backend/internal/storage/sqlite/gen"
)

func (s *Store) CreateCLAOMission(ctx context.Context, r domain.CLAOMissionRecord) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	return s.qw.InsertCLAOMission(ctx, gen.InsertCLAOMissionParams{ID: r.ID, ProjectID: string(r.ProjectID), State: r.State, Revision: r.Revision, Document: r.Document, UpdatedAt: r.UpdatedAt})
}
func claoRecord(r gen.ClaoMission) domain.CLAOMissionRecord {
	return domain.CLAOMissionRecord{ID: r.ID, ProjectID: domain.ProjectID(r.ProjectID), State: r.State, Revision: r.Revision, Document: r.Document, UpdatedAt: r.UpdatedAt}
}
func (s *Store) GetCLAOMission(ctx context.Context, id string) (domain.CLAOMissionRecord, bool, error) {
	r, err := s.qr.GetCLAOMission(ctx, id)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.CLAOMissionRecord{}, false, nil
	}
	if err != nil {
		return domain.CLAOMissionRecord{}, false, err
	}
	return claoRecord(r), true, nil
}
func (s *Store) ListCLAOMissions(ctx context.Context) ([]domain.CLAOMissionRecord, error) {
	rs, err := s.qr.ListCLAOMissions(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]domain.CLAOMissionRecord, 0, len(rs))
	for _, r := range rs {
		out = append(out, claoRecord(r))
	}
	return out, nil
}
func (s *Store) SaveCLAOMission(ctx context.Context, r domain.CLAOMissionRecord) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	n, err := s.qw.UpdateCLAOMission(ctx, gen.UpdateCLAOMissionParams{ID: r.ID, Revision: r.Revision, State: r.State, Document: r.Document, UpdatedAt: r.UpdatedAt})
	if err != nil {
		return err
	}
	if n != 1 {
		return fmt.Errorf("closed-loop revision conflict")
	}
	return nil
}
