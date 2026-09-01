<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# docs

## Purpose
Project documentation hub: the checked-in OpenAPI/Swagger schema for the HTTP API, architecture decision records (ADRs), and a pointer to API usage. These are reference materials for humans and agents working on the backend contract and architecture.

## Key Files
| File | Description |
|------|-------------|
| `openapi.json` | Checked-in OpenAPI 3 schema for the FastAPI API. Regenerate after API changes with `python3 scripts/export_openapi.py`. Intentionally excludes service/UI-only routes (`/dashboard`, `/api/events`, the Spotify job-status route). |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `adr/` | Architecture Decision Records — why the system is shaped the way it is (see `adr/AGENTS.md`) |
| `api/` | API usage notes pointing at the OpenAPI schema (see `api/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- `openapi.json` is **generated**, not hand-edited. If the API changes, update the FastAPI route definitions and re-run the export script; do not patch the JSON manually.
- When making a non-trivial architectural change, add a new ADR (see existing numbering) rather than rewriting history in an existing one.

### Testing Requirements
- No tests here. Verify `openapi.json` is current by diffing it against a fresh `python3 scripts/export_openapi.py` run.

### Common Patterns
- ADRs are sequentially numbered Markdown files: `ADR-NNN-short-title.md`.

## Dependencies

### Internal
- `openapi.json` is produced from `api_server.py` via `scripts/export_openapi.py`.

### External
- None.

<!-- MANUAL: -->
