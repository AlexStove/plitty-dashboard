<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# tests

## Purpose
Pytest unit tests for the shared, deterministic backend behavior in `modules/` — specifically the in-memory job tracker, atomic JSON persistence, and API request validation. Media/rendering and external-integration code is not unit-tested here (it needs `ffmpeg` and external keys); those are exercised manually through the bot/API.

## Key Files
| File | Description |
|------|-------------|
| `test_job_tracker.py` | Job lifecycle / state transitions for `modules/job_tracker.py`. |
| `test_json_index.py` | Atomic load/save behavior of `modules/json_index.py`. |
| `test_validation.py` | Pydantic request-model validation from `modules/validation.py`. |

## Subdirectories
None.

## For AI Agents

### Working In This Directory
- Mirror the `test_<module>.py` naming when adding tests for a `modules/` file.
- Keep tests hermetic: no network, no `ffmpeg`, no real external services. Use temp dirs for anything that touches the filesystem (the json-index tests are the model to follow).
- When you change a repository's read/write surface or a validation model, update or add the corresponding test here.

### Testing Requirements
- Run from the repo root: `pytest` (configuration lives in the root `pyproject.toml`).

### Common Patterns
- Plain pytest functions; filesystem isolation via temp directories; assert on observable state transitions and validation errors.

## Dependencies

### Internal
- Imports directly from `modules/` (`job_tracker`, `json_index`, `validation`).

### External
- pytest; pydantic (transitively, via the validation module).

<!-- MANUAL: -->
