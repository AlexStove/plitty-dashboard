"""
Фоновый воркер для API-генерации.

Запускается из бота, мониторит очередь задач от API
и запускает реальный рендер-пайплайн.
"""

import asyncio
import functools
import logging
import os
import random
import uuid
from pathlib import Path

from modules.job_tracker import tracker, Job
from modules.bundle1_karaoke import build_karaoke
from modules.styles import STYLE_PRESETS, DEFAULT_STYLE
from modules.types import LyricsLine, WordTiming
from modules import chorus_db, track_db, video_db
from modules.config import settings

import json as _json
import io


def _deserialize_lyrics(raw: list) -> list[LyricsLine]:
    """Конвертирует dict-формат из chorus_db в LyricsLine dataclass'ы."""
    result = []
    for item in raw or []:
        if isinstance(item, LyricsLine):
            result.append(item)
            continue
        if not isinstance(item, dict):
            continue
        words = [
            WordTiming(word=w.get("word", ""), start=w.get("start", 0.0), end=w.get("end", 0.0))
            for w in item.get("words", [])
            if isinstance(w, dict)
        ]
        result.append(LyricsLine(
            text=item.get("text", ""),
            start=item.get("start", 0.0),
            end=item.get("end", 0.0),
            words=words,
        ))
    return result

logger = logging.getLogger(__name__)

# Очередь задач от API
_queue: asyncio.Queue = None


def _resolve_cover(output_base: str, user_id: int, track_id: str) -> "str | None":
    """
    Возвращает локальный path к обложке трека. Если файл cover_local_path
    пропал с диска — ПЕРЕКАЧИВАЕТ по cover_url из Spotify (как _ensure_cover_local
    в bot.py). Раньше API-путь только проверял локальный файл и при его отсутствии
    отдавал None → cover_alive/pov_spotify падали, хотя cover_url в базе был.
    """
    if not track_id:
        return None
    trk = track_db.get_track(output_base, user_id, track_id)
    if not trk:
        return None
    cp = (trk.get("cover_local_path") or "").strip()
    if cp and not os.path.isabs(cp):
        cp = os.path.abspath(os.path.join(".", cp))
    if cp and os.path.exists(cp) and os.path.getsize(cp) > 1024:
        return cp
    cover_url = (trk.get("cover_url") or "").strip()
    if not cover_url:
        return None
    spotify_id = (trk.get("spotify_track_id") or trk.get("id") or "").strip()
    if not spotify_id:
        return None
    local_path = os.path.join(output_base, str(user_id), "covers", f"{spotify_id}.jpg")
    try:
        from modules.spotify_cover_fetcher import _download_cover
        if _download_cover(cover_url, local_path):
            logger.info(f"cover re-downloaded (api): {local_path}")
            try:
                track_db.update_track(output_base, user_id, trk.get("id"), cover_local_path=local_path)
            except Exception:
                pass
            return local_path
    except Exception as e:
        logger.warning(f"cover re-download failed: {e}")
    return None


