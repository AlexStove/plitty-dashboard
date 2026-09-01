<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# modules

## Purpose
The core business logic of agentMUSIC. A flat Python package (no nested subpackages) grouping cross-cutting infrastructure (config, errors, validation, logging), file-backed repositories, audio/chorus analysis, scenario-specific video renderers ("bundles"), media integrations (Spotify, stock footage), and the background generation worker. `bot.py` and `api_server.py` are thin entry points; the real work lives here.

## Key Files

### Infrastructure & data
| File | Description |
|------|-------------|
| `__init__.py` | Empty package marker (no barrel exports — import modules directly). |
| `config.py` | Frozen `Settings` dataclass loaded from environment; the single source of truth for secrets/host/ports/keys. |
| `types.py` | Shared dataclasses: `WordTiming`, `LyricsLine`. |
| `errors.py` | FastAPI exception handlers; standardizes the `{"error", "message"}` response shape. |
| `validation.py` | Pydantic request models (`MinioImportRequest`, `SpotifyImportRequest`, `GenerateRequest`, scenario/orientation enums). |
| `utils.py` | Misc helpers (ffmpeg availability checks, etc.). |
| `logging_config.py` | Centralized logging setup; module loggers use `__name__`. |

### Repositories (file-backed JSON)
| File | Description |
|------|-------------|
| `json_index.py` | Atomic JSON list persistence (temp file + `os.replace`). All repos build on this. |
| `track_db.py` | Track metadata + mp3 storage under `output/<user_id>/_tracks/`. |
| `chorus_db.py` | Chorus variants (audio + serialized `LyricsLine`) under `_choruses/`; `cleanup_old()`. |
| `video_db.py` | Generated-video metadata under `_videos/`; `cleanup_old()`. |
| `job_tracker.py` | Thread-safe in-memory `JobTracker` singleton with `Job` dataclass and eased progress. |

### Audio & chorus analysis
| File | Description |
|------|-------------|
| `whisper_transcriber.py` | `faster-whisper` (large-v3) word-level transcription → `LyricsLine[]`. |
| `chorus_extractor.py` | librosa structural analysis (chroma/RMS/recurrence) → `ChorusSegment`. |
| `dual_chorus.py` | Combines audio-based + Claude text-based chorus detection; dedupes overlaps → `ChorusVariant`. |
| `claude_agent.py` | Anthropic Claude calls for chorus trigger / metadata. |
| `audio_fingerprint.py` | Track dedup via fingerprinting. |
| `bpm_analyzer.py` | BPM detection for rhythm sync. |
| `viral_segment_picker.py` | Picks high-energy segments for viral appeal. |

### Video bundles (scenario renderers) & effects
| File | Description |
|------|-------------|
| `bundle1_karaoke.py` | Karaoke video (animated or footage background). |
| `bundle_slideshow.py` | Image slideshow synced to chorus audio. |
| `bundle_track_promo.py` | Full track promo video with effects. |
| `bundle_cover_alive.py` | Animated album-cover video. |
| `bundle_pov_spotify.py` | Spotify-themed POV format. |
| `animated_bg.py` | Procedural animated backgrounds (gradients/particles). |
| `cta_overlay.py` | Call-to-action text overlay rendering. |
| `light_leaks.py` | Light-leak effect compositing. |
| `styles.py` | Preset style definitions. |
| `video_validator.py` | Post-render validation (codec/bitrate/dimensions). |

### Integrations & worker
| File | Description |
|------|-------------|
| `spotify_loader.py` | spotDL track download + metadata parsing. |
| `spotify_cover_fetcher.py` | Album cover fetch from Spotify API; local cache. |
| `footage_searcher.py` | Pixabay/Pexels footage search + download/cache. |
| `api_worker.py` | Background generation queue: `enqueue_job()` + `worker_loop()`; orchestrates metadata, style, and the right bundle per scenario. |

## Subdirectories
None — `modules/` is a flat package.

## For AI Agents

### Working In This Directory
- Scenario routing lives in `api_worker.py`; each scenario maps to one `bundle_*` renderer. Adding a scenario means: a new `bundle_*` module, a branch in the worker, and a matching value in `validation.py` enums and `web/src/types.ts` (`Scenario`).
- Repositories are intentionally function-based (`save_*`, `list_user_*`, `get_*`, `delete_*`) so storage can later swap from JSON to a DB (see `docs/adr/ADR-002`). Keep that read/write surface stable.
- Never write JSON indexes directly — always go through `json_index.py` for atomicity.
- Read secrets/paths from `config.py` (env) and tunables from `config.yaml`; don't introduce new hardcoded constants for either.

### Testing Requirements
- Covered by `tests/` (job tracker, json index, validation). Run `pytest` from the repo root.
- Media-heavy modules (bundles, transcriber, footage) require `ffmpeg`/`ffprobe` and external keys; test these manually via the bot/API rather than in unit tests.

### Common Patterns
- snake_case modules with domain prefixes (`bundle_*`, `*_db`, `*_fetcher`). Type hints throughout; dataclasses for structured data.
- Module-level logger via `logging_config` and `__name__`.
- No circular imports; modules couple via plain function calls.

## Dependencies

### Internal
- `bot.py` and `api_server.py` call into these modules.
- `api_worker.py` is the hub: depends on the repos, `job_tracker`, `dual_chorus`/`chorus_extractor`, the `bundle_*` renderers, `spotify_cover_fetcher`, and `footage_searcher`.

### External
- librosa, soundfile, faster-whisper, Pillow, anthropic, spotdl, yt-dlp, requests; `ffmpeg`/`ffprobe` at the system level.

<!-- MANUAL: -->
