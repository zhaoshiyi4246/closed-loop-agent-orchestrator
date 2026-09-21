package claoloop

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/aoagents/agent-orchestrator/backend/internal/domain"
)

type uncertainConnectionStore struct {
	Store
	legacyStore
	failRead   bool
	failCommit bool
}

func (s *uncertainConnectionStore) ListCLAOImports(ctx context.Context) ([]domain.CLAOImportRecord, error) {
	if s.failRead {
		return nil, errors.New("injected read failure")
	}
	return s.legacyStore.ListCLAOImports(ctx)
}
func (s *uncertainConnectionStore) ImportCLAORecords(ctx context.Context, rows []domain.CLAOImportRecord) error {
	if err := s.legacyStore.ImportCLAORecords(ctx, rows); err != nil {
		return err
	}
	if s.failCommit {
		return errors.New("injected lost commit acknowledgement")
	}
	return nil
}

func TestConnectionUnconfirmedWriteReconcilesSameIdentity(t *testing.T) {
	for _, failure := range []string{"read", "commit"} {
		t.Run(failure, func(t *testing.T) {
			svc, core := legacyService(t)
			st := &uncertainConnectionStore{Store: svc.store, legacyStore: svc.store.(legacyStore), failRead: failure == "read", failCommit: failure == "commit"}
			svc.store = st
			id := "native-0123456789abcdef0123456789abcdef"
			record := connectionRecord(id, "bigmodel_general")
			core.response = LegacyResponse{OK: true, Rows: []LegacyItem{{ID: id, Kind: "connection", Document: json.RawMessage(record.Document)}}}
			in := ConnectionRequest{ID: "01234567-89ab-cdef-0123-456789abcdef", Name: "same name", Service: "bigmodel_general", Model: "saved-model"}
			if _, err := svc.CreateConnection(context.Background(), in); !errors.Is(err, ErrConnectionSaveUnconfirmed) {
				t.Fatalf("unconfirmed write classified as %v", err)
			}
			st.failRead, st.failCommit = false, false
			out, err := svc.CreateConnection(context.Background(), in)
			if err != nil || out.Connection.ID != id || len(out.Connection.Profile) != 0 {
				t.Fatalf("reconcile: %#v %v", out, err)
			}
			rows, err := st.ListCLAOImports(context.Background())
			if err != nil || len(rows) != 1 {
				t.Fatalf("duplicate records: %d %v", len(rows), err)
			}
			changed := connectionRecord(id, "moonshot_cn")
			core.response.Rows[0].Document = json.RawMessage(changed.Document)
			in.Service = "moonshot_cn"
			if _, err := svc.CreateConnection(context.Background(), in); !errors.Is(err, domain.ErrCLAOImportConflict) {
				t.Fatalf("immutable conflict classified as %v", err)
			}
		})
	}
}