def _generate_video_meta(track_name: str, scenario: str) -> dict:
    """Генерирует title, description, hashtags через Claude API."""
    import random

    # Fallback — рандомные варианты без упоминания бота
    fallback_titles = [
        f"Sing along if you know this one",
        f"Put this on repeat",
        f"This track hits different",
        f"{track_name}",
        f"Guess the song from the lyrics",
    ]
    fallback_descs = [
        "Save this before it gets lost. Best karaoke this week.",
        "Do you actually know all the words? Test yourself.",
        "3am vibes. Headphones on. This song.",
        "Drop the next line in the comments.",
    ]
    fallback_tags = ["lyrics", "karaoke", "music", "singalong", "fyp", "foryou",
                     "viral", "hit", "musicvideo", "vibes"]

    if not settings.anthropic_api_key:
        return {
            "title": random.choice(fallback_titles),
            "description": random.choice(fallback_descs),
            "hashtags": random.sample(fallback_tags, 7),
        }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Create a TikTok/Reels post for a music video.\n"
                    f"Track: {track_name}\n"
                    f"Video type: {scenario}\n\n"
                    f"Rules:\n"
                    f"- Do NOT mention any bot, AI, tool, or service name\n"
                    f"- Write as if a real person made this video\n"
                    f"- Title: short, catchy, viral (under 60 chars)\n"
                    f"- Description: 1-2 engaging sentences with call to action\n"
                    f"- Hashtags: 8-12 relevant tags without #, mix English and Russian\n"
                    f"- Style: casual, TikTok-native, emotional\n\n"
                    f"Return ONLY valid JSON: {{\"title\": \"...\", \"description\": \"...\", \"hashtags\": [...]}}"
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        result = _json.loads(text)
        # Убираем упоминания бота/AI из результата на всякий случай
        for field in ["title", "description"]:
            if field in result:
                for word in ["agentmusic", "agentMUSIC", "AI", "бот", "нейросеть", "generated"]:
                    result[field] = result[field].replace(word, "").strip()
        return result
    except Exception as e:
        logger.warning(f"Claude meta generation failed: {e}")
        return {
            "title": random.choice(fallback_titles),
            "description": random.choice(fallback_descs),
            "hashtags": random.sample(fallback_tags, 7),
        }


_minio_client = None

def _get_minio():
    global _minio_client
    if _minio_client is None:
        from modules.minio_client import build_minio_client
        _minio_client = build_minio_client()
    return _minio_client


def _upload_to_minio(file_path: str, key: str, metadata: dict = None):
    """Загружает файл в MinIO через S3 SDK."""
    client = _get_minio()
    if not client:
        logger.debug("MINIO_URL not set, skipping upload")
        return None

    bucket = settings.minio_bucket
    try:
        # Создаём бакет если нет
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        # Загружаем видео
        file_size = os.path.getsize(file_path)
        client.fput_object(bucket, key, file_path, content_type="video/mp4")
        logger.info(f"MinIO upload OK: {key} ({file_size} bytes)")

        # Загружаем JSON-метаданные
        if metadata:
            json_key = key.rsplit(".", 1)[0] + ".json"
            json_data = _json.dumps(metadata, ensure_ascii=False).encode("utf-8")
            client.put_object(bucket, json_key, io.BytesIO(json_data), len(json_data), content_type="application/json")

        return f"{bucket}/{key}"
    except Exception as e:
        logger.error(f"MinIO upload failed: {e}")
        return None


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def enqueue_job(job_id: str, params: dict):
    """Вызывается из API для постановки задачи в очередь."""
    q = get_queue()
    q.put_nowait({"job_id": job_id, **params})
    logger.info(f"API job enqueued: {job_id}")


def reconcile_persisted_jobs() -> int:
    """Восстанавливает задачи из job_store после рестарта.

    Очередь _queue не персистится, поэтому нетерминальные задачи либо
    ставятся в очередь заново (есть params — источник re-runnable; spotify/
    prompt могут ре-резолвиться в другой трек, это допустимо), либо
    помечаются failed/orphaned. Инвариант: ни одна задача не остаётся
    «running» без живого воркера.
    """
    from modules import job_store

    tracker.set_persist_hook(job_store.persist_job)
    restored = 0
    for job in job_store.load_jobs():
        if tracker.get(job.job_id):
            continue
        tracker.restore(job)
        if job.provider_status not in ("queued", "running"):
            continue
        if job.params:
            tracker.update(
                job.job_id,
                status="running",
                current_phase="queued",
                current_message="Повторный запуск после рестарта",
            )
            enqueue_job(job.job_id, dict(job.params))
            restored += 1
            logger.info(f"reconcile: job {job.job_id} re-enqueued after restart")
        else:
            tracker.fail(job.job_id, "orphaned by restart; re-issue command")
            logger.warning(f"reconcile: job {job.job_id} orphaned by restart")
    return restored


