"""
Spotify Cover Fetcher — скачивает обложку трека + audio features.

Фундамент продвижения ноунейм-трека: зритель должен ВИДЕТЬ обложку, имя и
артиста на экране ≥5 секунд крупно. Этот модуль добывает эти данные из
Spotify Web API (client credentials flow, бесплатно, без OAuth).

Возвращает:
  - cover.jpg (640x640) — кэшируется локально
  - audio_features: {valence, energy, key, tempo, danceability, acousticness,
                      instrumentalness, liveness, speechiness, mode, time_signature}
  - artist_name, track_name, release_date, popularity, spotify_url

Использует existing SPOTIFY_CLIENT_ID/SECRET из .env (spotify_loader уже их читает).
"""

from __future__ import annotations

import logging
import os
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class SpotifyTrackPack:
    """Всё что знаем о треке — для rendering и router."""
    track_id: str
    track_name: str = ""
    artist_name: str = ""
    album_name: str = ""
    release_date: str = ""
    popularity: int = 0
    spotify_url: str = ""
    cover_url: str = ""
    cover_local_path: str = ""          # локальный файл jpg
    # Audio Features (Spotify ML-derived, 0-1 нормализованы)
    valence: float = 0.5                # 0=sad, 1=happy
    energy: float = 0.5
    danceability: float = 0.5
    acousticness: float = 0.5
    instrumentalness: float = 0.5
    liveness: float = 0.5
    speechiness: float = 0.5
    mode: int = 1                       # 0=minor, 1=major
    key: int = -1                       # -1 = unknown, 0=C ... 11=B
    key_name: str = ""                  # "C#", "F"... (human readable)
    tempo: float = 0.0                  # BPM
    time_signature: int = 4
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# MIDI note → human-readable key name
_KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _get_spotify_client():
    """Lazy spotipy client с client_credentials flow."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError:
        logger.error("spotipy не установлен. pip install spotipy")
        return None

    cid = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    csec = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        logger.warning("SPOTIFY_CLIENT_ID/SECRET не заданы")
        return None

    try:
        auth = SpotifyClientCredentials(client_id=cid, client_secret=csec)
        sp = spotipy.Spotify(auth_manager=auth)
        return sp
    except Exception as e:
        logger.error(f"Spotify auth failed: {e}")
        return None


def _extract_track_id(spotify_ref: str) -> Optional[str]:
    """
    Принимает:
      - spotify:track:4iV5W9...
      - https://open.spotify.com/track/4iV5W9...
      - 4iV5W9...           (сам ID)
    Возвращает чистый ID или None.
    """
    s = (spotify_ref or "").strip()
    if not s:
        return None
    if "spotify:track:" in s:
        return s.split("spotify:track:")[-1].split("?")[0].strip()
    if "open.spotify.com/track/" in s:
        part = s.split("open.spotify.com/track/")[-1]
        return part.split("?")[0].split("/")[0].strip()
    # Raw ID — 22 символа base62
    if len(s) == 22 and s.replace("_", "").replace("-", "").isalnum():
        return s
    return None


def _download_cover(url: str, dst: str) -> bool:
    """Скачивает JPG/PNG по URL. Возвращает True если сохранился >1KB."""
    if not url:
        return False
    dst_path = Path(dst)
    if dst_path.exists() and dst_path.stat().st_size > 1024:
        return True
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            tmp = dst_path.with_suffix(dst_path.suffix + ".tmp")
            with open(tmp, "wb") as f:
                while chunk := resp.read(65536):
                    f.write(chunk)
            tmp.rename(dst_path)
        return dst_path.stat().st_size > 1024
    except Exception as e:
        logger.error(f"cover download failed: {e}")
        return False


def extract_id3_metadata(mp3_path: str) -> dict:
    """
    Читает ID3 теги из mp3 (artist, title, album) — mutagen.
    Возвращает {} если файл без тегов или mutagen не установлен.
    Это самый надёжный источник — не требует сети и не угадывает.
    """
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return {}
    if not mp3_path or not os.path.exists(mp3_path):
        return {}
    try:
        audio = MutagenFile(mp3_path, easy=True)
        if audio is None:
            return {}
        out: dict = {}
        for tag_in, tag_out in [
            ("artist", "artist"),
            ("title", "title"),
            ("album", "album"),
            ("date", "date"),
        ]:
            vals = audio.get(tag_in)
            if vals:
                v = vals[0] if isinstance(vals, list) else vals
                if isinstance(v, str) and v.strip():
                    out[tag_out] = v.strip()
        return out
    except Exception as e:
        logger.debug(f"id3 extract failed: {e}")
        return {}


def parse_filename_metadata(file_or_name: str) -> dict:
    """
    Пытается разобрать "Artist - Title.mp3" или "Artist — Title.mp3".
    Возвращает {artist, title} или {}.
    """
    if not file_or_name:
        return {}
    name = os.path.basename(file_or_name)
    name = os.path.splitext(name)[0]
    # Чистим типовые suffixes
    import re
    name = re.sub(r"\s*\(official.*?\)\s*", " ", name, flags=re.I)
    name = re.sub(r"\s*\[official.*?\]\s*", " ", name, flags=re.I)
    name = re.sub(r"\s*\((audio|text|lyrics|hd|hq)\)\s*", " ", name, flags=re.I)
    # Разделитель: " - " или " — "
    for sep in [" - ", " — ", " – "]:
        if sep in name:
            parts = name.split(sep, 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                return {"artist": parts[0].strip(), "title": parts[1].strip()}
    return {}


def search_track(query: str, artist: str = "", limit: int = 3) -> Optional[str]:
    """
    Ищет трек в Spotify. Если artist известен — ТОЧНЫЙ поиск
    `artist:X track:Y`, иначе свободный (менее надёжный).

    Возвращает первый URL или None.
    """
    sp = _get_spotify_client()
    if sp is None:
        return None
    import re
    q = query or ""
    q = re.sub(r"\([^)]*\)", " ", q)
    q = re.sub(r"\[[^\]]*\]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if len(q) < 2:
        return None

    if artist and len(artist.strip()) >= 2:
        # Точный поиск по artist+track — исключает случайные совпадения
        full_q = f'artist:"{artist.strip()}" track:"{q}"'
    else:
        full_q = q

    try:
        res = sp.search(q=full_q, type="track", limit=limit)
        items = ((res or {}).get("tracks") or {}).get("items") or []
        if items:
            return (items[0].get("external_urls") or {}).get("spotify", "")
        # Если точный поиск не дал — пробуем свободный (но только если artist был задан)
        if artist:
            res = sp.search(q=q, type="track", limit=limit)
            items = ((res or {}).get("tracks") or {}).get("items") or []
            if items:
                return (items[0].get("external_urls") or {}).get("spotify", "")
    except Exception as e:
        logger.debug(f"search failed: {e}")
    return None


def enrich_from_file(
    mp3_path: str,
    output_base: str,
    user_id: int,
    hint_artist: str = "",
    hint_title: str = "",
    use_shazam_fallback: bool = True,
) -> Optional[SpotifyTrackPack]:
    """
    Главная точка обогащения ТРЕКА при его сохранении.

    Стратегия (в порядке надёжности):
      1. ID3 теги mp3 + artist+title → точный Spotify search
      2. Filename "Artist - Title.mp3" + title → точный Spotify search
      3. Переданные hint_artist/hint_title (из UI) → точный search
      4. [NEW] Shazam audio fingerprint → ISRC → 100% match в Spotify
      5. Если нет артиста, но есть title → свободный поиск (последний вариант)

    Возвращает SpotifyTrackPack с cover + track URL, или None.
    """
    # Уровни 1-3: собираем best known metadata
    id3 = extract_id3_metadata(mp3_path)
    fn = parse_filename_metadata(mp3_path)

    artist = (id3.get("artist") or fn.get("artist") or hint_artist or "").strip()
    title = (id3.get("title") or fn.get("title") or hint_title or "").strip()

    # Если artist известен и title известен — точный поиск (самый надёжный)
    if artist and title:
        found_url = search_track(title, artist=artist, limit=3)
        if found_url:
            logger.info(f"enrich: по ID3/filename → {artist} — {title}")
            return fetch_track_pack(found_url, output_base, user_id)

    # Уровень 4: Shazam fingerprint (если artist не известен или search пустой)
    if use_shazam_fallback and not artist:
        logger.info(f"enrich: нет артиста, пробую Shazam fingerprint для {os.path.basename(mp3_path)}")
        try:
            from .audio_fingerprint import identify, isrc_to_spotify_url
            shz = identify(mp3_path)
            if shz and shz.artist and shz.title:
                # ISRC path — 100% точный match если есть
                if shz.isrc:
                    isrc_url = isrc_to_spotify_url(shz.isrc)
                    if isrc_url:
                        logger.info(
                            f"enrich: Shazam+ISRC → {shz.artist} — {shz.title} "
                            f"(ISRC {shz.isrc})"
                        )
                        return fetch_track_pack(isrc_url, output_base, user_id)
                # Иначе — обычный search но теперь с ПРАВИЛЬНЫМ артистом
                found_url = search_track(shz.title, artist=shz.artist, limit=3)
                if found_url:
                    logger.info(f"enrich: Shazam search → {shz.artist} — {shz.title}")
                    return fetch_track_pack(found_url, output_base, user_id)
        except Exception as e:
            logger.warning(f"shazam fallback failed: {e}")

    # Уровень 5: free-form search (ненадёжный — может вернуть случайный трек!)
    if title:
        found_url = search_track(title, artist="", limit=3)
        if found_url:
            logger.warning(
                f"enrich: FREE-form search → {title} — результат может быть неточным"
            )
            return fetch_track_pack(found_url, output_base, user_id)

    logger.info(f"enrich: не смогли идентифицировать {mp3_path}")
    return None


def fetch_track_pack(
    spotify_ref: str,
    output_base: str,
    user_id: int,
    cache: bool = True,
    fallback_query: str = "",
) -> Optional[SpotifyTrackPack]:
    """
    Главная точка входа.
    Args:
        spotify_ref: URL/URI/ID трека.
        output_base: корень output/ — туда кладётся covers/<id>.jpg.
        user_id: id юзера для per-user изоляции.
        cache: если True и cover уже скачан — не перекачиваем.
    Returns:
        SpotifyTrackPack или None при ошибке.
    """
    track_id = _extract_track_id(spotify_ref)
    # Fallback: если ref не дал track_id, пробуем поиск по fallback_query
    if not track_id and fallback_query:
        logger.info(f"no track_id, searching by '{fallback_query}'")
        found_url = search_track(fallback_query, limit=1)
        if found_url:
            track_id = _extract_track_id(found_url)
            logger.info(f"found via search: {track_id}")

    if not track_id:
        logger.warning(f"spotify_cover_fetcher: не распознал track ref '{spotify_ref}'")
        return None

    sp = _get_spotify_client()
    if sp is None:
        return None

    try:
        track = sp.track(track_id)
    except Exception as e:
        logger.error(f"Spotify track() failed for {track_id}: {e}")
        # Последняя попытка — search
        if fallback_query:
            found_url = search_track(fallback_query, limit=1)
            if found_url:
                track_id = _extract_track_id(found_url)
                if track_id:
                    try:
                        track = sp.track(track_id)
                    except Exception:
                        return None
        else:
            return None
    _ = cache  # reserved for future use

    pack = SpotifyTrackPack(track_id=track_id)
    pack.track_name = track.get("name", "") or ""
    pack.album_name = (track.get("album") or {}).get("name", "") or ""
    pack.release_date = (track.get("album") or {}).get("release_date", "") or ""
    pack.popularity = int(track.get("popularity") or 0)
    pack.duration_ms = int(track.get("duration_ms") or 0)
    pack.spotify_url = (track.get("external_urls") or {}).get("spotify", "") or ""

    artists = track.get("artists") or []
    if artists:
        pack.artist_name = ", ".join(a.get("name", "") for a in artists if a.get("name"))

    # Cover — берём самую большую из images
    images = (track.get("album") or {}).get("images") or []
    if images:
        # Spotify возвращает отсортированные от больших к маленьким
        images_sorted = sorted(
            images, key=lambda im: (im.get("width") or 0), reverse=True
        )
        pack.cover_url = images_sorted[0].get("url", "") or ""

    # Сохраняем cover локально
    if pack.cover_url:
        local_path = os.path.join(
            output_base, str(user_id), "covers", f"{track_id}.jpg"
        )
        if _download_cover(pack.cover_url, local_path):
            pack.cover_local_path = local_path
            logger.info(f"cover saved: {local_path}")

    # Audio Features — второй API запрос
    try:
        feats = sp.audio_features(track_id)
        if feats and feats[0]:
            f = feats[0]
            pack.valence = float(f.get("valence") or 0.5)
            pack.energy = float(f.get("energy") or 0.5)
            pack.danceability = float(f.get("danceability") or 0.5)
            pack.acousticness = float(f.get("acousticness") or 0.5)
            pack.instrumentalness = float(f.get("instrumentalness") or 0.5)
            pack.liveness = float(f.get("liveness") or 0.5)
            pack.speechiness = float(f.get("speechiness") or 0.5)
            pack.mode = int(f.get("mode") or 1)
            pack.key = int(f.get("key") or -1)
            if 0 <= pack.key < len(_KEY_NAMES):
                suffix = "" if pack.mode == 1 else "m"
                pack.key_name = _KEY_NAMES[pack.key] + suffix
            pack.tempo = float(f.get("tempo") or 0.0)
            pack.time_signature = int(f.get("time_signature") or 4)
    except Exception as e:
        logger.warning(f"audio_features failed: {e}")

    logger.info(
        f"track pack: '{pack.track_name}' — {pack.artist_name} "
        f"(valence={pack.valence:.2f} energy={pack.energy:.2f} "
        f"tempo={pack.tempo:.0f} key={pack.key_name})"
    )
    return pack


def mood_label(pack: SpotifyTrackPack) -> str:
    """
    Превращает Spotify audio features в текстовый mood тег.
    Используется в track_to_visual для выбора палитры.

    Классическая 2D модель (arousal=energy, valence=happy/sad):
      high V + high E = happy/upbeat
      high V + low E  = chill/peaceful
      low V + high E  = angry/intense
      low V + low E   = sad/melancholy
    """
    v, e = pack.valence, pack.energy
    if v >= 0.6 and e >= 0.6:
        return "happy"
    if v >= 0.6 and e < 0.4:
        return "chill"
    if v < 0.4 and e >= 0.6:
        return "intense"
    if v < 0.4 and e < 0.4:
        return "sad"
    if v < 0.4 and 0.4 <= e < 0.6:
        return "melancholy"
    if v >= 0.6 and 0.4 <= e < 0.6:
        return "dreamy"
    return "neutral"


def recommended_preset(pack: SpotifyTrackPack) -> str:
    """
    Из audio features → рекомендованный scenario (heuristic).
    Используется template_router как feature-based baseline.
    """
    # Вокальность высокая (speechiness), есть lyrics → kinetic / track_promo
    if pack.speechiness > 0.15 and pack.instrumentalness < 0.3:
        if pack.popularity < 20:
            return "track_promo"        # ноунейм с текстом → продвижение
        return "kinetic"
    # Инструментал / эмбиент → cover_alive (визуал + слабый текст)
    if pack.instrumentalness > 0.5:
        return "cover_alive"
    # Танцевальный upbeat → kinetic с батчем
    if pack.danceability > 0.7 and pack.energy > 0.7:
        return "kinetic"
    return "track_promo"
