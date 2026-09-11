-- +goose Up
CREATE TABLE clao_imports (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('history', 'connection', 'configuration')),
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    auth_revision INTEGER NOT NULL DEFAULT 0,
    auth_pending INTEGER NOT NULL DEFAULT 0
);

-- +goose Down
DROP TABLE clao_imports;