def _resolve_source_to_chorus(kind: str, value: str, output_base: str, user_id: int) -> dict:
    """Резолвит источник трека платформы в запись припева. Блокирующая (executor).

    kind: track_id | minio_key | spotify_url | prompt.
    Возвращает chorus-запись (как chorus_db.get_chorus). Кидает RuntimeError
    с actionable-сообщением при любой невозможности.
    """
    # Ленивые импорты: api_server импортирует этот модуль на старте,
    # поэтому обычный импорт наверху был бы циклическим.
    from api_server import import_minio_track, process_track
    from modules.validation import MinioImportRequest

    def _latest_chorus_for_track(track_id: str) -> "dict | None":
        choruses = [
            c for c in chorus_db.list_user_choruses(output_base, user_id)
            if c.get("track_id") == track_id
        ]
        return choruses[0] if choruses else None

    def _chorus_via_process(track_id: str) -> dict:
        existing = _latest_chorus_for_track(track_id)
        if existing:
            return existing
        process_track(track_id)
        chorus = _latest_chorus_for_track(track_id)
        if not chorus:
            raise RuntimeError(f"Трек {track_id} обработан, но припев не извлечён")
        return chorus

    if kind == "track_id":
        return _chorus_via_process(value)

    if kind == "minio_key":
        result = import_minio_track(MinioImportRequest(key=value))
        if result.get("error"):
            raise RuntimeError(f"Импорт из MinIO не удался: {result['error']}")
        choruses = result.get("choruses") or []
        if not choruses:
            raise RuntimeError(f"Из трека {value} не удалось извлечь припев")
        chorus_id = choruses[0].get("id")
        chorus = chorus_db.get_chorus(output_base, user_id, chorus_id)
        if not chorus:
            raise RuntimeError(f"Припев {chorus_id} не найден после импорта")
        return chorus

    if kind == "spotify_url":
        return _chorus_via_query(value, output_base, user_id, _chorus_via_process)

    if kind == "prompt":
        # 1) Уже импортированный трек по подстроке "artist title" (тёплая библиотека)
        needle = value.strip().lower()
        for trk in track_db.list_user_tracks(output_base, user_id):
            haystack = f"{trk.get('artist', '')} {trk.get('title', '')}".lower()
            if needle and needle in haystack:
                return _chorus_via_process(trk["id"])
        # 2) Скачиваем по имени ИЛИ ссылке без Spotify API (Deezer -> yt-dlp)
        return _chorus_via_query(value, output_base, user_id, _chorus_via_process)

    raise RuntimeError(f"Неизвестный источник трека: {kind}")


