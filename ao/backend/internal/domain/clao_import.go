package domain

import "errors"

var ErrCLAOImportConflict = errors.New("原导入来源已变化，未覆盖已有记录；请保留原记录并明确重新连接")

// CLAOImportRecord is an explicitly imported immutable legacy projection in
// the existing AO database. It never represents an executable native Mission.
type CLAOImportRecord struct {
	ID           string
	Kind         string
	Document     string
	CreatedAt    string
	AuthRevision int
	AuthPending  bool
}
