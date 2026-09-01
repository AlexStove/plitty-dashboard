"""
HTTP API для интеграции с atome-studio.

Эндпоинты:
  GET  /health                — проверка статуса
  GET  /api/jobs              — список всех задач
  GET  /api/jobs/:id          — статус задачи
  POST /api/jobs/:id/stop     — остановка задачи
  POST /api/generate          — запуск генерации
  GET  /api/tracks            — список треков всех пользователей
  GET  /api/choruses          — список припевов всех пользователей
  POST /api/tracks/spotify    — загрузка трека по Spotify-ссылке
  GET  /api/stats             — статистика бота

Запускается параллельно с Telegram-ботом через uvicorn.
"""

import os
import time
from pathlib import Path

import asyncio
import json

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(override=False)

from modules.job_tracker import tracker
from modules.api_worker import enqueue_job
from modules import job_store, video_db, track_db, chorus_db
from modules.auth import log_startup_posture, require_api_key
from modules.config import settings
from modules.errors import register_exception_handlers
from modules.validation import (
    GenerateRequest,
    MinioBatchImportRequest,
    MinioImportRequest,
    Orientation,
    SpotifyImportRequest,
    SubmitVideoRequest,
)

import logging
logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Проверка",
        "description": "Проверка состояния сервиса и быстрые операционные метрики.",
    },
    {
        "name": "Задачи",
        "description": "Просмотр, контроль и остановка фоновых задач генерации.",
    },
    {
        "name": "Треки",
        "description": "Загрузка, импорт и обработка музыкальных треков.",
    },
    {
        "name": "MinIO",
        "description": "Импорт аудиотреков из S3/MinIO-хранилища.",
    },
    {
        "name": "Припевы",
        "description": "Список, метаданные и аудио извлечённых припевов.",
    },
    {
        "name": "Генерация",
        "description": "Постановка задач на создание коротких музыкальных видео.",
    },
    {
        "name": "Видео",
        "description": "Просмотр готовых видео, метаданных и файлов для скачивания.",
    },
]

app = FastAPI(
    title="agentMUSIC API",
    version="1.0.0",
    description="API для загрузки музыки, извлечения припевов и генерации коротких видео.",
    debug=settings.debug,
    openapi_tags=OPENAPI_TAGS,
)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.api_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = time.time()

OWNER_ID = settings.owner_id  # default user for API-initiated tasks

# Jobs survive restarts: terminal transitions and creations go to the file store.
tracker.set_persist_hook(job_store.persist_job)


@app.on_event("startup")
def _log_auth_posture():
    log_startup_posture()


def _output_base() -> str:
    return settings.output_dir


