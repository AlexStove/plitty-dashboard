"""
Audio Fingerprint — идентификация трека по звуку через Shazam.

Root-cause fix бага "TommyMuzzic для трека Strangers":
  - Раньше при отсутствии ID3 тегов мы делали слепой search по названию
    файла → Spotify возвращал РАНДОМНЫЙ первый результат
  - Теперь: если ID3 пустые и имя файла не-structured — снимаем 10 секунд
    аудио, шазамим → получаем точного артиста/трек/ISRC → ищем в Spotify
    по ISRC (гарантированно правильный трек)

Использует shazamio (unofficial Shazam API, без ключей, ~1-2 req/s).

Fallback chain:
  1. ID3 теги mp3 (надёжнее всего, instant)
  2. Filename "Artist - Title" (если есть разделитель)
  3. Shazam по audio fingerprint (10с сэмпл, 2-5 сек латентность)
  4. Честное "Unknown Artist" (не угадываем)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ShazamResult:
    title: str = ""
    artist: str = ""
    album: str = ""
    isrc: str = ""                  # Уникальный track ID, позволяет точно найти в Spotify
    cover_url: str = ""
    genre: str = ""
    release_date: str = ""
    confidence: float = 0.0         # 0.0-1.0 (Shazam не даёт напрямую, используем proxy)

    def as_dict(self) -> dict:
        return asdict(self)


def _extract_sample(mp3_path: str, duration_sec: float = 10.0, offset_sec: float = 15.0) -> Optional[str]:
    """
    Вырезает 10-секундный сэмпл для шазам-запроса.
    offset_sec=15: пропускаем intro, берём из середины.
    Возвращает путь к tmp .ogg файлу (Shazamio требует аудио-формат).
    """
    if not os.path.exists(mp3_path):
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    tmp.close()
    try:
        # Shazamio может шазамить из raw PCM, но .ogg надёжнее
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{offset_sec:.2f}",
             "-t", f"{duration_sec:.2f}",
             "-i", mp3_path,
             "-ac", "1", "-ar", "44100",
             "-c:a", "libvorbis", "-b:a", "128k",
             tmp.name],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0 or os.path.getsize(tmp.name) < 1024:
            os.unlink(tmp.name)
            return None
        return tmp.name
    except Exception as e:
        logger.debug(f"extract sample failed: {e}")
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return None


async def _shazam_async(sample_path: str) -> Optional[dict]:
    """Вызов Shazamio. Возвращает raw dict или None."""
    try:
        from shazamio import Shazam
    except ImportError:
        logger.warning("shazamio не установлен")
        return None
    try:
        sh = Shazam()
        result = await sh.recognize(sample_path)
        return result
    except Exception as e:
        logger.warning(f"shazam recognize failed: {e}")
        return None


def _parse_shazam(raw: dict) -> Optional[ShazamResult]:
    """Вытаскивает из Shazam-response наши поля."""
    if not raw or not isinstance(raw, dict):
        return None
    track = raw.get("track") or {}
    if not track:
        return None
    r = ShazamResult()
    r.title = (track.get("title") or "").strip()
    r.artist = (track.get("subtitle") or "").strip()
    # ISRC обычно в sections/metapages
    sections = track.get("sections") or []
    for sec in sections:
        meta = sec.get("metadata") or []
        for m in meta:
            if (m.get("title") or "").lower() in ("album", "альбом"):
                r.album = (m.get("text") or "").strip()
            if (m.get("title") or "").lower() in ("released", "дата выхода"):
                r.release_date = (m.get("text") or "").strip()
    # ISRC
    hub = track.get("hub") or {}
    for provider in hub.get("providers") or []:
        # Ищем в providers — Apple Music / Spotify обычно содержит ISRC
        actions = provider.get("actions") or []
        for act in actions:
            isrc = act.get("isrc") or ""
            if isrc:
                r.isrc = isrc
                break
    # isrc может быть в images или непосредственно
    if not r.isrc:
        r.isrc = track.get("isrc", "") or ""
    # Genre
    genres = track.get("genres") or {}
    r.genre = genres.get("primary", "") or ""
    # Cover URL
    imgs = track.get("images") or {}
    r.cover_url = imgs.get("coverart") or imgs.get("coverarthq") or ""

    # Confidence: у Shazam нет прямого score, используем proxy —
    # если title+artist+isrc все есть, confidence 0.95; без isrc — 0.80
    score = 0.0
    if r.title:
        score += 0.35
    if r.artist:
        score += 0.35
    if r.isrc:
        score += 0.20
    if r.album:
        score += 0.10
    r.confidence = score
    return r if (r.title and r.artist) else None


def identify(mp3_path: str, sample_offset: float = 15.0) -> Optional[ShazamResult]:
    """
    Главная точка входа. Синхронный wrapper над async Shazam.
    Возвращает ShazamResult с artist/title/isrc или None.
    """
    sample = _extract_sample(mp3_path, duration_sec=10.0, offset_sec=sample_offset)
    if not sample:
        logger.debug(f"audio_fingerprint: не удалось вырезать сэмпл из {mp3_path}")
        return None
    try:
        # Async call из sync context. В Python 3.12+ get_event_loop() вне
        # running loop → DeprecationWarning. Пробуем running loop, иначе
        # asyncio.run() создаёт свой.
        try:
            asyncio.get_running_loop()
            # Уже в event loop (например, вызов из async) — asyncio.run нельзя,
            # запускаем в отдельном thread-executor.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(asyncio.run, _shazam_async(sample))
                raw = fut.result(timeout=30)
        except RuntimeError:
            # Нет running loop — создаём свой
            raw = asyncio.run(_shazam_async(sample))
        result = _parse_shazam(raw)
        if result:
            logger.info(
                f"shazam: '{result.artist} — {result.title}' "
                f"(isrc={result.isrc or '?'}, confidence={result.confidence:.2f})"
            )
        else:
            logger.info(f"shazam: не распознал {os.path.basename(mp3_path)}")
        return result
    finally:
        try:
            os.unlink(sample)
        except OSError:
            pass


def isrc_to_spotify_url(isrc: str) -> Optional[str]:
    """
    Находит Spotify-URL по ISRC.
    ISRC = уникальный международный code трека → в Spotify есть 100% match.
    """
    if not isrc:
        return None
    try:
        from .spotify_cover_fetcher import _get_spotify_client
        sp = _get_spotify_client()
        if not sp:
            return None
        res = sp.search(q=f"isrc:{isrc}", type="track", limit=1)
        items = ((res or {}).get("tracks") or {}).get("items") or []
        if items:
            return (items[0].get("external_urls") or {}).get("spotify", "")
    except Exception as e:
        logger.debug(f"isrc search failed: {e}")
    return None
