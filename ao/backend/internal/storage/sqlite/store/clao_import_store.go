package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
)

// Import is atomic, insert-only and independent of runtime mission state. An
// updated source must not silently rewrite an earlier accepted import.
func (s *Store) ImportCLAORecords(ctx context.Context, records []domain.CLAOImportRecord) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	tx, err := s.writeDB.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, r := range records {
		var previous string
		err = tx.QueryRowContext(ctx, "SELECT document FROM clao_imports WHERE id=?", r.ID).Scan(&previous)
		if err == nil {
			if previous != r.Document {
				return fmt.Errorf("原导入来源已变化，未覆盖已有记录；请保留原记录并明确重新连接")
			}
			continue
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if _, err = tx.ExecContext(ctx, "INSERT INTO clao_imports(id,kind,document,created_at) VALUES(?,?,?,?)", r.ID, r.Kind, r.Document, r.CreatedAt); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) ListCLAOImports(ctx context.Context) ([]domain.CLAOImportRecord, error) {
	rows, err := s.readDB.QueryContext(ctx, "SELECT id,kind,document,created_at,auth_revision,auth_pending FROM clao_imports ORDER BY created_at DESC,id")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []domain.CLAOImportRecord{}
	for rows.Next() {
		var r domain.CLAOImportRecord
		if err := rows.Scan(&r.ID, &r.Kind, &r.Document, &r.CreatedAt, &r.AuthRevision, &r.AuthPending); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// Only credential generation metadata changes; the imported source remains immutable.
func (s *Store) UpdateCLAOImportAuth(ctx context.Context, id string, expected int, pending bool) (int, error) {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	next := expected
	if pending {
		next++
	}
	result, err := s.writeDB.ExecContext(ctx, "UPDATE clao_imports SET auth_revision=?,auth_pending=? WHERE id=? AND kind='connection' AND auth_revision=?", next, pending, id, expected)
	if err != nil {
		return expected, err
	}
	n, err := result.RowsAffected()
	if err != nil || n != 1 {
		return expected, errors.New("连接已变化，请重新读取后确认")
	}
	return next, nil
}
