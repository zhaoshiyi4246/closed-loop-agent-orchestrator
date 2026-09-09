package domain

// CLAOMissionRecord is acceptance state, separate from the native Session's
// runtime facts. Document contains the versioned, frozen contract and evidence.
type CLAOMissionRecord struct {
	ID string
	ProjectID ProjectID
	State string
	Revision int64
	Document string
	UpdatedAt string
}