@app.get("/health", tags=["Проверка"], summary="Проверить состояние сервиса")
def health():
    return {
        "status": "ok",
        "service": "agentmusic",
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/api/jobs", tags=["Задачи"], summary="Получить список задач")
def list_jobs():
    return [j.to_dict() for j in tracker.list_all()]


@app.get(
    "/api/jobs/{job_id}",
    tags=["Задачи"],
    summary="Получить статус задачи",
    dependencies=[Depends(require_api_key)],
)
def get_job(job_id: str):
    job = tracker.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post(
    "/api/jobs/{job_id}/stop",
    tags=["Задачи"],
    summary="Остановить задачу",
    dependencies=[Depends(require_api_key)],
)
def stop_job(job_id: str):
    job = tracker.stop(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or not running")
    return {"ok": True, "job_id": job_id}


# ── MinIO треки (база треков) ───────────────────────────────────────────────

def _get_minio_client():
    from modules.minio_client import build_minio_client
    return build_minio_client()


# Хранилище статусов обработки (в памяти, сбрасывается при рестарте)
_processed_tracks: set = set()


@app.get(
    "/api/tracks/minio",
    tags=["MinIO"],
    summary="Получить список треков из MinIO",
    dependencies=[Depends(require_api_key)],
)
def list_minio_tracks():
    """Список треков из настроенного MinIO tracks bucket."""
    client = _get_minio_client()
    if not client:
        raise HTTPException(status_code=503, detail="MinIO not configured")

    bucket = settings.minio_tracks_bucket
    try:
        objects = client.list_objects(bucket, recursive=True)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MinIO error: {e}")

    tracks = []
    audio_exts = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma")
    for obj in objects:
        key = obj.object_name
        if not key or not any(key.lower().endswith(ext) for ext in audio_exts):
            continue

        parts = key.split("/")
        artist = parts[0] if len(parts) > 1 else "Unknown"
        filename = parts[-1]
        title = Path(filename).stem

        tracks.append({
            "key": key,
            "artist": artist,
            "title": title,
            "size_bytes": obj.size or 0,
            "last_modified": obj.last_modified.isoformat() if obj.last_modified else "",
            "processed": key in _processed_tracks,
        })

    tracks.sort(key=lambda t: (t["artist"], t["title"]))
    return tracks


@app.post(
    "/api/tracks/minio/import",
    tags=["MinIO"],
    summary="Импортировать один трек из MinIO",
    dependencies=[Depends(require_api_key)],
)
def import_minio_track(body: MinioImportRequest):
    """Импортирует трек из MinIO, транскрибирует и извлекает припевы."""
    key = body.key
    client = _get_minio_client()
    if not client:
        raise HTTPException(status_code=503, detail="MinIO not configured")

    # Скачиваем трек из MinIO
    import tempfile
    bucket = settings.minio_tracks_bucket
    parts = key.split("/")
    artist = parts[0] if len(parts) > 1 else ""
    title = Path(parts[-1]).stem
    suffix = Path(parts[-1]).suffix or ".mp3"

    tmp_path = tempfile.mktemp(suffix=suffix)
    try:
        client.fget_object(bucket, key, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Track not found in MinIO: {e}")

    # Сохраняем в track_db
    try:
        from modules.utils import get_media_duration
        duration = get_media_duration(tmp_path)
    except Exception:
        duration = 0.0

    record = track_db.save_track(
        output_base=_output_base(),
        user_id=OWNER_ID,
        src_path=tmp_path,
        source="minio",
        artist=artist,
        title=title,
        duration=duration,
    )
    os.unlink(tmp_path)

    # Транскрипция + припевы
    track_path = record["path"]
    track_id = record["id"]

    try:
        from modules.whisper_transcriber import transcribe_with_timings
        segments = transcribe_with_timings(track_path)
    except Exception as e:
        _processed_tracks.add(key)
        return {"track": record, "choruses": [], "error": f"Transcription failed: {e}"}

    choruses_saved = []
    if segments:
        try:
            import uuid as _uuid
            from modules.dual_chorus import extract_two_choruses
            output_dir = Path(_output_base())
            session_dir = os.path.join(str(output_dir), str(OWNER_ID), _uuid.uuid4().hex[:8])
            os.makedirs(session_dir, exist_ok=True)
            variants_dir = os.path.join(session_dir, "chorus_variants")

            variants = extract_two_choruses(
                track_path, segments, variants_dir, settings.anthropic_api_key,
                min_duration=15, max_duration=30,
            )
            for v in variants:
                saved = chorus_db.save_chorus(
                    output_base=str(output_dir),
                    user_id=OWNER_ID,
                    src_chorus_path=v.audio_path,
                    track_id=track_id,
                    name=f"{artist} - {title} ({v.label})" if artist else f"{title} ({v.label})",
                    lyrics_lines=v.lyrics,
                    variant=v.variant_type if hasattr(v, "variant_type") else "auto",
                    start=v.start,
                    end=v.end,
                    is_preview=record.get("is_preview", False),
                )
                choruses_saved.append(saved)
        except Exception as e:
            logger.error(f"Chorus extraction failed for {key}: {e}")

    _processed_tracks.add(key)
    return {"track": record, "choruses": choruses_saved, "count": len(choruses_saved)}


@app.post(
    "/api/tracks/minio/import-batch",
    tags=["MinIO"],
    summary="Импортировать несколько треков из MinIO",
    dependencies=[Depends(require_api_key)],
)
def import_minio_batch(body: MinioBatchImportRequest):
    """Массовый импорт + обработка треков из MinIO."""
    keys = body.keys
    results = []
    for key in keys:
        try:
            result = import_minio_track(MinioImportRequest(key=key))
            results.append({"key": key, "status": "ok", "choruses": result.get("count", 0)})
        except Exception as e:
            results.append({"key": key, "status": "error", "error": str(e)})

    return {"results": results, "total": len(results), "success": sum(1 for r in results if r["status"] == "ok")}


# ── Треки ──────────────────────────────────────────────────────────────────

@app.get("/api/tracks", tags=["Треки"], summary="Получить список треков")
def list_tracks():
    """Список всех треков всех пользователей."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        return []
    results = []
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        for t in track_db.list_user_tracks(str(output_dir), uid):
            t["user_id"] = uid
            results.append(t)
    results.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return results


@app.post(
    "/api/tracks/upload",
    tags=["Треки"],
    summary="Загрузить аудиофайл",
    dependencies=[Depends(require_api_key)],
)
async def upload_track(file: UploadFile = File(...)):
    """Загрузка аудиофайла через API."""
    import tempfile
    import shutil

    suffix = Path(file.filename or "track.mp3").suffix or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        from modules.utils import get_media_duration
        duration = get_media_duration(tmp_path)
    except Exception:
        duration = 0.0

    record = track_db.save_track(
        output_base=_output_base(),
        user_id=OWNER_ID,
        src_path=tmp_path,
        source="api_upload",
        title=Path(file.filename or "").stem,
        duration=duration,
    )
    os.unlink(tmp_path)
    return record


def _spotify_download_worker(job_id: str, url: str, source: str = "auto"):
    """Скачивание + автоматическая транскрипция + извлечение припева."""
    import tempfile
    import shutil
    try:
        tracker.update(
            job_id,
            current_phase="downloading",
            current_message="Ищу и скачиваю треки...",
        )

        from modules.spotify_loader import download_artist_tracks

        tmp_dir = tempfile.mkdtemp()
        try:
            tracks = download_artist_tracks(url, tmp_dir, max_tracks=5, source=source)
        except Exception as e:
            tracker.fail(job_id, str(e))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        results = []
        for idx, dt in enumerate(tracks, start=1):
            record = track_db.save_track(
                output_base=_output_base(),
                user_id=OWNER_ID,
                src_path=dt.path,
                source="spotify",
                artist=dt.artist,
                title=dt.title or Path(dt.path).stem,
                duration=dt.duration,
                spotify_url=url,
                is_preview=dt.is_preview,
            )

            # Автоматически транскрибируем + извлекаем припев.
            # Клиент получит трек уже с готовым chorus.
            tracker.update(
                job_id,
                current_phase="processing",
                current_message=(
                    f"[{idx}/{len(tracks)}] Обрабатываю: "
                    f"{dt.artist} — {dt.title}"
                    + (" (превью)" if dt.is_preview else "")
                ),
            )
            try:
                proc_result = process_track(record["id"])
                record["choruses"] = proc_result.get("choruses", [])
            except HTTPException as e:
                logger.warning(f"process failed for {record['id']}: {e.detail}")
                record["process_error"] = str(e.detail)
            except Exception as e:
                logger.warning(f"process exception for {record['id']}: {e}")
                record["process_error"] = str(e)

            results.append(record)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        tracker.complete(job_id, results=results)
    except Exception as e:
        tracker.fail(job_id, str(e))


@app.post(
    "/api/tracks/spotify",
    tags=["Треки"],
    summary="Импортировать треки из Spotify",
    dependencies=[Depends(require_api_key)],
)
def spotify_download_start(body: SpotifyImportRequest):
    """Async-загрузка Spotify — возвращает job_id сразу, клиент опрашивает /job/{id}."""
    url = body.url

    try:
        from modules.spotify_loader import download_artist_tracks  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=500, detail="spotify_loader not available")

    job = tracker.create(
        user_id=OWNER_ID,
        scenario="spotify_download",
        track_name=f"Spotify: {url[:60]}",
        total=1,
    )

    import threading
    threading.Thread(
        target=_spotify_download_worker,
        args=(job.job_id, url, body.source),
        daemon=True,
    ).start()

    return {"job_id": job.job_id, "status": "pending"}


@app.get("/api/tracks/spotify/job/{job_id}", include_in_schema=False)
def spotify_job_status(job_id: str):
    """Статус async-загрузки Spotify: pending / running / done / error."""
    job = tracker.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    d = job.to_dict()
    # Алиасим status для фронта: running -> pending в начале, done / error остаются
    if d.get("status") == "running":
        d["status"] = "pending" if d.get("current_phase") == "queued" else "running"
    # Треки — в поле results
    d["tracks"] = d.get("results") or []
    d["count"] = len(d["tracks"])
    return d


@app.post(
    "/api/tracks/{track_id}/process",
    tags=["Треки"],
    summary="Обработать трек и извлечь припевы",
    dependencies=[Depends(require_api_key)],
)
def process_track(track_id: str):
    """Транскрипция + извлечение припевов для трека."""
    import functools
    import uuid

    # Ищем трек
    track = None
    output_dir = Path(_output_base())
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        t = track_db.get_track(str(output_dir), uid, track_id)
        if t:
            track = t
            track["user_id"] = uid
            break

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    track_path = track["path"]
    if not os.path.exists(track_path):
        raise HTTPException(status_code=404, detail="Track file missing")

    user_id = track["user_id"]

    # 1. Транскрипция
    try:
        from modules.whisper_transcriber import transcribe_with_timings
        segments = transcribe_with_timings(track_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not segments:
        raise HTTPException(status_code=422, detail="Could not transcribe track")

    # 2. Извлечение припевов
    try:
        from modules.dual_chorus import extract_two_choruses
        session_dir = os.path.join(str(output_dir), str(user_id), uuid.uuid4().hex[:8])
        os.makedirs(session_dir, exist_ok=True)
        variants_dir = os.path.join(session_dir, "chorus_variants")

        variants = extract_two_choruses(
            track_path, segments, variants_dir, settings.anthropic_api_key,
            min_duration=15, max_duration=30,
        )
    except Exception as e:
        logger.error(f"Chorus extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chorus extraction failed: {e}")

    if not variants:
        raise HTTPException(status_code=422, detail="Could not extract choruses")

    # 3. Сохраняем в chorus_db
    saved = []
    from modules.whisper_transcriber import segments_to_lyrics_lines
    for v in variants:
        record = chorus_db.save_chorus(
            output_base=str(output_dir),
            user_id=user_id,
            src_chorus_path=v.audio_path,
            track_id=track_id,
            name=v.label,
            lyrics_lines=v.lyrics,
            variant=v.variant_type if hasattr(v, "variant_type") else "auto",
            start=v.start,
            end=v.end,
            is_preview=track.get("is_preview", False),
        )
        record["user_id"] = user_id
        saved.append(record)

    return {"choruses": saved, "count": len(saved)}


# ── Припевы ────────────────────────────────────────────────────────────────

@app.get("/api/choruses", tags=["Припевы"], summary="Получить список припевов")
def list_choruses():
    """Список припевов с артистом и title связанного трека (для UI)."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        return []

    # id трека → {artist, title}
    track_info: dict[str, dict] = {}
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        for t in track_db.list_user_tracks(str(output_dir), uid):
            track_info[t["id"]] = {
                "artist": t.get("artist", ""),
                "title": t.get("title", ""),
            }

    results = []
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        for c in chorus_db.list_user_choruses(str(output_dir), uid):
            c["user_id"] = uid
            ti = track_info.get(c.get("track_id", ""), {})
            c["artist"] = ti.get("artist", "")
            c["track_title"] = ti.get("title", "")
            # name оставляем ОРИГИНАЛЬНЫЙ ("Вариант 1 (аудио-анализ)") —
            # фронт сам собирает ярлык из artist + track_title.
            results.append(c)
    results.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return results


@app.get("/api/choruses/{chorus_id}/audio", tags=["Припевы"], summary="Скачать аудио припева")
def get_chorus_audio(chorus_id: str):
    """Аудиофайл припева для прослушивания."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Chorus not found")
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        c = chorus_db.get_chorus(str(output_dir), uid, chorus_id)
        if c and os.path.exists(c["path"]):
            return FileResponse(c["path"], media_type="audio/mpeg", filename=f"{chorus_id}.mp3")
    raise HTTPException(status_code=404, detail="Chorus audio not found")


# ── Генерация ──────────────────────────────────────────────────────────────

@app.post(
    "/api/generate",
    tags=["Генерация"],
    summary="Запустить генерацию видео",
    dependencies=[Depends(require_api_key)],
)
def generate(body: GenerateRequest | None = None):
    """Создаёт задачу генерации."""
    if not body:
        body = GenerateRequest()
    scenario = body.scenario
    orientation = body.orientation
    bg_type = body.bg_type
    videos_per_account = body.videos_per_account

    topic = body.topic or ""
    if topic:
        try:
            params = json.loads(topic)
            scenario = params.get("scenario", scenario)
            orientation = params.get("orientation", orientation)
            bg_type = params.get("bg_type", bg_type)
        except (json.JSONDecodeError, TypeError):
            pass

    chorus_id = body.chorus_id

    job = tracker.create(
        user_id=OWNER_ID,
        scenario=scenario,
        track_name=f"atome-studio ({scenario})",
        orientation=orientation,
        total=videos_per_account,
    )

    # Ставим в очередь реальной генерации
    enqueue_job(job.job_id, {
        "scenario": scenario,
        "orientation": orientation,
        "bg_type": bg_type,
        "video_count": videos_per_account,
        "chorus_id": chorus_id,
    })

    return job.to_dict()


# ── AF-платформа: one-shot генерация (v1) ─────────────────────────────────

@app.post(
    "/api/v1/videos",
    tags=["Генерация"],
    summary="Принять команду платформы: один трек → одно видео",
    dependencies=[Depends(require_api_key)],
    status_code=202,
)
def submit_video(body: SubmitVideoRequest):
    """Одношаговый submit для AF video-generator адаптера.

    Контракт: ровно один ассет на command_id (идемпотентно). Источник трека —
    один из minio_key | spotify_url | track_id | prompt; импорт, транскрипция
    и рендер выполняются внутри задачи, статус — GET /api/jobs/{job_id}.
    """
    kind, value = body.source
    platform_meta = {
        k: v
        for k, v in {
            "project": body.project,
            "content_type": body.content_type,
            "allowed_platforms": body.allowed_platforms,
            "lang": body.lang,
        }.items()
        if v
    }
    params = {
        "scenario": body.scenario,
        "orientation": body.aspect,
        "bg_type": body.bg_type,
        "video_count": 1,
        "chorus_id": None,
        "source": {"kind": kind, "value": value},
        "platform": platform_meta,
    }

    def _create_job():
        job = tracker.create(
            user_id=OWNER_ID,
            scenario=body.scenario,
            track_name=f"AF {kind}: {value[:60]}",
            orientation=body.aspect,
            total=1,
            command_id=body.command_id,
            params=params,
        )
        enqueue_job(job.job_id, dict(params))
        return job

    job, created = job_store.resolve_or_reserve(body.command_id, _create_job)
    return {
        "job_id": job.job_id,
        "status": job.provider_status,
        "command_id": body.command_id,
        "created": created,
    }


@app.post(
    "/api/footage/prewarm",
    tags=["Генерация"],
    summary="Прогреть кэш футажей (Pixabay/Pexels)",
    dependencies=[Depends(require_api_key)],
)
async def footage_prewarm(orientation: Orientation = "portrait"):
    """Скачивает футажи в кэш заранее, чтобы рендер не ждал их в задаче."""
    import yaml

    from modules.footage_prewarm import footage_keys_configured, prewarm_footage_cache

    if not footage_keys_configured():
        raise HTTPException(
            status_code=503,
            detail="PIXABAY_API_KEY/PEXELS_API_KEY are not configured",
        )
    try:
        with open("config.yaml", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except OSError:
        config = {}
    clips = await prewarm_footage_cache(config, _output_base(), orientation=orientation)
    return {"cached_clips": len(clips), "orientation": orientation}


# ── Видео ─────────────────────────────────────────────────────────────────

@app.get("/api/videos", tags=["Видео"], summary="Получить список готовых видео")
def list_videos():
    """Список всех готовых видео всех пользователей."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        return []
    results = []
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        for v in video_db.list_user_videos(str(output_dir), uid):
            v["user_id"] = uid
            v["download_url"] = f"/api/videos/{v['id']}/file"
            results.append(v)
    results.sort(key=lambda x: x.get("rendered_at", ""), reverse=True)
    return results


@app.get(
    "/api/videos/{video_id}",
    tags=["Видео"],
    summary="Получить метаданные видео",
    dependencies=[Depends(require_api_key)],
)
def get_video(video_id: str):
    """Метаданные одного видео."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        v = video_db.get_video(str(output_dir), uid, video_id)
        if v:
            v["user_id"] = uid
            v["download_url"] = f"/api/videos/{video_id}/file"
            return v
    raise HTTPException(status_code=404, detail="Video not found")


@app.get(
    "/api/videos/{video_id}/file",
    tags=["Видео"],
    summary="Скачать видеофайл",
    dependencies=[Depends(require_api_key)],
)
def get_video_file(video_id: str):
    """Скачивание видеофайла."""
    output_dir = Path(_output_base())
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    for user_dir in output_dir.iterdir():
        if not user_dir.is_dir() or not user_dir.name.isdigit():
            continue
        uid = int(user_dir.name)
        v = video_db.get_video(str(output_dir), uid, video_id)
        if v and os.path.exists(v["path"]):
            return FileResponse(
                v["path"],
                media_type="video/mp4",
                filename=f"{video_id}.mp4",
            )
    raise HTTPException(status_code=404, detail="Video file not found")


# ── Статистика ─────────────────────────────────────────────────────────────

@app.get("/api/stats", tags=["Проверка"], summary="Получить статистику сервиса")
def stats():
    output_dir = Path(_output_base())
    if not output_dir.exists():
        return {
            "users": 0, "tracks": 0, "choruses": 0,
            "videos": 0, "active_jobs": 0, "size_mb": 0,
        }

    user_dirs = [
        d for d in output_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and d.name.isdigit()
    ]
    base = str(output_dir)
    total_tracks = sum(len(track_db.list_user_tracks(base, int(d.name))) for d in user_dirs)
    total_choruses = sum(len(chorus_db.list_user_choruses(base, int(d.name))) for d in user_dirs)
    total_videos = sum(len(video_db.list_user_videos(base, int(d.name), limit=10000)) for d in user_dirs)
    total_size_mb = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file()) / (1024 * 1024)

    return {
        "users": len(user_dirs),
        "tracks": total_tracks,
        "choruses": total_choruses,
        "videos": total_videos,
        "active_jobs": len(tracker.list_active()),
        "size_mb": round(total_size_mb, 1),
    }


# ── Live events (SSE) ─────────────────────────────────────────────────────

def _collect_live_snapshot() -> dict:
    """Build the payload broadcast to SSE subscribers."""
    try:
        jobs_payload = [j.to_dict() for j in tracker.list_all()]
    except Exception:
        jobs_payload = []
    try:
        stats_payload = stats()
    except Exception:
        stats_payload = {}
    return {"stats": stats_payload, "jobs": jobs_payload}


@app.get("/api/events", include_in_schema=False)
async def live_events(request: Request):
    """Server-Sent Events stream: pushes {stats, jobs} every ~2s."""

    async def event_stream():
        last_payload = None
        while True:
            if await request.is_disconnected():
                break
            snapshot = _collect_live_snapshot()
            serialized = json.dumps(snapshot, default=str)
            if serialized != last_payload:
                yield f"data: {serialized}\n\n"
                last_payload = serialized
            else:
                # Keep-alive comment so proxies don't close the connection.
                yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Dashboard ─────────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"
_ASSETS_DIR = _STATIC_DIR / "assets"

if _ASSETS_DIR.exists():
    # Vite build output lives under static/assets/*
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    """Standalone agentMUSIC dashboard (Vite build)."""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(index.read_text(encoding="utf-8"))
