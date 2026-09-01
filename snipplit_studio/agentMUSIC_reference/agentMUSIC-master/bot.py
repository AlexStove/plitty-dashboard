"""
Telegram-бот: агент генерации музыкального контента (agentMUSIC).

WORKFLOW:
  /start
    └─ WAIT_ENTRY (3 кнопки)
        ├─ "🎵 Загрузить трек" → WAIT_AUDIO
        │   └─ handle_audio() → save в track_db → process_track()
        │
        ├─ "🎤 Spotify артист" → WAIT_SPOTIFY_LINK
        │   └─ handle_spotify_link() → spotdl → save в track_db → process_track() для каждого
        │
        └─ "📁 Мои припевы" → WAIT_CHORUS_CHOICE → handle_chorus_choice() → WAIT_SCENARIO

  process_track(track_path):
    ├─ Whisper транскрипция
    ├─ dual_chorus.extract_two_choruses() — 2 варианта (audio + text)
    ├─ Отправить в чат: 2 mp3 + текст + кнопки → WAIT_CHORUS_PICK
    └─ handle_chorus_pick() → save в chorus_db → WAIT_SCENARIO

  WAIT_SCENARIO:
    ├─ KARAOKE → WAIT_KARAOKE_BG → footage / animated → WAIT_VIDEO_COUNT
    └─ другие сценарии → WAIT_VIDEO_COUNT
    → WAIT_ORIENTATION → _run_pipeline() → render → отправка в Telegram → END
"""

import asyncio
import functools
import json
import logging
import os
import random
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv(override=False)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from modules.chorus_extractor import ChorusSegment, detect_chorus, extract_chorus_audio, pick_best_segment_with_text
from modules.footage_searcher import search_and_download
from modules.bundle1_karaoke import build_karaoke
from modules.bundle_slideshow import build_slideshow
from modules.whisper_transcriber import segments_to_lyrics_lines, transcribe_with_timings
from modules.styles import DEFAULT_STYLE, STYLE_PRESETS
from modules.utils import check_ffmpeg, get_media_duration
from modules.segment_select import match_text_to_segment, parse_time_range
from modules import track_db, chorus_db, video_db
from modules.job_tracker import tracker as job_tracker
from modules.api_worker import worker_loop as api_worker_loop
from modules.video_validator import validate_video
from modules.dual_chorus import extract_two_choruses, ChorusVariant, _crop_lyrics_to_range
from modules.spotify_loader import (
    is_spotdl_available,
    download_artist_tracks,
    SpotdlError,
)
from modules.config import settings
from modules.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

logger.info(
    "ENV check: SPOTIFY_CLIENT_ID=%s, SPOTIFY_CLIENT_SECRET=%s, TELEGRAM_BOT_TOKEN=%s",
    f"set({settings.spotify_client_id[:6]}...)" if settings.spotify_client_id else "EMPTY",
    f"set({settings.spotify_client_secret[:4]}...)" if settings.spotify_client_secret else "EMPTY",
    "set" if os.getenv("TELEGRAM_BOT_TOKEN") else "EMPTY",
)

# ---------------------------------------------------------------------------
# Состояния ConversationHandler
# ---------------------------------------------------------------------------
WAIT_ENTRY = 0          # выбор: загрузить трек / Spotify / мои припевы
WAIT_AUDIO = 1          # ожидание аудиофайла
WAIT_SPOTIFY_LINK = 2   # ожидание ссылки на артиста
WAIT_CHORUS_CHOICE = 3  # выбор сохранённого припева
WAIT_CHORUS_PICK = 4    # выбор 1-го/2-го/обоих новых вариантов
WAIT_SCENARIO = 5       # выбор сценария рендера
WAIT_KARAOKE_BG = 6     # выбор фона для караоке (footage / animated)
WAIT_VIDEO_COUNT = 7    # количество видео
WAIT_ORIENTATION = 8    # ориентация
WAIT_TRACK_CHOICE = 9   # просмотр/действия с загруженными треками
WAIT_CUT_MODE = 10      # выбор способа нарезки: текст / секунды / авто
WAIT_TEXT_FRAGMENT = 11 # ожидание скопированного куска текста
WAIT_SECONDS = 12       # ожидание диапазона секунд

# Ключи user_data
KEY_PROJECT_DIR = "project_dir"
KEY_SPOTIFY_URL = "spotify_url"          # ссылка Spotify в ожидании выбора источника
KEY_TRACK_ID = "track_id"
KEY_TRACK_NAME = "track_name"
KEY_CHORUS_PATH = "chorus_path"
KEY_CHORUS_ID = "chorus_id"
KEY_LYRICS_LINES = "lyrics_lines"
KEY_CHORUS_VARIANTS = "chorus_variants"  # список ChorusVariant до выбора
KEY_SCENARIO = "scenario"
KEY_KARAOKE_BG_TYPE = "karaoke_bg_type"  # "footage" | "animated"
KEY_STYLE = "style"
KEY_ORIENTATION = "orientation"
KEY_BG_VIDEOS = "bg_videos"
KEY_VIDEO_COUNT = "video_count"
KEY_PENDING_TRACKS = "pending_tracks"  # очередь треков из Spotify
KEY_FULL_SEGMENTS = "full_segments"
KEY_TRACK_PATH = "track_path"          # путь к исходному аудио (для ручной нарезки)

# Сценарии
SCENARIO_KARAOKE = "karaoke"
SCENARIO_SLIDESHOW = "slideshow"
SCENARIO_TRACK_PROMO = "track_promo"  # 4-актный промо: hook → chorus → cover reveal → CTA
SCENARIO_COVER_ALIVE = "cover_alive"  # cover art parallax + kinetic lyrics overlay
SCENARIO_POV_SPOTIFY = "pov_spotify"  # Spotify UI mockup — play button + cover + progress

# Типы фона для караоке
KARAOKE_BG_FOOTAGE = "footage"
KARAOKE_BG_ANIMATED = "animated"

OWNER_ID = settings.owner_id

# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------
def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def get_env(key: str, required: bool = True) -> Optional[str]:
    val = os.getenv(key)
    if not val and required:
        raise EnvironmentError(f"Переменная окружения не задана: {key}")
    return val


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_project_dir(user_id: int) -> str:
    output_base = Path(CONFIG["paths"]["output_dir"])
    output_base.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4().hex[:8]
    project_dir = str(output_base / str(user_id) / session_id)
    Path(project_dir).mkdir(parents=True, exist_ok=True)
    return project_dir


def _output_base() -> str:
    return CONFIG["paths"]["output_dir"]


def _extract_embedded_cover(mp3_path: str, user_id: int, track_id: str) -> Optional[str]:
    """
    Достаёт встроенную обложку (ID3 APIC) из mp3 и сохраняет в covers/<id>.jpg.
    Работает БЕЗ Spotify API — нужен, когда Spotify Web API недоступен (403).
    Возвращает путь к jpg или None.
    """
    try:
        from mutagen.id3 import ID3
        tags = ID3(mp3_path)
        apics = [tags[k] for k in tags.keys() if k.startswith("APIC")]
        if not apics:
            return None
        data = apics[0].data
        if not data or len(data) < 1024:
            return None
        dst = os.path.join(_output_base(), str(user_id), "covers", f"{track_id}.jpg")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        logger.info(f"cover from embedded ID3: {dst} ({len(data)} б)")
        return dst
    except Exception as e:
        logger.debug(f"embedded cover extract failed: {e}")
        return None


def _ensure_cover_local(trk: dict, user_id: int) -> Optional[str]:
    """
    Возвращает абсолютный path к локальной обложке трека, существующий на диске.

    Если cover_local_path пустой / относительный / файла нет — пробует
    перекачать по cover_url. Если и это не удаётся — возвращает None.

    Починка: раньше при удалении файла обложки (или если cover_local_path
    был относительным и CWD изменился) сценарий cover_alive падал с
    "Не удалось создать видео", хотя cover_url в базе был — нужно было
    всего лишь перекачать.
    """
    if not trk:
        return None
    cp = (trk.get("cover_local_path") or "").strip()
    # Относительные пути делаем абсолютными относительно output_base (raw)
    if cp and not os.path.isabs(cp):
        cp = os.path.abspath(os.path.join(".", cp))
    if cp and os.path.exists(cp) and os.path.getsize(cp) > 1024:
        return cp
    # Пробуем перекачать
    cover_url = (trk.get("cover_url") or "").strip()
    if not cover_url:
        return None
    try:
        from modules.spotify_cover_fetcher import _download_cover
    except ImportError:
        return None
    # Стандартное место хранения: output/<uid>/covers/<track_id>.jpg
    track_id_spotify = (trk.get("spotify_track_id") or trk.get("id") or "").strip()
    if not track_id_spotify:
        return None
    local_path = os.path.join(
        _output_base(), str(user_id), "covers", f"{track_id_spotify}.jpg"
    )
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if _download_cover(cover_url, local_path):
        logger.info(f"cover re-downloaded: {local_path}")
        # Обновляем track_db чтобы в следующий раз сразу нашли
        try:
            track_db.update_track(
                _output_base(), user_id, trk.get("id"),
                cover_local_path=local_path,
            )
        except Exception as _e:
            logger.debug(f"cover path update in track_db failed: {_e}")
        return local_path
    return None


