# agentMUSIC

agentMUSIC is a modular monolith for turning music tracks into short-form video content. It combines a Telegram bot, a FastAPI HTTP API, a React dashboard, local media processing, and optional external integrations for Spotify, Anthropic, stock footage, and MinIO/S3 storage.

The product flow is:

```txt
Upload or import track
-> transcribe audio
-> extract chorus variants
-> generate karaoke / streamer video
-> save media metadata
-> expose status and downloads through API/dashboard
```

## What It Does

- Accepts tracks through Telegram, dashboard upload, Spotify import, or MinIO import.
- Transcribes tracks and extracts chorus segments.
- Generates vertical or horizontal short videos.
- Supports karaoke, animated background, footage-based, and streamer-style scenarios.
- Tracks background jobs through an in-memory job tracker.
- Stores generated media metadata in file-backed JSON indexes.
- Serves a production dashboard from `static/`.

## Architecture

The project is intentionally kept as a modular monolith. One deployable process is simpler to operate, while shared concerns are separated into reusable modules.

```txt
bot.py              Telegram conversation entry point and bot lifecycle
api_server.py       FastAPI API, dashboard serving, Swagger/OpenAPI
modules/
  api_worker.py     Background generation queue worker
  *_db.py           File-backed repositories for tracks, choruses, videos
  config.py         Environment-driven settings
  errors.py         Shared API error format
  validation.py     API request validation models
  json_index.py     Atomic JSON index persistence
web/                Vite + React dashboard source
static/             Built dashboard served by FastAPI
tests/              Unit tests for shared backend behavior
docs/openapi.json   Exported Swagger/OpenAPI schema
docs/adr/           Architecture decision records
```

The next major backend cleanup should split `api_server.py` into domain routers: `jobs`, `tracks`, `choruses`, `videos`, `generation`, and `dashboard`.

## Requirements

- Python 3.11
- Node.js 22.22.2
- npm 10.9+
- `ffmpeg` and `ffprobe`
- Telegram bot token

Optional integrations:

- Anthropic API key for smarter chorus/search metadata.
- Spotify credentials for spotDL.
- Pixabay/Pexels API keys for footage search.
- MinIO/S3-compatible storage.

Node is pinned with `.node-version` and `.nvmrc`.

## Environment

Copy `.env.example` to `.env` for local backend development. Keep real secrets out of Git.

Important backend variables:

```txt
TELEGRAM_BOT_TOKEN
ANTHROPIC_API_KEY
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
PIXABAY_API_KEY
PEXELS_API_KEY
APP_ENV
LOG_LEVEL
OUTPUT_DIR
API_HOST
API_PORT
API_CORS_ORIGINS
AGENTMUSIC_OWNER_ID
YT_DLP_UPGRADE_URL
MINIO_URL
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
MINIO_BUCKET
MINIO_TRACKS_BUCKET
```

Dashboard build/dev variables live in `web/.env`. Start from `web/.env.example`.

```txt
VITE_DEV_SERVER_PORT
VITE_API_PROXY_TARGET
VITE_MINIO_TRACKS_BUCKET
```

## Run Locally

Backend and bot:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

The bot starts the FastAPI server in a background thread. The API listens on `API_HOST:API_PORT`.

Dashboard development server:

```bash
cd web
npm ci
npm run dev
```

Production dashboard build:

```bash
cd web
npm ci
npm run build
```

The build output is written to `static/` and served by FastAPI at `/dashboard`.

## API And Swagger

When the API is running:

- Health check: `GET /health`
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- OpenAPI JSON: `GET /openapi.json`
- Checked-in OpenAPI schema: [docs/openapi.json](docs/openapi.json)

Regenerate the checked-in schema after API changes:

```bash
python3 scripts/export_openapi.py
```

Main API groups:

```txt
Jobs       /api/jobs, /api/jobs/{job_id}, /api/jobs/{job_id}/stop
Tracks     /api/tracks, /api/tracks/upload, /api/tracks/spotify, /api/tracks/minio
Choruses   /api/choruses, /api/choruses/{chorus_id}/audio
Generation /api/generate
Videos     /api/videos, /api/videos/{video_id}, /api/videos/{video_id}/file
Stats      /api/stats
Live       /api/events
Dashboard  /dashboard
```

The public Swagger schema intentionally excludes service/UI-only routes:

```txt
/dashboard
/api/events
/api/tracks/spotify/job/{job_id}
```

Use `/api/jobs/{job_id}` as the public job-status endpoint.

Errors use a stable JSON shape:

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid request payload."
}
```

API input is validated with Pydantic models in `modules/validation.py`. Add new request models there before adding new endpoints.

## Data Storage

The app currently stores media files and metadata under `OUTPUT_DIR/<user_id>/`.

```txt
_tracks/index.json
_choruses/index.json
_videos/index.json
```

Index writes go through `modules/json_index.py` and are atomic. This protects against partially written JSON when a process is interrupted.

Generated media, `.env` files, private keys, and local dependency folders must not be committed.

## Tests And Checks

Backend:

```bash
pytest
python3 -m py_compile api_server.py bot.py modules/config.py
```

Frontend:

```bash
cd web
npm ci
npm run build
npm audit --audit-level=moderate
```

CI runs backend tests and frontend build on pushes and pull requests.

## Deployment Notes

- Set `APP_ENV=production`.
- Set `API_CORS_ORIGINS` to explicit origins instead of `*`.
- Mount persistent storage for `OUTPUT_DIR`.
- Back up `OUTPUT_DIR` and test restore.
- Configure logs collection and error alerts.
- Run database/storage migrations manually only after documenting them.
- Run `pytest`, `npm run build`, and `npm audit --audit-level=moderate` before deploy.

## Architecture Decisions

See:

- [ADR-001: Modular monolith](docs/adr/ADR-001-modular-monolith.md)
- [ADR-002: File-backed repositories](docs/adr/ADR-002-file-backed-repositories.md)
