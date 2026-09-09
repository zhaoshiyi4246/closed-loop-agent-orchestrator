-- name: InsertCLAOMission :exec
INSERT INTO clao_missions(id, project_id, state, revision, document, updated_at) VALUES (?, ?, ?, ?, ?, ?);

-- name: GetCLAOMission :one
SELECT * FROM clao_missions WHERE id = ?;

-- name: ListCLAOMissions :many
SELECT * FROM clao_missions ORDER BY updated_at DESC;

-- name: UpdateCLAOMission :execrows
UPDATE clao_missions SET state = ?, revision = revision + 1, document = ?, updated_at = ? WHERE id = ? AND revision = ?;