def _cleanup_old_sessions(user_id: int) -> int:
    """Удаляет временные сессии (не _tracks/_choruses/_videos) старше N дней."""
    max_age_days = CONFIG.get("cleanup", {}).get("session_max_age_days", 7)
    user_dir = Path(_output_base()) / str(user_id)
    if not user_dir.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for d in user_dir.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def _cleanup_all_users() -> tuple[int, int]:
    output_dir = Path(_output_base())
    if not output_dir.exists():
        return 0, 0
    users = 0
    total = 0
    for ud in output_dir.iterdir():
        if not ud.is_dir() or ud.name.startswith("_"):
            continue
        try:
            uid = int(ud.name)
        except ValueError:
            continue
        n = _cleanup_old_sessions(uid)
        if n:
            users += 1
            total += n
    return users, total


def _collect_backgrounds(footage_results: dict) -> list[str]:
    paths = []
    seen = set()
    for results in footage_results.values():
        for f in results:
            if f.local_path and os.path.exists(f.local_path) and f.local_path not in seen:
                paths.append(f.local_path)
                seen.add(f.local_path)
    random.shuffle(paths)
    return paths


def _try_generate_smart_queries(base_queries: list[str], track_description: str = "") -> list[str]:
    api_key = settings.anthropic_api_key
    if not api_key or api_key == "your_anthropic_api_key_here":
        return base_queries
    try:
        from modules.claude_agent import generate_search_queries
        description = track_description or "Музыкальный трек"
        return generate_search_queries(description, base_queries, api_key)
    except Exception as e:
        logger.warning(f"Claude agent недоступен: {e}")
        return base_queries


# ---------------------------------------------------------------------------
# Точка входа: /start
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    _cleanup_old_sessions(user.id)

    saved_choruses = chorus_db.list_user_choruses(_output_base(), user.id)
    saved_tracks = track_db.list_user_tracks(_output_base(), user.id)

    text = f"Привет, {user.first_name}!\n\n"
    text += "Что делаем?"
    if user.id == OWNER_ID:
        text += "\n\nАдмин: /stats /cleanup"
    if saved_tracks:
        text += f"\n\n📀 В базе {len(saved_tracks)} треков"
    if saved_choruses:
        text += f"\n📁 Сохранено {len(saved_choruses)} припевов"

    buttons = [
        [InlineKeyboardButton("🎵 Загрузить трек", callback_data="entry_upload")],
        [InlineKeyboardButton("🎤 Spotify артист", callback_data="entry_spotify")],
    ]
    if saved_choruses:
        buttons.append([InlineKeyboardButton("📁 Мои припевы", callback_data="entry_choruses")])
    if saved_tracks:
        buttons.append([InlineKeyboardButton("📀 Мои треки", callback_data="entry_tracks")])

    keyboard = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)
    return WAIT_ENTRY


async def handle_entry_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "entry_upload":
        await query.edit_message_text(
            "🎵 Загрузка трека\n\n"
            "Отправь аудиофайл: MP3, WAV, FLAC, M4A, OGG, AAC — "
            "как аудио или как документ."
        )
        return WAIT_AUDIO

    if choice == "entry_spotify":
        if not is_spotdl_available():
            await query.edit_message_text(
                "❌ spotdl не установлен. Запусти: `pip install spotdl`",
            )
            return ConversationHandler.END
        await query.edit_message_text(
            "🎤 Spotify артист\n\n"
            "Отправь ссылку на артиста или плейлист:\n"
            "https://open.spotify.com/artist/...\n"
            "https://open.spotify.com/playlist/..."
        )
        return WAIT_SPOTIFY_LINK

    if choice == "entry_choruses":
        return await _show_saved_choruses(update, context)

    if choice == "entry_tracks":
        return await _show_saved_tracks(update, context)

    return WAIT_ENTRY


# ---------------------------------------------------------------------------
# Загрузка трека (кнопка "🎵 Загрузить трек")
# ---------------------------------------------------------------------------
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    audio = update.message.audio or update.message.voice or update.message.document
    if not audio:
        await update.message.reply_text("Отправь аудиофайл (MP3, WAV, FLAC, M4A, OGG).")
        return WAIT_AUDIO

    user_id = update.effective_user.id
    project_dir = make_project_dir(user_id)
    tmp_path = os.path.join(project_dir, "track_input.mp3")

    await update.message.reply_text("Скачиваю трек...")
    file = await context.bot.get_file(audio.file_id)
    await file.download_to_drive(tmp_path)

    # Метаданные из Telegram
    track_name = ""
    if hasattr(audio, "file_name") and audio.file_name:
        track_name = os.path.splitext(audio.file_name)[0][:80]
    elif hasattr(audio, "title") and audio.title:
        track_name = audio.title[:80]

    artist = ""
    if hasattr(audio, "performer") and audio.performer:
        artist = audio.performer[:80]

    # Сохраняем в базу треков
    record = track_db.save_track(
        output_base=_output_base(),
        user_id=user_id,
        src_path=tmp_path,
        source="upload",
        artist=artist,
        title=track_name,
    )
    # Обогащение: обложка + метаданные (ID3 / Spotify по hint artist/title)
    try:
        from modules.spotify_cover_fetcher import enrich_from_file
        pack = enrich_from_file(
            record["path"], _output_base(), user_id,
            hint_artist=artist, hint_title=track_name,
            use_shazam_fallback=False,
        )
        if pack:
            track_db.update_track(
                _output_base(), user_id, record["id"],
                artist=pack.artist_name or artist,
                title=pack.track_name or track_name,
                spotify_url=pack.spotify_url,
                spotify_track_id=pack.track_id,
                cover_url=pack.cover_url,
                cover_local_path=pack.cover_local_path,
            )
    except Exception as _e:
        logger.debug(f"upload enrich failed: {_e}")
    # Fallback: встроенная ID3-обложка (без Spotify API)
    _utrk = track_db.get_track(_output_base(), user_id, record["id"]) or {}
    _ucl = _utrk.get("cover_local_path", "")
    if not (_ucl and os.path.exists(_ucl)):
        _uemb = _extract_embedded_cover(record["path"], user_id, record["id"])
        if _uemb:
            track_db.update_track(_output_base(), user_id, record["id"], cover_local_path=_uemb)

    context.user_data[KEY_PROJECT_DIR] = project_dir
    context.user_data[KEY_TRACK_ID] = record["id"]
    context.user_data[KEY_TRACK_NAME] = track_name or "трек"

    return await process_track(update, context, record["path"])


# ---------------------------------------------------------------------------
# Spotify (кнопка "🎤 Spotify артист")
# ---------------------------------------------------------------------------
async def handle_spotify_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text.startswith("http") or "spotify.com" not in text:
        await update.message.reply_text("Отправь корректную ссылку на Spotify.")
        return WAIT_SPOTIFY_LINK

    # Запоминаем ссылку и спрашиваем источник скачивания.
    context.user_data[KEY_SPOTIFY_URL] = text
    buttons = [
        [InlineKeyboardButton("⚡ Авто (Deezer → YouTube)", callback_data="src_auto")],
        [InlineKeyboardButton("🎧 Deezer (полное качество)", callback_data="src_deezer")],
        [InlineKeyboardButton("▶️ YouTube", callback_data="src_youtube")],
    ]
    await update.message.reply_text(
        "Откуда качать треки?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_SPOTIFY_LINK


async def handle_spotify_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    source = query.data.replace("src_", "") or "auto"  # auto | deezer | youtube

    url = context.user_data.get(KEY_SPOTIFY_URL, "")
    if not url:
        await query.edit_message_text("Ссылка потерялась. /start — начать заново.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    await query.edit_message_text(
        f"⏬ Скачиваю треки ({source})... (это может занять несколько минут)"
    )
    status_msg = query.message

    project_dir = make_project_dir(user_id)
    download_dir = os.path.join(project_dir, "spotify_dl")

    loop = asyncio.get_event_loop()
    try:
        tracks = await loop.run_in_executor(
            None,
            functools.partial(
                download_artist_tracks, url, download_dir, 20, 300, None, None, source
            ),
        )
    except SpotdlError as e:
        await status_msg.edit_text(str(e))
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"download error: {e}")
        await status_msg.edit_text(f"❌ Ошибка скачивания: {e}")
        return ConversationHandler.END

    if not tracks:
        await status_msg.edit_text("Не удалось скачать ни одного трека.")
        return ConversationHandler.END

    # Сохраняем все треки в базу
    saved_records = []
    preview_count = 0
    for dt in tracks:
        if dt.is_preview:
            preview_count += 1
        rec = track_db.save_track(
            output_base=_output_base(),
            user_id=user_id,
            src_path=dt.path,
            source="spotify",
            artist=dt.artist,
            title=dt.title,
            duration=dt.duration,
            spotify_url=url,
            is_preview=dt.is_preview,
        )
        # Обогащение per-track: cover_url + локальная обложка + album/spotify_track_id
        try:
            from modules.spotify_cover_fetcher import enrich_from_file
            pack = enrich_from_file(
                rec["path"], _output_base(), user_id,
                hint_artist=dt.artist, hint_title=dt.title,
                use_shazam_fallback=False,
            )
            if pack:
                track_db.update_track(
                    _output_base(), user_id, rec["id"],
                    artist=pack.artist_name or dt.artist,
                    title=pack.track_name or dt.title,
                    album=pack.album_name,
                    release_date=pack.release_date,
                    popularity=pack.popularity,
                    spotify_url=pack.spotify_url,
                    spotify_track_id=pack.track_id,
                    cover_url=pack.cover_url,
                    cover_local_path=pack.cover_local_path,
                )
                logger.info(
                    f"enriched: {pack.artist_name} — {pack.track_name} "
                    f"cover={bool(pack.cover_local_path)}"
                )
        except Exception as _e:
            logger.warning(f"enrich failed: {_e}")
        # Надёжный fallback: встроенная ID3-обложка (без Spotify API)
        _trk = track_db.get_track(_output_base(), user_id, rec["id"]) or {}
        _cl = _trk.get("cover_local_path", "")
        if not (_cl and os.path.exists(_cl)):
            _emb = _extract_embedded_cover(rec["path"], user_id, rec["id"])
            if _emb:
                track_db.update_track(_output_base(), user_id, rec["id"], cover_local_path=_emb)
        saved_records.append(rec)

    # Очередь треков для последовательной обработки
    context.user_data[KEY_PENDING_TRACKS] = [r["id"] for r in saved_records]
    context.user_data[KEY_PROJECT_DIR] = project_dir

    summary = f"✅ Скачано {len(saved_records)} треков. Начинаю обработку..."
    if preview_count:
        summary += (
            f"\n\n⚠️ Из них {preview_count} — только 30-сек превью "
            f"(полный трек не найден). Для полного качества загрузи MP3 "
            f"вручную через вкладку MinIO."
        )
    await status_msg.edit_text(summary)

    # Обрабатываем первый трек
    return await _process_next_pending_track(update, context)


