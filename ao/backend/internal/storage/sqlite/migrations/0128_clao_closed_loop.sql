-- +goose Up
-- CLAO acceptance facts share AO's database; Session/runtime facts remain in sessions.
CREATE TABLE clao_missions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    state TEXT NOT NULL,
    revision INTEGER NOT NULL,
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE sessions ADD COLUMN clao_mission_id TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX sessions_clao_mission ON sessions(clao_mission_id) WHERE clao_mission_id != '';

-- +goose Down
DROP INDEX sessions_clao_mission;
ALTER TABLE sessions DROP COLUMN clao_mission_id;
DROP TABLE clao_missions;