def _chorus_via_query(query: str, output_base: str, user_id: int, chorus_via_process) -> dict:
    """Скачивает трек по свободному запросу (имя ИЛИ ссылка) без Spotify API, извлекает припев.

    Deezer (ARL) -> yt-dlp фолбэк, см. modules.track_resolver. Заменяет старую
    Spotify-цепочку (search/resolve падали 403 с политикой Premium 2026).
    """
    import shutil
    import tempfile

    from modules.track_resolver import download_freeform

    tmp_dir = tempfile.mkdtemp()
    try:
        dt = download_freeform(query, tmp_dir, timeout=300)
        if not dt:
            raise RuntimeError(
                f"Не удалось скачать трек по запросу «{query}». Проверьте название/ссылку "
                "или загрузите MP3 через MinIO (бакет music-tracks)."
            )
        is_link = query.strip().lower().startswith(("http://", "https://"))
        record = track_db.save_track(
            output_base=output_base,
            user_id=user_id,
            src_path=dt.path,
            source=dt.source,
            artist=dt.artist,
            title=dt.title or Path(dt.path).stem,
            duration=dt.duration,
            spotify_url=query if is_link else "",
            is_preview=dt.is_preview,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return chorus_via_process(record["id"])


async def run_api_job(config: dict, job_id: str, params: dict):
    """Запускает рендер-пайплайн для одной API-задачи."""
    job = tracker.get(job_id)
    if not job or job.status != "running":
        return

    output_base = config["paths"]["output_dir"]
    user_id = job.user_id or settings.owner_id
    chorus_id = params.get("chorus_id")
    source = params.get("source") or {}
    scenario = params.get("scenario", "karaoke")
    orientation = params.get("orientation", "portrait")
    bg_type = params.get("bg_type", "footage")
    video_count = params.get("video_count", 1)

    loop = asyncio.get_event_loop()

    # Находим припев
    chorus_data = None
    if not chorus_id and source.get("kind"):
        # Платформенный запрос (/api/v1/videos): резолвим источник трека
        # (импорт + транскрипция + припев) до рендера. Тяжёлая блокирующая
        # работа -> executor, чтобы не замораживать event loop бота.
        tracker.update(
            job_id,
            current_phase="resolving",
            current_message=f"Готовлю трек ({source['kind']})...",
        )
        try:
            chorus_data = await loop.run_in_executor(
                None,
                functools.partial(
                    _resolve_source_to_chorus,
                    source["kind"], str(source.get("value", "")), output_base, user_id,
                ),
            )
        except Exception as e:
            tracker.fail(job_id, str(e))
            return

    if chorus_data is None:
        if not chorus_id:
            # Берём последний доступный припев
            choruses = chorus_db.list_user_choruses(output_base, user_id)
            if not choruses:
                tracker.fail(job_id, "Нет доступных припевов. Загрузите трек через Telegram-бота.")
                return
            chorus_data = choruses[0]
        else:
            chorus_data = chorus_db.get_chorus(output_base, user_id, chorus_id)
            if not chorus_data:
                tracker.fail(job_id, f"Припев {chorus_id} не найден")
                return

    chorus_path = chorus_data["path"]
    if not os.path.exists(chorus_path):
        tracker.fail(job_id, "Файл припева не найден на диске")
        return

    lyrics_lines = _deserialize_lyrics(chorus_data.get("lyrics", []))

    # Запись трека нужна promo/cover/pov-сценариям (title/artist/spotify_url).
    # Раньше здесь было NameError: trk использовался, но нигде не определялся.
    track_ref = chorus_data.get("track_id", "")
    trk = track_db.get_track(output_base, user_id, track_ref) if track_ref else None

    # Создаём рабочую директорию
    session_id = uuid.uuid4().hex[:8]
    project_dir = os.path.join(output_base, str(user_id), session_id)
    Path(project_dir).mkdir(parents=True, exist_ok=True)

    tracker.update(job_id, current_phase="rendering", current_message="Запуск рендера")

    style = STYLE_PRESETS.get(DEFAULT_STYLE, STYLE_PRESETS["clean"])
    highlight_color = config.get("karaoke", {}).get("highlight_color", "0xFFD700")
    fonts_dir = config["paths"]["fonts_dir"]

    # Фоновые видео для караоке с футажом (и для slideshow).
    # API-путь раньше только читал кэш (его наполнял лишь бот) — теперь
    # при пустом кэше скачиваем футажи сами (Pixabay/Pexels).
    bg_videos = []
    if (scenario == "karaoke" and bg_type == "footage") or scenario == "slideshow":
        from modules.footage_prewarm import (
            footage_keys_configured,
            list_cached_videos,
            prewarm_footage_cache,
        )

        bg_videos = list_cached_videos(output_base)
        if len(bg_videos) < 4:
            tracker.update(
                job_id,
                current_phase="searching_footage",
                current_message="Скачиваю футажи (Pixabay/Pexels)...",
            )
            bg_videos = await prewarm_footage_cache(config, output_base, orientation=orientation)
        if not bg_videos:
            if footage_keys_configured():
                note = "Футажи не нашлись — использую анимированный фон"
            else:
                note = (
                    "PIXABAY_API_KEY/PEXELS_API_KEY не заданы — "
                    "использую анимированный фон вместо футажей"
                )
            logger.warning(f"job {job_id}: {note}")
            tracker.update(job_id, current_message=note)
            # Без футажей — fallback на анимированный
            bg_type = "animated"

    results = []
    shuffled_bgs = list(bg_videos)
    random.shuffle(shuffled_bgs)

    for vid_num in range(1, video_count + 1):
        base_pct = int((vid_num - 1) / video_count * 100)
        step_pct = int(100 / video_count)

        tracker.update(
            job_id, progress=vid_num - 1,
            current_phase="rendering",
            current_message=f"Рендер видео {vid_num}/{video_count} — подготовка фона",
        )
        iter_dir = os.path.join(project_dir, f"iter_{vid_num}")

        try:
            if scenario == "karaoke":
                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — генерация фона")
                karaoke_dir = os.path.join(iter_dir, "karaoke")
                kwargs = dict(
                    lyrics_lines=lyrics_lines,
                    background_videos=None,
                    chorus_audio_path=chorus_path,
                    output_dir=karaoke_dir,
                    fonts_dir=fonts_dir,
                    orientation=orientation,
                    highlight_color=highlight_color,
                    style=style,
                    use_animated_bg=(bg_type == "animated"),
                    palette_seed=vid_num - 1,
                )
                if bg_type == "footage" and shuffled_bgs:
                    kwargs["background_videos"] = [shuffled_bgs[(vid_num - 1) % len(shuffled_bgs)]]

                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — FFmpeg рендер")
                result = await loop.run_in_executor(
                    None, functools.partial(build_karaoke, **kwargs)
                )
                if result:
                    tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — сохранение")
                    vid_record = video_db.save_video(
                        output_base=output_base, user_id=user_id,
                        src_path=result.output_path,
                        chorus_id=chorus_data["id"],
                        track_id=chorus_data.get("track_id", ""),
                        scenario="karaoke", bg_type=bg_type,
                        orientation=orientation,
                    )
                    # Генерация метаданных и загрузка в MinIO
                    track_name = chorus_data.get("name", "Unknown Track")
                    meta = _generate_video_meta(track_name, "karaoke")
                    minio_key = f"agentmusic/{user_id}/{vid_record['id']}.mp4"
                    minio_result = _upload_to_minio(result.output_path, minio_key, {
                        "source_service": "agentmusic",
                        "status": "published",
                        "scenario": "karaoke",
                        "orientation": orientation,
                        "track_name": track_name,
                        "chorus_id": chorus_data["id"],
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                    results.append({
                        "video": result.output_path,
                        "video_id": vid_record["id"],
                        "minio_key": minio_key if minio_result else None,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })

            elif scenario == "slideshow":
                # Mood Slideshow: lyric-карточки поверх перемешанных футажей.
                from modules.bundle_slideshow import build_slideshow

                if not lyrics_lines:
                    logger.warning(f"slideshow vid {vid_num}: пустые lyrics_lines, пропуск")
                    continue
                bgs_for_slideshow = shuffled_bgs or bg_videos
                if not bgs_for_slideshow:
                    logger.warning(f"slideshow vid {vid_num}: нет фоновых футажей, пропуск")
                    continue

                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — slideshow")
                slideshow_dir = os.path.join(iter_dir, "slideshow")
                try:
                    result = await loop.run_in_executor(
                        None, functools.partial(
                            build_slideshow,
                            lyrics_lines=lyrics_lines,
                            background_videos=bgs_for_slideshow,
                            chorus_audio_path=chorus_path,
                            output_dir=slideshow_dir,
                            fonts_dir=fonts_dir,
                            orientation=orientation,
                            style=style,
                            palette_seed=vid_num - 1,
                        )
                    )
                    if result:
                        vid_record = video_db.save_video(
                            output_base=output_base, user_id=user_id,
                            src_path=result.output_path,
                            chorus_id=chorus_data["id"],
                            track_id=chorus_data.get("track_id", ""),
                            scenario="slideshow", bg_type="slideshow",
                            orientation=orientation,
                        )
                        track_name = chorus_data.get("name", "Unknown Track")
                        meta = _generate_video_meta(track_name, "slideshow")
                        minio_key = f"agentmusic/{user_id}/{vid_record['id']}.mp4"
                        minio_result = _upload_to_minio(result.output_path, minio_key, {
                            "source_service": "agentmusic",
                            "status": "published",
                            "scenario": "slideshow",
                            "orientation": orientation,
                            "track_name": track_name,
                            "chorus_id": chorus_data["id"],
                            "title": meta.get("title", ""),
                            "description": meta.get("description", ""),
                            "hashtags": meta.get("hashtags", []),
                        })
                        results.append({
                            "video": result.output_path,
                            "video_id": vid_record["id"],
                            "minio_key": minio_key if minio_result else None,
                            "title": meta.get("title", ""),
                            "description": meta.get("description", ""),
                            "hashtags": meta.get("hashtags", []),
                        })
                except Exception as e:
                    logger.error(f"slideshow render failed: {e}")
                    continue

            elif scenario == "track_promo":
                # Track Promo: hook → chorus kinetic → cover reveal → CTA.
                from modules.bundle_track_promo import build_track_promo, TrackPromoConfig
                from modules.utils import get_media_duration

                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — track_promo")
                cover = _resolve_cover(output_base, user_id, chorus_data.get("track_id", ""))

                promo_dir = os.path.join(iter_dir, "track_promo")
                os.makedirs(promo_dir, exist_ok=True)
                output_mp4_p = os.path.join(promo_dir, "final.mp4")
                font_path = os.path.join(fonts_dir, "Montserrat-Bold.ttf")

                try:
                    dur_p = get_media_duration(chorus_path)
                except Exception:
                    dur_p = 21.0
                if dur_p <= 0:
                    dur_p = 21.0

                palette_names_p = ["sad-girl", "trap", "dark", "dream-pop", "default"]
                palette_name_p = palette_names_p[(vid_num - 1) % len(palette_names_p)]
                hook_phrases_p = [
                    "this song will ruin you",
                    "why is nobody talking about this",
                    "you need to hear this",
                    "I'm gatekeeping this",
                    "POV: your new favorite song",
                ]
                hook_phrase_p = hook_phrases_p[(vid_num - 1) % len(hook_phrases_p)]
                cta_texts_p = [
                    "save this before it blows up",
                    "add to your playlist now",
                    "press play and thank me later",
                    "full track → link in bio",
                ]
                cta_p = cta_texts_p[(vid_num - 1) % len(cta_texts_p)]

                track_name = (trk.get("title") if trk else None) or chorus_data.get("name", "Unknown Track")
                artist_name = (trk.get("artist") if trk else None) or "Unknown Artist"
                spotify_url = (trk.get("spotify_url") if trk else None) or ""

                cfg_p = TrackPromoConfig(
                    audio_path=chorus_path,
                    lyrics=lyrics_lines,
                    output_path=output_mp4_p,
                    font_path=font_path,
                    duration=min(dur_p, 21.0),
                    track_name=track_name or "Unknown Track",
                    artist_name=artist_name or "Unknown Artist",
                    cover_path=cover,
                    spotify_url=spotify_url,
                    palette_name=palette_name_p,
                    hook_phrase=hook_phrase_p,
                    cta_text=cta_p,
                )

                try:
                    await loop.run_in_executor(
                        None, functools.partial(build_track_promo, cfg_p)
                    )

                    class _PromoResult:
                        def __init__(self, path): self.output_path = path
                    result = _PromoResult(output_mp4_p)

                    vid_record = video_db.save_video(
                        output_base=output_base, user_id=user_id,
                        src_path=result.output_path,
                        chorus_id=chorus_data["id"],
                        track_id=chorus_data.get("track_id", ""),
                        scenario="track_promo", bg_type="promo_cover",
                        orientation=orientation,
                    )
                    meta = _generate_video_meta(track_name, "track_promo")
                    minio_key = f"agentmusic/{user_id}/{vid_record['id']}.mp4"
                    minio_result = _upload_to_minio(result.output_path, minio_key, {
                        "source_service": "agentmusic",
                        "status": "published",
                        "scenario": "track_promo",
                        "orientation": orientation,
                        "track_name": track_name,
                        "chorus_id": chorus_data["id"],
                        "palette": palette_name_p,
                        "hook_phrase": hook_phrase_p,
                        "cta_text": cta_p,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                    results.append({
                        "video": result.output_path,
                        "video_id": vid_record["id"],
                        "minio_key": minio_key if minio_result else None,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                except Exception as e:
                    logger.error(f"track_promo render failed: {e}")
                    continue

            elif scenario == "cover_alive":
                # Cover Alive: cover-art parallax + kinetic lyrics. Обложка обязательна.
                from modules.bundle_cover_alive import build_cover_alive, CoverAliveConfig
                from modules.utils import get_media_duration

                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — cover_alive")
                cover = _resolve_cover(output_base, user_id, chorus_data.get("track_id", ""))
                if not cover:
                    logger.warning(f"cover_alive vid {vid_num}: обложка отсутствует, пропуск")
                    continue

                ca_dir = os.path.join(iter_dir, "cover_alive")
                os.makedirs(ca_dir, exist_ok=True)
                output_mp4_ca = os.path.join(ca_dir, "final.mp4")
                font_path = os.path.join(fonts_dir, "Montserrat-Bold.ttf")

                try:
                    dur_ca = get_media_duration(chorus_path)
                except Exception:
                    dur_ca = 21.0
                if dur_ca <= 0:
                    dur_ca = 21.0

                palettes_ca = ["sad-girl", "trap", "dark", "dream-pop", "default"]
                palette_ca = palettes_ca[(vid_num - 1) % len(palettes_ca)]

                track_name = (trk.get("title") if trk else None) or chorus_data.get("name", "Unknown Track")
                artist_name = (trk.get("artist") if trk else None) or "Unknown Artist"

                cfg_ca = CoverAliveConfig(
                    audio_path=chorus_path,
                    lyrics=lyrics_lines,
                    output_path=output_mp4_ca,
                    font_path=font_path,
                    duration=min(dur_ca, 21.0),
                    track_name=track_name or "Unknown Track",
                    artist_name=artist_name or "Unknown Artist",
                    cover_path=cover,
                    palette_name=palette_ca,
                )

                try:
                    await loop.run_in_executor(
                        None, functools.partial(build_cover_alive, cfg_ca)
                    )

                    class _CoverAliveResult:
                        def __init__(self, path): self.output_path = path
                    result = _CoverAliveResult(output_mp4_ca)

                    vid_record = video_db.save_video(
                        output_base=output_base, user_id=user_id,
                        src_path=result.output_path,
                        chorus_id=chorus_data["id"],
                        track_id=chorus_data.get("track_id", ""),
                        scenario="cover_alive", bg_type="cover",
                        orientation=orientation,
                    )
                    meta = _generate_video_meta(track_name, "cover_alive")
                    minio_key = f"agentmusic/{user_id}/{vid_record['id']}.mp4"
                    minio_result = _upload_to_minio(result.output_path, minio_key, {
                        "source_service": "agentmusic",
                        "status": "published",
                        "scenario": "cover_alive",
                        "orientation": orientation,
                        "track_name": track_name,
                        "chorus_id": chorus_data["id"],
                        "palette": palette_ca,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                    results.append({
                        "video": result.output_path,
                        "video_id": vid_record["id"],
                        "minio_key": minio_key if minio_result else None,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                except Exception as e:
                    logger.error(f"cover_alive render failed: {e}")
                    continue

            elif scenario == "pov_spotify":
                # POV Spotify: mockup интерфейса Spotify. Обложка обязательна.
                from modules.bundle_pov_spotify import build_pov_spotify, POVSpotifyConfig
                from modules.utils import get_media_duration

                tracker.update(job_id, current_message=f"Рендер видео {vid_num}/{video_count} — pov_spotify")
                cover = _resolve_cover(output_base, user_id, chorus_data.get("track_id", ""))
                if not cover:
                    logger.warning(f"pov_spotify vid {vid_num}: обложка отсутствует, пропуск")
                    continue

                pov_dir = os.path.join(iter_dir, "pov_spotify")
                os.makedirs(pov_dir, exist_ok=True)
                output_mp4_pov = os.path.join(pov_dir, "final.mp4")
                font_path = os.path.join(fonts_dir, "Montserrat-Bold.ttf")

                try:
                    dur_pov = get_media_duration(chorus_path)
                except Exception:
                    dur_pov = 21.0
                if dur_pov <= 0:
                    dur_pov = 21.0

                palettes_pov = ["dark", "trap", "sad-girl", "dream-pop", "default"]
                palette_pov = palettes_pov[(vid_num - 1) % len(palettes_pov)]
                hooks_pov = [
                    "found this gem on spotify",
                    "adding this to every playlist",
                    "spotify played this for me",
                    "my new obsession",
                    "pov: you found it first",
                ]
                hook_pov = hooks_pov[(vid_num - 1) % len(hooks_pov)]

                track_name = (trk.get("title") if trk else None) or chorus_data.get("name", "Unknown Track")
                artist_name = (trk.get("artist") if trk else None) or "Unknown Artist"

                cfg_pov = POVSpotifyConfig(
                    audio_path=chorus_path,
                    lyrics=lyrics_lines,
                    output_path=output_mp4_pov,
                    font_path=font_path,
                    duration=min(dur_pov, 21.0),
                    track_name=track_name or "Unknown Track",
                    artist_name=artist_name or "Unknown Artist",
                    cover_path=cover,
                    palette_name=palette_pov,
                    hook_phrase=hook_pov,
                )

                try:
                    await loop.run_in_executor(
                        None, functools.partial(build_pov_spotify, cfg_pov)
                    )

                    class _POVResult:
                        def __init__(self, path): self.output_path = path
                    result = _POVResult(output_mp4_pov)

                    vid_record = video_db.save_video(
                        output_base=output_base, user_id=user_id,
                        src_path=result.output_path,
                        chorus_id=chorus_data["id"],
                        track_id=chorus_data.get("track_id", ""),
                        scenario="pov_spotify", bg_type="cover",
                        orientation=orientation,
                    )
                    meta = _generate_video_meta(track_name, "pov_spotify")
                    minio_key = f"agentmusic/{user_id}/{vid_record['id']}.mp4"
                    minio_result = _upload_to_minio(result.output_path, minio_key, {
                        "source_service": "agentmusic",
                        "status": "published",
                        "scenario": "pov_spotify",
                        "orientation": orientation,
                        "track_name": track_name,
                        "chorus_id": chorus_data["id"],
                        "palette": palette_pov,
                        "hook_phrase": hook_pov,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                    results.append({
                        "video": result.output_path,
                        "video_id": vid_record["id"],
                        "minio_key": minio_key if minio_result else None,
                        "title": meta.get("title", ""),
                        "description": meta.get("description", ""),
                        "hashtags": meta.get("hashtags", []),
                    })
                except Exception as e:
                    logger.error(f"pov_spotify render failed: {e}")
                    continue

        except Exception as e:
            logger.error(f"API render error vid {vid_num}: {e}")

    if results:
        tracker.complete(job_id, results=results)
        logger.info(f"API job {job_id} done: {len(results)} videos")
    else:
        tracker.fail(job_id, "Не удалось создать видео")


async def worker_loop(config: dict):
    """Основной цикл воркера — ожидает задачи из очереди."""
    q = get_queue()
    logger.info("API worker started")
    while True:
        try:
            item = await q.get()
            job_id = item.pop("job_id")
            await run_api_job(config, job_id, item)
        except Exception as e:
            logger.error(f"API worker error: {e}")