async def _process_next_pending_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Берёт следующий трек из очереди и запускает process_track."""
    user_id = update.effective_user.id
    pending = context.user_data.get(KEY_PENDING_TRACKS, [])
    if not pending:
        await update.effective_message.reply_text(
            "Все треки обработаны. /start — начать заново."
        )
        return ConversationHandler.END

    track_id = pending.pop(0)
    context.user_data[KEY_PENDING_TRACKS] = pending

    record = track_db.get_track(_output_base(), user_id, track_id)
    if not record:
        return await _process_next_pending_track(update, context)

    context.user_data[KEY_TRACK_ID] = track_id
    context.user_data[KEY_TRACK_NAME] = record.get("title") or "трек"

    await update.effective_message.reply_text(
        f"🎵 Обработка: {record.get('artist', '')} — {record.get('title', '')}"
        if record.get("artist")
        else f"🎵 Обработка: {record.get('title', '')}"
    )

    return await process_track(update, context, record["path"])


# ---------------------------------------------------------------------------
# Универсальная обработка трека: транскрипция + 2 варианта припева
# ---------------------------------------------------------------------------
async def process_track(
    update: Update, context: ContextTypes.DEFAULT_TYPE, track_path: str
) -> int:
    """Whisper → меню выбора способа нарезки (текст / секунды / авто)."""
    msg = update.effective_message
    user_id = update.effective_user.id

    status_msg = await msg.reply_text("🔍 Распознаю текст трека...")
    full_segments = transcribe_with_timings(track_path)

    project_dir = context.user_data.get(KEY_PROJECT_DIR) or make_project_dir(user_id)
    context.user_data[KEY_PROJECT_DIR] = project_dir
    context.user_data[KEY_FULL_SEGMENTS] = full_segments
    context.user_data[KEY_TRACK_PATH] = track_path

    if full_segments:
        await status_msg.edit_text("✅ Текст распознан. Выбери способ нарезки ↓")
    else:
        # Текст не распознался — это не тупик: режут по секундам или авто.
        await status_msg.edit_text(
            "⚠️ Текст распознать не удалось (инструментал или вокал тонет в музыке).\n"
            "Можно вырезать фрагмент по секундам или довериться авто-подбору ↓"
        )

    return await _ask_cut_mode(update, context)


# ---------------------------------------------------------------------------
# Меню выбора способа нарезки фрагмента
# ---------------------------------------------------------------------------
async def _ask_cut_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """3 режима: полный текст → копировать кусок / по секундам / авто."""
    has_text = bool(context.user_data.get(KEY_FULL_SEGMENTS))
    buttons = []
    if has_text:
        buttons.append(
            [InlineKeyboardButton("📝 Полный текст (выбрать кусок)", callback_data="cut_fulltext")]
        )
    buttons.append([InlineKeyboardButton("⏱ По секундам", callback_data="cut_seconds")])
    buttons.append([InlineKeyboardButton("⚡ Авто (2 варианта)", callback_data="cut_auto")])
    keyboard = InlineKeyboardMarkup(buttons)
    text = "Как вырезать фрагмент?"
    await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_CUT_MODE


async def handle_cut_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "cut_fulltext":
        await query.edit_message_text("📝 Готовлю полный текст трека...")
        return await _send_full_text(update, context)

    if choice == "cut_seconds":
        track_path = context.user_data.get(KEY_TRACK_PATH, "")
        dur_hint = ""
        try:
            dur = get_media_duration(track_path)
            m, s = divmod(int(dur), 60)
            dur_hint = f"\nДлительность трека: {m}:{s:02d} ({dur:.0f}с)."
        except Exception:
            pass
        await query.edit_message_text(
            "⏱ Пришли диапазон, который вырезать.\n\n"
            "Форматы: `45-72`, `1:05 - 1:30`, `90 120`." + dur_hint,
            parse_mode="Markdown",
        )
        return WAIT_SECONDS

    if choice == "cut_auto":
        await query.edit_message_text("⚡ Подбираю 2 варианта припева...")
        return await _run_auto_choruses(update, context)

    return WAIT_CUT_MODE


async def _send_full_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправляет весь распознанный текст (с разбивкой на части Telegram)."""
    msg = update.effective_message
    segments = context.user_data.get(KEY_FULL_SEGMENTS, [])
    lines = [s.get("text", "").strip() for s in segments if s.get("text", "").strip()]
    full_text = "\n".join(lines) or "(текста нет)"

    await msg.reply_text(
        "Вот полный текст трека. Скопируй нужный кусок и пришли его сюда "
        "сообщением — я найду его в треке и вырежу.\n"
        "Можно с лёгкими неточностями, поиск нечёткий."
    )

    # Telegram ограничивает сообщение ~4096 символами — режем по строкам.
    chunk = ""
    for ln in full_text.split("\n"):
        if len(chunk) + len(ln) + 1 > 3500:
            await msg.reply_text(chunk or ln)
            chunk = ""
        chunk += (ln + "\n")
    if chunk.strip():
        await msg.reply_text(chunk)

    return WAIT_TEXT_FRAGMENT


async def handle_text_fragment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Принимает скопированный кусок текста и ищет его тайминги (fuzzy)."""
    query_text = (update.message.text or "").strip()
    segments = context.user_data.get(KEY_FULL_SEGMENTS, [])
    logger.info(
        f"text-fragment: получено {len(query_text)} симв., сегментов={len(segments)}"
    )
    if not query_text:
        await update.message.reply_text("Пришли текстом кусок песни.")
        return WAIT_TEXT_FRAGMENT
    if not segments:
        await update.message.reply_text(
            "Текст трека потерялся (сессия сброшена). Нажми /start и загрузи трек заново."
        )
        return WAIT_TEXT_FRAGMENT

    try:
        match = match_text_to_segment(segments, query_text)
    except Exception as e:
        logger.exception("match_text_to_segment упал")
        await update.message.reply_text(
            f"⚠️ Ошибка поиска по тексту: {type(e).__name__}: {e}\n"
            "Попробуй «⏱ По секундам» — /start."
        )
        return WAIT_TEXT_FRAGMENT

    if not match:
        await update.message.reply_text(
            "Не нашёл такой фрагмент в треке 🤔\n"
            "Попробуй скопировать кусок поточнее или выбери «⏱ По секундам» через /start."
        )
        return WAIT_TEXT_FRAGMENT

    logger.info(
        f"text-fragment: матч {match['start']:.1f}-{match['end']:.1f}с "
        f"(score={match['score']:.2f})"
    )
    return await _finalize_single_segment(
        update, context,
        start=match["start"], end=match["end"],
        variant="manual_text",
        reason=f"Выбрано по тексту (совпадение {match['score']*100:.0f}%)",
    )


async def handle_seconds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Принимает диапазон секунд и вырезает его."""
    raw = (update.message.text or "").strip()
    rng = parse_time_range(raw)
    if not rng:
        await update.message.reply_text(
            "Не понял диапазон. Пришли в формате `45-72` или `1:05 - 1:30`.",
            parse_mode="Markdown",
        )
        return WAIT_SECONDS

    start, end = rng
    track_path = context.user_data.get(KEY_TRACK_PATH, "")
    try:
        duration = get_media_duration(track_path)
    except Exception:
        duration = None

    if duration is not None:
        if start >= duration:
            await update.message.reply_text(
                f"Начало ({start:.0f}с) за пределами трека ({duration:.0f}с). Ещё раз?"
            )
            return WAIT_SECONDS
        end = min(end, duration)
    if end - start < 1.0:
        await update.message.reply_text("Слишком короткий фрагмент (<1с). Ещё раз?")
        return WAIT_SECONDS

    return await _finalize_single_segment(
        update, context,
        start=start, end=end,
        variant="manual_seconds",
        reason=f"Выбрано вручную: {start:.0f}с – {end:.0f}с",
    )


