<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# scripts

## Purpose
One-off developer/build utility scripts run by hand (not part of the running service). They generate the checked-in OpenAPI schema and prepare static assets for the POV-Spotify video scenario.

## Key Files
| File | Description |
|------|-------------|
| `export_openapi.py` | Imports the FastAPI app and writes the schema to `docs/openapi.json`. Run after any API change. |
| `generate_pov_spotify_frame.py` | Generates the POV-Spotify frame/overlay PNG assets used by `modules/bundle_pov_spotify.py`. |
| `prepare_pov_spotify_mockup.py` | Prepares the source mockup imagery for the POV-Spotify scenario. |

## Subdirectories
None.

## For AI Agents

### Working In This Directory
- These are manual scripts; run them from the repo root so relative paths and imports resolve (e.g. `python3 scripts/export_openapi.py`).
- `export_openapi.py` is the canonical way to refresh `docs/openapi.json` — keep it in sync with `api_server.py` rather than editing the JSON by hand.
- The POV-Spotify scripts produce binary assets (PNGs) consumed at render time; regenerate them when the POV-Spotify layout changes, then commit the resulting assets.

### Testing Requirements
- No automated tests. Validate by running the script and inspecting its output (the JSON schema, or the generated PNGs).

### Common Patterns
- Standalone `python3 scripts/<name>.py` invocations; side effects write into `docs/` or asset directories.

## Dependencies

### Internal
- `export_openapi.py` imports the FastAPI app from `api_server.py`; the POV scripts target `modules/bundle_pov_spotify.py` assets.

### External
- Pillow (image generation); FastAPI (schema export).

<!-- MANUAL: -->
