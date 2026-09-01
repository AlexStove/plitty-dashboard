<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# api

## Purpose
API usage notes for the agentMUSIC HTTP API. This directory is a thin pointer to the authoritative, generated OpenAPI schema rather than a hand-maintained API reference.

## Key Files
| File | Description |
|------|-------------|
| `README.md` | Brief guide to the API; points at the checked-in `docs/openapi.json` and the live Swagger UI (`/docs`) / ReDoc (`/redoc`). |

## Subdirectories
None.

## For AI Agents

### Working In This Directory
- The source of truth for endpoints is `docs/openapi.json` (generated from `api_server.py` via `scripts/export_openapi.py`) and the live `/docs` UI — keep prose here in sync with those, and don't document routes by hand-copying.
- Main API groups: Jobs (`/api/jobs`), Tracks (`/api/tracks`, `/upload`, `/spotify`, `/minio`), Choruses (`/api/choruses`), Generation (`/api/generate`), Videos (`/api/videos`), Stats (`/api/stats`), Live (`/api/events`). Use `/api/jobs/{job_id}` as the public job-status endpoint.

### Testing Requirements
- None — documentation only.

### Common Patterns
- Stable error JSON shape `{ "error": CODE, "message": ... }` (see `modules/errors.py`).

## Dependencies

### Internal
- References `docs/openapi.json` and the API defined in `api_server.py`.

### External
- None.

<!-- MANUAL: -->