async def _finalize_single_segment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start: float,
    end: float,
    variant: str,
    reason: str,
) -> int:
    """
    Вырезает один фрагмент [start, end], сохраняет его в базу припевов
    и переходит к выбору сценария. Общий путь для режимов «текст» и «секунды».
    """
    msg = update.effective_message
    user_id = update.effective_user.id
    track_path = context.user_data.get(KEY_TRACK_PATH, "")
    full_segments = context.user_data.get(KEY_FULL_SEGMENTS, [])
    track_id = context.user_data.get(KEY_TRACK_ID, "")
    track_name = context.user_data.get(KEY_TRACK_NAME, "трек")
    project_dir = context.user_data.get(KEY_PROJECT_DIR) or make_project_dir(user_id)
    context.user_data[KEY_PROJECT_DIR] = project_dir

    status_msg = await msg.reply_text(f"✂️ Вырезаю {start:.1f}с – {end:.1f}с...")

    cut_dir = os.path.join(project_dir, "manual_cut")
    out_path = os.path.join(cut_dir, f"segment_{int(start)}_{int(end)}.mp3")
    seg = ChorusSegment(start=start, end=end, confidence=1.0)
    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            functools.partial(extract_chorus_audio, track_path, seg, out_path),
        )
    except Exception as e:
        logger.error(f"manual cut error: {e}")
        await status_msg.edit_text(f"Не удалось вырезать фрагмент: {e}")
        return ConversationHandler.END

    try:
        lyrics = _crop_lyrics_to_range(full_segments, start, end)

        _trk = track_db.get_track(_output_base(), user_id, track_id) or {}
        is_preview = bool(_trk.get("is_preview", False))
        rec = chorus_db.save_chorus(
            output_base=_output_base(),
            user_id=user_id,
            src_chorus_path=out_path,
            track_id=track_id,
            name=f"{track_name} ({variant})",
            lyrics_lines=lyrics,
            variant=variant,
            start=start,
            end=end,
            is_preview=is_preview,
        )
        chorus_db.cleanup_old(_output_base(), user_id, max_choruses=50)
    except Exception as e:
        logger.exception("manual finalize: сохранение припева упало")
        await status_msg.edit_text(
            f"⚠️ Фрагмент вырезан, но сохранить не удалось: {type(e).__name__}: {e}\n"
            "Нажми /start и попробуй ещё раз."
        )
        return ConversationHandler.END

    context.user_data[KEY_CHORUS_PATH] = rec["path"]
    context.user_data[KEY_CHORUS_ID] = rec["id"]
    context.user_data[KEY_LYRICS_LINES] = lyrics

    # Превью + подтверждение
    text_lines = "\n".join(ll.text for ll in lyrics) if lyrics else "(без текста)"
    try:
        with open(out_path, "rb") as f:
            await msg.reply_audio(audio=f, title=f"Фрагмент {start:.0f}-{end:.0f}с")
    except Exception as e:
        logger.warning(f"Не удалось отправить превью фрагмента: {e}")
    await status_msg.edit_text(
        f"✅ Фрагмент готов ({start:.1f}с – {end:.1f}с).\n💡 {reason}\n\n{text_lines}"[:4000]
    )

    return await _ask_scenario(update, context)


async def _run_auto_choruses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Авто-режим: 2 варианта припева (аудио-анализ + текст-анализ) → WAIT_CHORUS_PICK."""
    msg = update.effective_message
    user_id = update.effective_user.id
    track_path = context.user_data.get(KEY_TRACK_PATH, "")
    full_segments = context.user_data.get(KEY_FULL_SEGMENTS, [])

    chorus_cfg = CONFIG.get("chorus", {})
    project_dir = context.user_data.get(KEY_PROJECT_DIR) or make_project_dir(user_id)
    context.user_data[KEY_PROJECT_DIR] = project_dir
    variants_dir = os.path.join(project_dir, "chorus_variants")

    api_key = settings.anthropic_api_key
    try:
        variants = await asyncio.get_event_loop().run_in_executor(
            None,
            functools.partial(
                extract_two_choruses,
                track_path,
                full_segments,
                variants_dir,
                api_key,
                chorus_cfg.get("min_duration", 15),
                chorus_cfg.get("max_duration", 30),
            ),
        )
    except Exception as e:
        logger.error(f"dual_chorus error: {e}")
        await msg.reply_text(f"Ошибка извлечения припева: {e}")
        return ConversationHandler.END

    if not variants:
        await msg.reply_text("Не удалось извлечь припев. Попробуй «⏱ По секундам».")
        return ConversationHandler.END

    context.user_data[KEY_CHORUS_VARIANTS] = variants
    await msg.reply_text(f"✅ Получено {len(variants)} варианта(ов). Слушай ↓")

    # Отправляем каждый вариант: аудио + текст
    for i, v in enumerate(variants, 1):
        try:
            with open(v.audio_path, "rb") as f:
                await msg.reply_audio(audio=f, title=f"{v.label}")
        except Exception as e:
            logger.warning(f"Не удалось отправить вариант {i}: {e}")

        text_lines = "\n".join(f"{j+1}. {ll.text}" for j, ll in enumerate(v.lyrics)) or "(текста нет)"
        info = (
            f"*{v.label}*\n"
            f"⏱ {v.start:.1f}с – {v.end:.1f}с\n"
            f"💡 {v.reason or '—'}\n\n"
            f"{text_lines}"
        )
        try:
            await msg.reply_text(info, parse_mode="Markdown")
        except Exception:
            await msg.reply_text(info)

    # Кнопки выбора
    if len(variants) == 1:
        buttons = [[InlineKeyboardButton("✅ Использовать", callback_data="pick_0")]]
    else:
        buttons = [
            [
                InlineKeyboardButton("✅ Вариант 1", callback_data="pick_0"),
                InlineKeyboardButton("✅ Вариант 2", callback_data="pick_1"),
            ],
            [InlineKeyboardButton("✅ Оба", callback_data="pick_both")],
        ]
    await msg.reply_text(
        "Что используем?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_CHORUS_PICK


async def handle_chorus_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет выбранные варианты в chorus_db и переходит к выбору сценария."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    variants: list[ChorusVariant] = context.user_data.get(KEY_CHORUS_VARIANTS, [])
    if not variants:
        await query.edit_message_text("Варианты потеряны. /start.")
        return ConversationHandler.END

    track_id = context.user_data.get(KEY_TRACK_ID, "")
    track_name = context.user_data.get(KEY_TRACK_NAME, "трек")

    chosen: list[ChorusVariant] = []
    if query.data == "pick_both":
        chosen = variants
    else:
        try:
            idx = int(query.data.replace("pick_", ""))
            if 0 <= idx < len(variants):
                chosen = [variants[idx]]
        except ValueError:
            pass

    if not chosen:
        chosen = [variants[0]]

    _trk = track_db.get_track(_output_base(), user_id, track_id) or {}
    _is_preview = bool(_trk.get("is_preview", False))
    saved_ids = []
    for v in chosen:
        rec = chorus_db.save_chorus(
            output_base=_output_base(),
            user_id=user_id,
            src_chorus_path=v.audio_path,
            track_id=track_id,
            name=f"{track_name} ({v.variant})",
            lyrics_lines=v.lyrics,
            variant=v.variant,
            start=v.start,
            end=v.end,
            is_preview=_is_preview,
        )
        saved_ids.append(rec["id"])

    # Используем первый выбранный вариант для рендера
    first = chosen[0]
    context.user_data[KEY_CHORUS_PATH] = first.audio_path
    context.user_data[KEY_CHORUS_ID] = saved_ids[0]
    context.user_data[KEY_LYRICS_LINES] = first.lyrics

    chorus_db.cleanup_old(_output_base(), user_id, max_choruses=50)

    await query.edit_message_text(
        f"✅ Сохранено припевов: {len(chosen)}. Перехожу к выбору сценария..."
    )

    return await _ask_scenario(update, context)


# ---------------------------------------------------------------------------
# Сохранённые припевы
# ---------------------------------------------------------------------------
async def _show_saved_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Список загруженных треков пользователя с действиями."""
    user_id = update.effective_user.id
    tracks = track_db.list_user_tracks(_output_base(), user_id)
    if not tracks:
        txt = "Нет загруженных треков. Загрузи трек через 🎵 / 🎤 Spotify."
        if update.callback_query:
            await update.callback_query.edit_message_text(txt)
        else:
            await update.effective_message.reply_text(txt)
        return WAIT_ENTRY

    buttons = []
    for t in tracks[:20]:
        title = (t.get("title") or t["id"]).strip()
        artist = (t.get("artist") or "").strip()
        label = f"📀 {artist} — {title}" if artist else f"📀 {title}"
        buttons.append([InlineKeyboardButton(label[:60], callback_data=f"trk_{t['id']}")])
    buttons.append([InlineKeyboardButton("⬅ Назад", callback_data="trkback")])

    keyboard = InlineKeyboardMarkup(buttons)
    text = f"📀 Твои треки ({len(tracks)}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_TRACK_CHOICE


