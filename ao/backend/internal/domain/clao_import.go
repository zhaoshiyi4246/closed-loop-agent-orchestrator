package domain

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