async def handle_track_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Открыть / перегенерить / удалить выбранный трек."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "trkback":
        return await cmd_start(update, context)
    if data == "trklist":
        return await _show_saved_tracks(update, context)

    def _get(tid):
        return track_db.get_track(_output_base(), user_id, tid)

    # Меню действий по треку
    if data.startswith("trk_"):
        track_id = data[len("trk_"):]
        trk = _get(track_id)
        if not trk:
            await query.edit_message_text("Трек не найден.")
            return await _show_saved_tracks(update, context)
        title = (trk.get("title") or "трек").strip()
        artist = (trk.get("artist") or "").strip()
        label = f"{artist} — {title}" if artist else title
        buttons = [
            [InlineKeyboardButton("▶️ Открыть", callback_data=f"trkopen_{track_id}")],
            [InlineKeyboardButton("🎬 Перегенерить", callback_data=f"trkgen_{track_id}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"trkdel_{track_id}")],
            [InlineKeyboardButton("⬅ К списку", callback_data="trklist")],
        ]
        info = f"📀 *{label}*\nИсточник: {trk.get('source', '—')}"
        try:
            await query.edit_message_text(info, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await query.edit_message_text(f"📀 {label}", reply_markup=InlineKeyboardMarkup(buttons))
        return WAIT_TRACK_CHOICE

    # Открыть: прислать обложку + аудио + метаданные
    if data.startswith("trkopen_"):
        track_id = data[len("trkopen_"):]
        trk = _get(track_id)
        if not trk or not os.path.exists(trk.get("path", "")):
            await query.edit_message_text("Файл трека не найден на диске.")
            return await _show_saved_tracks(update, context)
        title = (trk.get("title") or "трек").strip()
        artist = (trk.get("artist") or "").strip()
        caption = (f"📀 {artist} — {title}" if artist else f"📀 {title}").strip()
        caption += f"\nИсточник: {trk.get('source', '—')}"
        if trk.get("spotify_url"):
            caption += f"\n{trk['spotify_url']}"
        msg = update.effective_message
        cover = _ensure_cover_local(trk, user_id)
        if cover and os.path.exists(cover):
            try:
                with open(cover, "rb") as f:
                    await msg.reply_photo(photo=f, caption=caption)
            except Exception:
                await msg.reply_text(caption)
        else:
            await msg.reply_text(caption)
        try:
            with open(trk["path"], "rb") as f:
                await msg.reply_audio(audio=f, title=title, performer=artist or None)
        except Exception as e:
            await msg.reply_text(f"Не удалось отправить аудио: {e}")
        return WAIT_TRACK_CHOICE

    # Перегенерить: запустить пайплайн заново (припев → сценарий)
    if data.startswith("trkgen_"):
        track_id = data[len("trkgen_"):]
        trk = _get(track_id)
        if not trk or not os.path.exists(trk.get("path", "")):
            await query.edit_message_text("Файл трека не найден на диске.")
            return await _show_saved_tracks(update, context)
        context.user_data[KEY_PROJECT_DIR] = make_project_dir(user_id)
        context.user_data[KEY_TRACK_ID] = trk["id"]
        context.user_data[KEY_TRACK_NAME] = (trk.get("title") or "трек").strip()
        await query.edit_message_text(f"🎬 Перегенерация: {trk.get('title', 'трек')}")
        return await process_track(update, context, trk["path"])

    # Удалить: подтверждение
    if data.startswith("trkdel_"):
        track_id = data[len("trkdel_"):]
        buttons = [[
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"trkyes_{track_id}"),
            InlineKeyboardButton("⬅ Отмена", callback_data="trklist"),
        ]]
        await query.edit_message_text("Удалить трек безвозвратно?", reply_markup=InlineKeyboardMarkup(buttons))
        return WAIT_TRACK_CHOICE

    if data.startswith("trkyes_"):
        track_id = data[len("trkyes_"):]
        ok = track_db.delete_track(_output_base(), user_id, track_id)
        await query.answer("Удалено" if ok else "Не найдено")
        return await _show_saved_tracks(update, context)

    return WAIT_TRACK_CHOICE


async def _show_saved_choruses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    choruses = chorus_db.list_user_choruses(_output_base(), user_id)

    if not choruses:
        msg_text = "Нет сохранённых припевов. Загрузи трек."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg_text)
        else:
            await update.effective_message.reply_text(msg_text)
        return WAIT_ENTRY

    buttons = []
    for c in choruses[:20]:
        label = f"🎵 {c.get('name', c['id'])[:40]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"chorus_{c['id']}")])
    buttons.append([InlineKeyboardButton("🗑 Удалить все", callback_data="chorus_delete_all")])
    buttons.append([InlineKeyboardButton("⬅ Назад", callback_data="chorus_back")])

    keyboard = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.edit_message_text("Выбери припев:", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text("Выбери припев:", reply_markup=keyboard)
    return WAIT_CHORUS_CHOICE


async def handle_chorus_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "chorus_back":
        return await cmd_start(update, context)

    if query.data == "chorus_delete_all":
        choruses = chorus_db.list_user_choruses(_output_base(), user_id)
        for c in choruses:
            chorus_db.delete_chorus(_output_base(), user_id, c["id"])
        await query.edit_message_text("Все припевы удалены.")
        return await cmd_start(update, context)

    chorus_id = query.data.replace("chorus_", "")
    record = chorus_db.get_chorus(_output_base(), user_id, chorus_id)
    if not record:
        await query.edit_message_text("Припев не найден.")
        return WAIT_ENTRY

    # Восстанавливаем lyrics из JSON
    from modules.types import LyricsLine, WordTiming
    lyrics_lines = []
    for ll in record.get("lyrics", []):
        words = [WordTiming(**w) for w in ll.get("words", [])]
        lyrics_lines.append(LyricsLine(
            text=ll.get("text", ""),
            start=ll.get("start", 0.0),
            end=ll.get("end", 0.0),
            words=words,
        ))

    project_dir = make_project_dir(user_id)
    context.user_data[KEY_PROJECT_DIR] = project_dir
    context.user_data[KEY_CHORUS_PATH] = record["path"]
    context.user_data[KEY_CHORUS_ID] = chorus_id
    context.user_data[KEY_TRACK_ID] = record.get("track_id", "")
    context.user_data[KEY_TRACK_NAME] = record.get("name", "трек")
    context.user_data[KEY_LYRICS_LINES] = lyrics_lines

    await query.edit_message_text(f"📁 Припев: {record.get('name', 'трек')}")
    return await _ask_scenario(update, context)


# ---------------------------------------------------------------------------
# Выбор сценария рендера
# ---------------------------------------------------------------------------
def _build_scenario_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📀 Track Promo (продвижение)", callback_data=f"scenario_{SCENARIO_TRACK_PROMO}")],
        [InlineKeyboardButton("🖼 Cover Alive (обложка+lyrics)", callback_data=f"scenario_{SCENARIO_COVER_ALIVE}")],
        [InlineKeyboardButton("📱 POV Spotify (mockup UI)", callback_data=f"scenario_{SCENARIO_POV_SPOTIFY}")],
        [InlineKeyboardButton("🎤 Караоке", callback_data=f"scenario_{SCENARIO_KARAOKE}")],
        [InlineKeyboardButton("🎞 Mood Slideshow", callback_data=f"scenario_{SCENARIO_SLIDESHOW}")],
    ])


async def _ask_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = _build_scenario_keyboard()
    text = "Выбери формат видео:"
    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_SCENARIO


async def handle_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    scenario = query.data.replace("scenario_", "")
    context.user_data[KEY_SCENARIO] = scenario
    context.user_data[KEY_STYLE] = DEFAULT_STYLE

    if scenario == SCENARIO_KARAOKE:
        return await _ask_karaoke_bg(update, context)
    return await _ask_video_count(update, context)


# ---------------------------------------------------------------------------
# Выбор фона караоке
# ---------------------------------------------------------------------------
async def _ask_karaoke_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📹 Футаж из базы", callback_data=f"kbg_{KARAOKE_BG_FOOTAGE}")],
        [InlineKeyboardButton("✨ Анимированный фон", callback_data=f"kbg_{KARAOKE_BG_ANIMATED}")],
    ])
    text = "Какой фон для караоке?"
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_KARAOKE_BG


async def handle_karaoke_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    bg_type = query.data.replace("kbg_", "")
    context.user_data[KEY_KARAOKE_BG_TYPE] = bg_type
    label = "Футаж" if bg_type == KARAOKE_BG_FOOTAGE else "Анимированный фон"
    await query.edit_message_text(f"Фон: {label}")
    return await _ask_video_count(update, context)


# ---------------------------------------------------------------------------
# Количество видео + ориентация
# ---------------------------------------------------------------------------
async def _ask_video_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="vcount_1"),
            InlineKeyboardButton("2", callback_data="vcount_2"),
            InlineKeyboardButton("3", callback_data="vcount_3"),
        ],
        [
            InlineKeyboardButton("5", callback_data="vcount_5"),
            InlineKeyboardButton("10", callback_data="vcount_10"),
        ],
    ])
    text = "Сколько видео сгенерировать?"
    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_VIDEO_COUNT


async def handle_video_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    count = int(query.data.replace("vcount_", ""))
    context.user_data[KEY_VIDEO_COUNT] = count
    await query.edit_message_text(f"Генерирую {count} видео")
    return await _ask_orientation(update, context)


async def _ask_orientation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Portrait (9:16)", callback_data="orient_portrait"),
            InlineKeyboardButton("🖥 Landscape (16:9)", callback_data="orient_landscape"),
        ],
    ])
    text = "Ориентация видео:"
    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            await update.effective_message.reply_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)
    return WAIT_ORIENTATION


async def handle_orientation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    orient = query.data.replace("orient_", "")
    context.user_data[KEY_ORIENTATION] = orient
    label = "Portrait (9:16)" if orient == "portrait" else "Landscape (16:9)"
    await query.edit_message_text(f"Ориентация: {label}. Запускаю...")
    return await _run_pipeline(update, context)


# ---------------------------------------------------------------------------
# Pipeline: поиск футажей (если нужны) + рендер
# ---------------------------------------------------------------------------
async def _run_with_progress(build_func, kwargs: dict, status_msg, stage_text: str):
    loop = asyncio.get_event_loop()
    start_time = time.time()
    async def _ticker():
        while True:
            await asyncio.sleep(15)
            elapsed = int(time.time() - start_time)
            mins, secs = divmod(elapsed, 60)
            time_str = f"{mins}:{secs:02d}" if mins else f"{secs} сек"
            try:
                await status_msg.edit_text(f"{stage_text}\n⏱ {time_str}...")
            except Exception:
                pass

    ticker_task = asyncio.create_task(_ticker())
    try:
        result = await loop.run_in_executor(None, functools.partial(build_func, **kwargs))
    finally:
        ticker_task.cancel()
    return result


async def _run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    user_data = context.user_data

    project_dir: str = user_data[KEY_PROJECT_DIR]
    chorus_path: str = user_data[KEY_CHORUS_PATH]
    scenario = user_data.get(KEY_SCENARIO, SCENARIO_KARAOKE)
    bg_type = user_data.get(KEY_KARAOKE_BG_TYPE, KARAOKE_BG_FOOTAGE)
    orientation = user_data.get(KEY_ORIENTATION, CONFIG["video"]["orientation"])
    video_count = user_data.get(KEY_VIDEO_COUNT, 1)

    # Mood Slideshow: ищем футажи как для караоке (нужно побольше разных)
    if scenario == SCENARIO_SLIDESHOW:
        status_msg = await msg.reply_text("🔎 Ищу футажи для слайдшоу...")
        all_queries = CONFIG["footage"]["base_queries"]
        track_name = user_data.get(KEY_TRACK_NAME, "")
        all_queries = _try_generate_smart_queries(all_queries, track_description=track_name)
        queries = all_queries[:6]

        footage_dir = os.path.join(project_dir, "footage")
        footage_cache_dir = os.path.join(_output_base(), "_footage_cache")
        try:
            footage_results = await search_and_download(
                queries=queries,
                pixabay_key=get_env("PIXABAY_API_KEY"),
                pexels_key=get_env("PEXELS_API_KEY"),
                output_dir=footage_dir,
                orientation=orientation,
                min_duration=4,
                results_per_query=4,
                cache_dir=footage_cache_dir,
            )
        except Exception as e:
            logger.error(f"Slideshow footage search error: {e}")
            footage_results = {}

        if not footage_results:
            await status_msg.edit_text("Не удалось найти футажи для слайдшоу.")
            return ConversationHandler.END

        bg_videos = _collect_backgrounds(footage_results)
        if not bg_videos:
            await status_msg.edit_text("Нет подходящих футажей.")
            return ConversationHandler.END
        user_data[KEY_BG_VIDEOS] = bg_videos

    # Караоке с футажом: ищем через Pixabay/Pexels
    elif scenario == SCENARIO_KARAOKE and bg_type == KARAOKE_BG_FOOTAGE:
        status_msg = await msg.reply_text("🔎 Ищу футажи...")
        all_queries = CONFIG["footage"]["base_queries"]
        track_name = user_data.get(KEY_TRACK_NAME, "")
        all_queries = _try_generate_smart_queries(all_queries, track_description=track_name)
        queries = all_queries[:5]

        footage_dir = os.path.join(project_dir, "footage")
        from modules.utils import get_media_duration
        chorus_dur = get_media_duration(chorus_path)

        footage_cache_dir = os.path.join(_output_base(), "_footage_cache")
        try:
            footage_results = await search_and_download(
                queries=queries,
                pixabay_key=get_env("PIXABAY_API_KEY"),
                pexels_key=get_env("PEXELS_API_KEY"),
                output_dir=footage_dir,
                orientation=orientation,
                min_duration=max(10, int(chorus_dur) - 5),
                results_per_query=3,
                cache_dir=footage_cache_dir,
            )
        except Exception as e:
            logger.error(f"Footage search error: {e}")
            footage_results = {}

        if not footage_results:
            await status_msg.edit_text("Не удалось найти футажи. Попробуй другой трек.")
            return ConversationHandler.END

        bg_videos = _collect_backgrounds(footage_results)
        user_data[KEY_BG_VIDEOS] = bg_videos
    else:
        user_data[KEY_BG_VIDEOS] = []

    return await _run_pipeline_render(update, context)


async def _run_pipeline_render(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    user_data = context.user_data
    user_id = update.effective_user.id

    project_dir: str = user_data[KEY_PROJECT_DIR]
    chorus_path: str = user_data[KEY_CHORUS_PATH]
    chorus_id: str = user_data.get(KEY_CHORUS_ID, "")
    track_id: str = user_data.get(KEY_TRACK_ID, "")
    orientation = user_data.get(KEY_ORIENTATION, CONFIG["video"]["orientation"])
    lyrics_lines = user_data.get(KEY_LYRICS_LINES, [])
    bg_videos = user_data.get(KEY_BG_VIDEOS, [])
    video_count = user_data.get(KEY_VIDEO_COUNT, 1)
    scenario = user_data.get(KEY_SCENARIO, SCENARIO_KARAOKE)
    bg_type = user_data.get(KEY_KARAOKE_BG_TYPE, KARAOKE_BG_FOOTAGE)
    style_name = user_data.get(KEY_STYLE, DEFAULT_STYLE)
    style = STYLE_PRESETS.get(style_name, STYLE_PRESETS[DEFAULT_STYLE])
    highlight_color = CONFIG.get("karaoke", {}).get("highlight_color", "0xFFD700")

    status_msg = await msg.reply_text(f"🎬 Подготовка видео (0/{video_count})...")

    # Регистрируем задачу в трекере для API
    job = job_tracker.create(
        user_id=user_id,
        scenario=scenario,
        track_name=user_data.get(KEY_TRACK_NAME, ""),
        orientation=orientation,
        total=video_count,
    )
    job_tracker.update(job.job_id, current_phase="rendering", current_message="Рендер запущен")

    videos: list[tuple[str, str, dict]] = []  # (path, label, video_db_meta)
    render_errors: list[str] = []  # причины неудачи — показываем юзеру если 0 видео

    shuffled_bgs = list(bg_videos)
    random.shuffle(shuffled_bgs)

    for vid_num in range(1, video_count + 1):
        job_tracker.update(
            job.job_id, progress=vid_num - 1,
            current_message=f"Рендер видео {vid_num}/{video_count}",
        )
        if video_count > 1:
            try:
                await status_msg.edit_text(f"🎬 Видео {vid_num}/{video_count}...")
            except Exception:
                pass
        iter_dir = os.path.join(project_dir, f"iter_{vid_num}")
        tag = f" [{vid_num}/{video_count}]" if video_count > 1 else ""

        if scenario == SCENARIO_KARAOKE:
            karaoke_dir = os.path.join(iter_dir, "karaoke")
            kwargs = dict(
                lyrics_lines=lyrics_lines,
                background_videos=None,
                chorus_audio_path=chorus_path,
                output_dir=karaoke_dir,
                fonts_dir=CONFIG["paths"]["fonts_dir"],
                orientation=orientation,
                highlight_color=highlight_color,
                style=style,
                use_animated_bg=(bg_type == KARAOKE_BG_ANIMATED),
                palette_seed=vid_num - 1,
            )
            if bg_type == KARAOKE_BG_FOOTAGE and shuffled_bgs:
                kwargs["background_videos"] = [shuffled_bgs[(vid_num - 1) % len(shuffled_bgs)]]

            try:
                karaoke_result = await _run_with_progress(
                    build_karaoke, kwargs, status_msg, f"🎤 Караоке...{tag}",
                )
                if karaoke_result:
                    label = "Караоке (анимированный)" if bg_type == KARAOKE_BG_ANIMATED else "Караоке (футаж)"
                    meta = {"scenario": scenario, "bg_type": bg_type, "orientation": orientation}
                    videos.append((karaoke_result.output_path, f"{label}{tag}", meta))
            except Exception as e:
                logger.error(f"Karaoke error: {e}")
                render_errors.append(f"Караоке: {e}")

        elif scenario == SCENARIO_SLIDESHOW:
            slideshow_dir = os.path.join(iter_dir, "slideshow")
            if not lyrics_lines:
                logger.warning("Slideshow: пустые lyrics_lines")
                await status_msg.edit_text("Нет текста припева для слайдшоу.")
                break
            if not shuffled_bgs:
                await status_msg.edit_text("Нет фоновых футажей.")
                break
            kwargs = dict(
                lyrics_lines=lyrics_lines,
                background_videos=shuffled_bgs,
                chorus_audio_path=chorus_path,
                output_dir=slideshow_dir,
                fonts_dir=CONFIG["paths"]["fonts_dir"],
                orientation=orientation,
                style=style,
                palette_seed=vid_num - 1,
            )
            try:
                slideshow_result = await _run_with_progress(
                    build_slideshow, kwargs, status_msg, f"🎞 Mood Slideshow...{tag}",
                )
                if slideshow_result:
                    meta = {"scenario": scenario, "bg_type": "slideshow", "orientation": orientation}
                    videos.append((slideshow_result.output_path, f"Mood Slideshow{tag}", meta))
            except Exception as e:
                logger.error(f"Slideshow error: {e}")
                render_errors.append(f"Slideshow: {e}")

        elif scenario == SCENARIO_TRACK_PROMO:
            # Track Promo — главный формат продвижения ноунейм-трека.
            # 4 акта: hook → chorus kinetic → cover reveal → CTA.
            from modules.bundle_track_promo import build_track_promo, TrackPromoConfig
            from modules.cta_overlay import build_utm_link

            promo_dir = os.path.join(iter_dir, "track_promo")
            os.makedirs(promo_dir, exist_ok=True)
            output_mp4_p = os.path.join(promo_dir, "final.mp4")
            font_path = os.path.join(CONFIG["paths"]["fonts_dir"], "Montserrat-Bold.ttf")

            # Метаданные трека ИЗ track_db (обогащены при скачивании/загрузке).
            # Больше не угадываем через search — если в track_db не записано → честно Unknown.
            cover_path_p = None
            artist_name_p = ""
            spotify_url_p = ""
            track_name_p = user_data.get(KEY_TRACK_NAME, "").replace(" (audio)", "").replace(" (text)", "")
            try:
                if track_id:
                    trk = track_db.get_track(_output_base(), user_id, track_id)
                    if trk:
                        artist_name_p = (trk.get("artist") or "").strip()
                        if trk.get("title"):
                            track_name_p = trk["title"]
                        spotify_url_p = (trk.get("spotify_url") or "").strip()
                        cover_path_p = _ensure_cover_local(trk, user_id)
                        logger.info(
                            f"track_promo/db: {artist_name_p} — {track_name_p} "
                            f"(cover={bool(cover_path_p)} spotify={bool(spotify_url_p)})"
                        )
            except Exception as _e:
                logger.debug(f"track_promo: track_db lookup skipped: {_e}")

            # Длина припева
            try:
                from modules.utils import get_media_duration
                chorus_dur_p = get_media_duration(chorus_path)
            except Exception:
                chorus_dur_p = 21.0
            if chorus_dur_p <= 0:
                chorus_dur_p = 21.0

            # Варьируем promo-параметры на vid_num для batch
            palette_names_p = ["sad-girl", "trap", "dark", "dream-pop", "default"]
            palette_name_p = palette_names_p[(vid_num - 1) % len(palette_names_p)]
            hook_phrases_p = [
                "this song will ruin you",
                "why is nobody talking about this",
                "you need to hear this",
                "I'm gatekeeping this",
                "POV: your new favorite song",
                "don't scroll past this",
                "this one hits different",
            ]
            hook_phrase_p = hook_phrases_p[(vid_num - 1) % len(hook_phrases_p)]
            cta_texts_p = [
                "save this before it blows up",
                "add to your playlist now",
                "press play and thank me later",
                "full track → link in bio",
            ]
            cta_p = cta_texts_p[(vid_num - 1) % len(cta_texts_p)]

            # UTM-линка для этого конкретного варианта
            if spotify_url_p:
                utm_url = build_utm_link(
                    spotify_url_p,
                    f"promo-{vid_num:02d}",
                    platform="tiktok",
                )
            else:
                utm_url = ""

            cfg_p = TrackPromoConfig(
                audio_path=chorus_path,
                lyrics=lyrics_lines,
                output_path=output_mp4_p,
                font_path=font_path,
                duration=min(chorus_dur_p, 21.0),
                track_name=track_name_p or "Unknown Track",
                artist_name=artist_name_p or "Unknown Artist",
                cover_path=cover_path_p,
                spotify_url=utm_url,
                palette_name=palette_name_p,
                hook_phrase=hook_phrase_p,
                cta_text=cta_p,
            )

            try:
                def _render_promo_wrapper(**kw):
                    build_track_promo(cfg_p)
                    class _R:
                        output_path = output_mp4_p
                    return _R()
                promo_result = await _run_with_progress(
                    _render_promo_wrapper, {}, status_msg,
                    f"📀 Track Promo ({palette_name_p}){tag}",
                )
                if promo_result:
                    meta = {
                        "scenario": scenario,
                        "bg_type": "promo_cover",
                        "orientation": orientation,
                        "palette": palette_name_p,
                        "hook_phrase": hook_phrase_p,
                        "cta_text": cta_p,
                        "has_cover": bool(cover_path_p),
                        "artist_name": artist_name_p,
                        "track_name": track_name_p,
                        "spotify_url": utm_url,
                    }
                    videos.append((
                        promo_result.output_path,
                        f"Track Promo {palette_name_p}{tag}", meta,
                    ))
            except Exception as e:
                logger.error(f"Track Promo error: {e}", exc_info=True)
                render_errors.append(f"Track Promo: {e}")

        elif scenario == SCENARIO_COVER_ALIVE:
            # Cover Alive: cover art parallax + kinetic lyrics поверх
            from modules.bundle_cover_alive import build_cover_alive, CoverAliveConfig

            ca_dir = os.path.join(iter_dir, "cover_alive")
            os.makedirs(ca_dir, exist_ok=True)
            output_mp4_ca = os.path.join(ca_dir, "final.mp4")
            font_path_ca = os.path.join(CONFIG["paths"]["fonts_dir"], "Montserrat-Bold.ttf")

            # Метаданные + cover из track_db. _ensure_cover_local попробует
            # перекачать обложку если cover_local_path пропал с диска.
            cover_path_ca = None
            artist_name_ca = ""
            track_name_ca = user_data.get(KEY_TRACK_NAME, "")
            try:
                if track_id:
                    trk = track_db.get_track(_output_base(), user_id, track_id)
                    if trk:
                        artist_name_ca = (trk.get("artist") or "").strip()
                        if trk.get("title"):
                            track_name_ca = trk["title"]
                        cover_path_ca = _ensure_cover_local(trk, user_id)
            except Exception as _e:
                logger.debug(f"cover_alive: track_db lookup: {_e}")

            if not cover_path_ca:
                await status_msg.edit_text(
                    "🖼 Cover Alive требует обложку трека.\n"
                    "Загрузи трек через '🎤 Spotify артист' или mp3 с ID3 тегами."
                )
                render_errors.append("Cover Alive: нет обложки трека")
                continue

            try:
                from modules.utils import get_media_duration
                dur_ca = get_media_duration(chorus_path)
            except Exception:
                dur_ca = 21.0
            if dur_ca <= 0:
                dur_ca = 21.0

            palettes_ca = ["sad-girl", "trap", "dark", "dream-pop", "default"]
            palette_ca = palettes_ca[(vid_num - 1) % len(palettes_ca)]

            cfg_ca = CoverAliveConfig(
                audio_path=chorus_path, lyrics=lyrics_lines,
                output_path=output_mp4_ca, font_path=font_path_ca,
                duration=min(dur_ca, 21.0),
                track_name=track_name_ca or "Unknown Track",
                artist_name=artist_name_ca or "Unknown Artist",
                cover_path=cover_path_ca,
                palette_name=palette_ca,
            )

            try:
                def _render_ca_wrap(**kw):
                    build_cover_alive(cfg_ca)
                    class _R:
                        output_path = output_mp4_ca
                    return _R()
                ca_result = await _run_with_progress(
                    _render_ca_wrap, {}, status_msg,
                    f"🖼 Cover Alive ({palette_ca}){tag}",
                )
                if ca_result:
                    videos.append((
                        ca_result.output_path,
                        f"Cover Alive {palette_ca}{tag}",
                        {"scenario": scenario, "palette": palette_ca, "orientation": orientation,
                         "artist_name": artist_name_ca, "track_name": track_name_ca},
                    ))
            except Exception as e:
                logger.error(f"Cover Alive error: {e}", exc_info=True)
                render_errors.append(f"Cover Alive: {e}")

        elif scenario == SCENARIO_POV_SPOTIFY:
            # POV Spotify — mockup интерфейса Spotify, топовый виральный формат
            from modules.bundle_pov_spotify import build_pov_spotify, POVSpotifyConfig

            pov_dir = os.path.join(iter_dir, "pov_spotify")
            os.makedirs(pov_dir, exist_ok=True)
            output_mp4_pov = os.path.join(pov_dir, "final.mp4")
            font_path_pov = os.path.join(CONFIG["paths"]["fonts_dir"], "Montserrat-Bold.ttf")

            cover_path_pov = None
            artist_name_pov = ""
            track_name_pov = user_data.get(KEY_TRACK_NAME, "")
            try:
                if track_id:
                    trk = track_db.get_track(_output_base(), user_id, track_id)
                    if trk:
                        artist_name_pov = (trk.get("artist") or "").strip()
                        if trk.get("title"):
                            track_name_pov = trk["title"]
                        cover_path_pov = _ensure_cover_local(trk, user_id)
            except Exception as _e:
                logger.debug(f"pov_spotify: track_db: {_e}")

            if not cover_path_pov:
                await status_msg.edit_text(
                    "📱 POV Spotify требует обложку. Загрузи трек через Spotify URL."
                )
                render_errors.append("POV Spotify: нет обложки трека")
                continue

            try:
                from modules.utils import get_media_duration
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

            cfg_pov = POVSpotifyConfig(
                audio_path=chorus_path, lyrics=lyrics_lines,
                output_path=output_mp4_pov, font_path=font_path_pov,
                duration=min(dur_pov, 21.0),
                track_name=track_name_pov or "Unknown Track",
                artist_name=artist_name_pov or "Unknown Artist",
                cover_path=cover_path_pov,
                palette_name=palette_pov,
                hook_phrase=hook_pov,
            )

            try:
                def _render_pov_wrap(**kw):
                    build_pov_spotify(cfg_pov)
                    class _R:
                        output_path = output_mp4_pov
                    return _R()
                pov_result = await _run_with_progress(
                    _render_pov_wrap, {}, status_msg,
                    f"📱 POV Spotify ({palette_pov}){tag}",
                )
                if pov_result:
                    videos.append((
                        pov_result.output_path,
                        f"POV Spotify {palette_pov}{tag}",
                        {"scenario": scenario, "palette": palette_pov, "orientation": orientation,
                         "artist_name": artist_name_pov, "track_name": track_name_pov,
                         "hook_phrase": hook_pov},
                    ))
            except Exception as e:
                logger.error(f"POV Spotify error: {e}", exc_info=True)
                render_errors.append(f"POV Spotify: {e}")

    if not videos:
        reason = " | ".join(render_errors[:3]) if render_errors else "неизвестная ошибка рендера"
        job_tracker.fail(job.job_id, f"Не удалось создать видео: {reason}")
        await status_msg.edit_text(f"❌ Не удалось создать видео.\n\nПричина: {reason}")
        # Если есть очередь Spotify — пробуем следующий трек
        if context.user_data.get(KEY_PENDING_TRACKS):
            return await _process_next_pending_track(update, context)
        return ConversationHandler.END

    job_tracker.update(job.job_id, current_phase="uploading", current_message="Отправка видео в Telegram")
    await status_msg.edit_text("📤 Отправляю видео...")

    TG_MAX_SIZE = 49 * 1024 * 1024

    for i, (path, label, meta) in enumerate(videos):
        if not os.path.exists(path):
            continue

        send_path = path
        if os.path.getsize(path) > TG_MAX_SIZE:
            compressed = path.replace(".mp4", "_compressed.mp4")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", path,
                     "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                     "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "128k",
                     "-movflags", "+faststart", compressed],
                    capture_output=True, timeout=120,
                )
                if os.path.exists(compressed) and os.path.getsize(compressed) < TG_MAX_SIZE:
                    send_path = compressed
                else:
                    logger.warning(f"Пережатие не помогло: {path}")
                    continue
            except Exception as e:
                logger.warning(f"Ошибка пережатия {path}: {e}")
                continue

        # Сохраняем в video_db
        try:
            video_db.save_video(
                output_base=_output_base(),
                user_id=user_id,
                src_path=send_path,
                chorus_id=chorus_id,
                track_id=track_id,
                scenario=meta.get("scenario", ""),
                bg_type=meta.get("bg_type", ""),
                orientation=meta.get("orientation", "portrait"),
            )
        except Exception as e:
            logger.warning(f"video_db save failed: {e}")

        caption = f"{label} {i + 1}/{len(videos)}"
        file_size_mb = os.path.getsize(send_path) / (1024 * 1024)
        logger.info(f"Отправка видео {send_path} ({file_size_mb:.1f} МБ)")
        try:
            with open(send_path, "rb") as f:
                await msg.reply_video(
                    video=f, caption=caption, supports_streaming=True,
                    read_timeout=300, write_timeout=300, connect_timeout=60,
                )
        except Exception as e:
            logger.error(f"Ошибка отправки {send_path} ({file_size_mb:.1f} МБ): {e}")
            # Попробуем как документ
            try:
                with open(send_path, "rb") as f:
                    await msg.reply_document(
                        document=f, caption=caption,
                        read_timeout=300, write_timeout=300,
                    )
            except Exception as e2:
                logger.error(f"Ошибка отправки документом: {e2}")

    video_db.cleanup_old(_output_base(), user_id, max_videos=100)
    job_tracker.complete(job.job_id, results=[{"video": label} for _, label, _ in videos])

    # Если есть очередь Spotify-треков — продолжаем
    if context.user_data.get(KEY_PENDING_TRACKS):
        await msg.reply_text(
            f"⏭ Осталось {len(context.user_data[KEY_PENDING_TRACKS])} треков из Spotify-плейлиста..."
        )
        return await _process_next_pending_track(update, context)

    await msg.reply_text("✅ Готово! /start — начать заново.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Служебные команды
# ---------------------------------------------------------------------------
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено. /start — начать заново.")
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Нет доступа.")
        return
    output_dir = Path(_output_base())
    if not output_dir.exists():
        await update.message.reply_text("output пуст.")
        return
    user_dirs = [d for d in output_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
    total_size_mb = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file()) / (1024 * 1024)
    total_tracks = sum(len(track_db.list_user_tracks(_output_base(), int(d.name))) for d in user_dirs if d.name.isdigit())
    total_choruses = sum(len(chorus_db.list_user_choruses(_output_base(), int(d.name))) for d in user_dirs if d.name.isdigit())
    total_videos = sum(len(video_db.list_user_videos(_output_base(), int(d.name), limit=10000)) for d in user_dirs if d.name.isdigit())
    await update.message.reply_text(
        f"📊 Статистика:\n"
        f"  Пользователей: {len(user_dirs)}\n"
        f"  Треков: {total_tracks}\n"
        f"  Припевов: {total_choruses}\n"
        f"  Видео: {total_videos}\n"
        f"  Размер: {total_size_mb:.1f} МБ"
    )


async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Нет доступа.")
        return
    max_days = CONFIG.get("cleanup", {}).get("session_max_age_days", 7)
    await update.message.reply_text(f"Очищаю сессии старше {max_days} дней...")
    users, total = _cleanup_all_users()
    await update.message.reply_text(f"Очищено: пользователей {users}, сессий {total}")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def _startup_cleanup():
    """Очистка при старте: удаляем старые сессии и кэш футажей."""
    import shutil
    output_dir = Path(_output_base())
    # Удаляем все сессии (uuid-папки) — они временные
    if output_dir.exists():
        for user_dir in output_dir.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("_"):
                continue
            for session_dir in user_dir.iterdir():
                if session_dir.is_dir() and not session_dir.name.startswith("_"):
                    shutil.rmtree(session_dir, ignore_errors=True)
    # Удаляем кэш футажей
    cache_dir = output_dir / "_footage_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    logger.info("Startup cleanup done")


def _start_api_server():
    """Запускает FastAPI сервер в отдельном потоке."""
    import threading
    import uvicorn

    def run():
        port = settings.api_port
        uvicorn.run("api_server:app", host=settings.api_host, port=port, log_level="info")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.info(f"API сервер запущен на порту {settings.api_port}")


def _upgrade_ytdlp():
    """Обновляем yt-dlp до nightly с GitHub (PyPI версия часто отстаёт)."""
    try:
        result = subprocess.run(
            ["pip", "install", "--force-reinstall", "--no-deps",
             settings.yt_dlp_upgrade_url],
            capture_output=True, text=True, timeout=120,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                logger.info(f"yt-dlp upgrade: {line.strip()}")
        if result.returncode != 0:
            logger.warning(f"yt-dlp upgrade stderr: {result.stderr[-300:]}")
    except Exception as e:
        logger.warning(f"yt-dlp upgrade failed: {e}")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Глобальный обработчик ошибок: пишет полный traceback в лог и сообщает
    пользователю, что упало. Без него падение любого хендлера было «тихим»
    (PTB логировал, но в чат ничего не приходило).
    """
    logger.exception("Необработанная ошибка в хендлере", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            err = context.error
            await update.effective_message.reply_text(
                f"⚠️ Внутренняя ошибка: {type(err).__name__}: {err}\n"
                "Попробуй ещё раз или нажми /start."
            )
    except Exception:
        pass


def main() -> None:
    if not check_ffmpeg():
        raise SystemExit("ffmpeg/ffprobe не найдены.")
    _upgrade_ytdlp()
    _startup_cleanup()
    _start_api_server()

    token = get_env("TELEGRAM_BOT_TOKEN")
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        read_timeout=120,
        write_timeout=120,
        connect_timeout=30,
    )
    app = Application.builder().token(token).request(request).concurrent_updates(True).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        per_message=False,
        states={
            WAIT_ENTRY: [
                CallbackQueryHandler(handle_entry_choice, pattern="^entry_"),
            ],
            WAIT_AUDIO: [
                MessageHandler(
                    filters.AUDIO | filters.VOICE | filters.Document.ALL,
                    handle_audio,
                ),
            ],
            WAIT_SPOTIFY_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spotify_link),
                CallbackQueryHandler(handle_spotify_source, pattern="^src_"),
            ],
            WAIT_CHORUS_CHOICE: [
                CallbackQueryHandler(handle_chorus_choice, pattern="^chorus_"),
            ],
            WAIT_CUT_MODE: [
                CallbackQueryHandler(handle_cut_mode, pattern="^cut_"),
            ],
            WAIT_TEXT_FRAGMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_fragment),
            ],
            WAIT_SECONDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seconds),
            ],
            WAIT_CHORUS_PICK: [
                CallbackQueryHandler(handle_chorus_pick, pattern="^pick_"),
            ],
            WAIT_SCENARIO: [
                CallbackQueryHandler(handle_scenario, pattern="^scenario_"),
            ],
            WAIT_KARAOKE_BG: [
                CallbackQueryHandler(handle_karaoke_bg, pattern="^kbg_"),
            ],
            WAIT_VIDEO_COUNT: [
                CallbackQueryHandler(handle_video_count, pattern="^vcount_"),
            ],
            WAIT_ORIENTATION: [
                CallbackQueryHandler(handle_orientation, pattern="^orient_"),
            ],
            WAIT_TRACK_CHOICE: [
                CallbackQueryHandler(handle_track_action, pattern="^trk"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("cleanup", cmd_cleanup))
    app.add_error_handler(on_error)

    # Запускаем API-воркер в event loop бота
    async def post_init(application):
        # Восстанавливаем персистентные задачи ДО старта воркера: очередь
        # in-memory, иначе нетерминальные задачи зависли бы в "running" навсегда.
        from modules.api_worker import reconcile_persisted_jobs
        try:
            restored = reconcile_persisted_jobs()
            if restored:
                logger.info(f"Reconcile: {restored} задач(и) перезапущены после рестарта")
        except Exception:
            logger.exception("Reconcile персистентных задач не удался")
        asyncio.create_task(api_worker_loop(CONFIG))
        logger.info("API worker запущен")

    app.post_init = post_init
    logger.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
