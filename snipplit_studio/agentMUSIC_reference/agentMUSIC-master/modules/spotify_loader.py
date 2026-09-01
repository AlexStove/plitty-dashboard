"""
Скачивание полных треков по Spotify-ссылке.

Spotify сам аудио не отдаёт (DRM) — резолвим метаданные через spotipy и качаем
полную копию из источников по выбранному режиму:
  - "deezer"  : точное совпадение по ISRC -> Deezer (streamrip), полный трек.
  - "youtube" : hardened yt-dlp поиск, с проверкой длительности.
  - "auto"    : Deezer -> YouTube -> (помеченное) 30-сек превью.

Любая нога при ошибке возвращает None и цепочка идёт дальше — превью никогда не
выдаётся молча за полный трек: оно помечается is_preview=True.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse

from modules.config import settings

logger = logging.getLogger(__name__)

# Аудио-расширения, которые могут отдать источники (нормализуем в mp3).
_AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac")


@dataclass
class DownloadedTrack:
    """Результат скачивания одного трека."""
    path: str
    artist: str
    title: str
    duration: float
    source: str          # "deezer" | "youtube" | "preview"
    is_preview: bool


class SpotdlError(Exception):
    """Ошибка скачивания с понятным сообщением для пользователя."""
    pass


# ---------------------------------------------------------------------------
# Поиск бинарников
# ---------------------------------------------------------------------------
def _spotdl_executable() -> Optional[str]:
    """Путь к spotdl: сначала venv, потом PATH."""
    venv_bin = os.path.dirname(sys.executable)
    candidate = os.path.join(venv_bin, "spotdl")
    if os.path.exists(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which("spotdl")


def is_spotdl_available() -> bool:
    """Проверяет наличие spotdl (venv или PATH) — используется как gate в боте."""
    return _spotdl_executable() is not None


def _streamrip_executable() -> Optional[str]:
    """Путь к streamrip CLI (`rip`): сначала venv, потом PATH."""
    venv_bin = os.path.dirname(sys.executable)
    for name in ("rip", "rip.exe"):
        candidate = os.path.join(venv_bin, name)
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("rip")


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def _list_audio(directory: str, recursive: bool = False) -> list[str]:
    """Список аудиофайлов в директории (опционально рекурсивно)."""
    if not os.path.isdir(directory):
        return []
    out: list[str] = []
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(_AUDIO_EXTS):
                    out.append(os.path.join(root, f))
    else:
        for f in os.listdir(directory):
            p = os.path.join(directory, f)
            if f.lower().endswith(_AUDIO_EXTS) and os.path.isfile(p):
                out.append(p)
    return out


def _list_mp3(directory: str) -> list[str]:
    """Список mp3 в директории (для yt-dlp/preview, которые пишут mp3)."""
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.lower().endswith(".mp3") and os.path.isfile(os.path.join(directory, f))
    ]


def _probe_duration(path: str) -> float:
    """Длительность файла в секундах через ffprobe; 0.0 при ошибке."""
    try:
        from modules.utils import get_media_duration
        return get_media_duration(path)
    except Exception as e:
        logger.warning(f"duration probe failed for {path}: {e}")
        return 0.0


def _safe_name(artist: str, title: str) -> str:
    return f"{artist} - {title}".replace("/", "_").replace("\\", "_").strip()[:120] or "track"


def _ensure_mp3(src: str, out_dir: str, item: dict) -> Optional[str]:
    """Нормализует скачанный файл в mp3 внутри out_dir. Возвращает путь к mp3."""
    safe = _safe_name(item.get("artist", ""), item.get("title", "")) or \
        os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(out_dir, f"{safe}.mp3")

    if src.lower().endswith(".mp3"):
        if os.path.abspath(src) != os.path.abspath(dst):
            try:
                shutil.move(src, dst)
            except Exception:
                return src
        return dst

    cmd = ["ffmpeg", "-y", "-i", src, "-vn", "-acodec", "libmp3lame", "-q:a", "2", dst]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
    except Exception as e:
        logger.warning(f"ffmpeg convert to mp3 failed: {e}")
        return src
    if os.path.exists(dst):
        try:
            os.remove(src)
        except OSError:
            pass
        return dst
    return src


# ---------------------------------------------------------------------------
# Резолв треков из Spotify (метаданные + ISRC)
# ---------------------------------------------------------------------------
def _resolve_spotify_tracks(
    spotify_url: str,
    client_id: str,
    client_secret: str,
    max_tracks: int,
) -> list[dict]:
    """
    Через spotipy достаёт список треков для любого типа Spotify-URL.
    Каждый item: {artist, title, track_id, isrc, preview_url, duration}.
    """
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError:
        raise SpotdlError("spotipy не установлен — резолв треков невозможен")

    parsed = urlparse(spotify_url)
    spotify_url = urlunparse(parsed._replace(query="", fragment=""))

    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
    )

    items: list[dict] = []

    def _collect(t: Optional[dict]):
        if not t or not t.get("name"):
            return
        artists = t.get("artists") or [{}]
        artist = artists[0].get("name", "") if artists else ""
        ext = t.get("external_ids") or {}
        items.append({
            "artist": artist,
            "title": t["name"],
            "track_id": t.get("id", ""),
            "isrc": ext.get("isrc", ""),
            "preview_url": t.get("preview_url"),
            "duration": float(t.get("duration_ms") or 0) / 1000.0,
        })

    try:
        if "/track/" in spotify_url:
            tid = spotify_url.split("/track/")[1].split("?")[0].split("/")[0]
            _collect(sp.track(tid))
        elif "/playlist/" in spotify_url:
            pid = spotify_url.split("/playlist/")[1].split("?")[0].split("/")[0]
            for it in sp.playlist_items(pid, limit=max_tracks).get("items", [])[:max_tracks]:
                if it.get("track"):
                    _collect(it["track"])
        elif "/album/" in spotify_url:
            aid = spotify_url.split("/album/")[1].split("?")[0].split("/")[0]
            # album_tracks не содержит external_ids/isrc — дочитываем через /tracks/{ids}
            album_ts = sp.album_tracks(aid, limit=max_tracks).get("items", [])[:max_tracks]
            ids = [t["id"] for t in album_ts if t.get("id")]
            if ids:
                for t in sp.tracks(ids).get("tracks", []):
                    _collect(t)
        elif "/artist/" in spotify_url:
            aid = spotify_url.split("/artist/")[1].split("?")[0].split("/")[0]
            for t in sp.artist_top_tracks(aid).get("tracks", [])[:max_tracks]:
                _collect(t)
        else:
            raise SpotdlError("Unsupported Spotify URL")
    except spotipy.SpotifyException as e:
        # С февраля 2026 Spotify требует Premium у владельца dev-приложения,
        # иначе Web API отдаёт 403. Делаем сообщение понятным и actionable.
        if getattr(e, "http_status", None) == 403:
            raise SpotdlError(
                "❌ Spotify API недоступен (403).\n\n"
                "С февраля 2026 Spotify требует, чтобы у владельца приложения был "
                "активный Premium-аккаунт. Создай приложение на "
                "https://developer.spotify.com/dashboard под Premium-аккаунтом и "
                "обнови SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET."
            )
        raise SpotdlError(f"Spotify API error: {e}")

    return items


# ---------------------------------------------------------------------------
# Нога 1: Deezer (ISRC -> Deezer -> streamrip)
# ---------------------------------------------------------------------------
def _deezer_id_from_isrc(isrc: str) -> Optional[int]:
    """Находит Deezer track id по ISRC через публичный Deezer API."""
    url = f"https://api.deezer.com/track/isrc:{isrc}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode(errors="replace"))
    if isinstance(data, dict) and data.get("id") and not data.get("error"):
        return int(data["id"])
    return None


def _streamrip_config_path() -> str:
    """Отдельный config.toml для streamrip под нашим ботом (не трогаем юзерский)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "agentmusic", "streamrip_config.toml")


def _ensure_streamrip_config(cfg_path: str, arl: str, rip_bin: str) -> bool:
    """
    Гарантирует валидный config.toml streamrip с нашим ARL.

    streamrip сам создаёт полный дефолтный конфиг по --config-path, если файла нет
    (callback группы `rip`). Мы лишь вписываем [deezer].arl через tomlkit, не ломая
    остальную (версионно-зависимую) схему. quality/codec/folder задаются флагами CLI.
    """
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    # 1) Если конфига нет — пусть streamrip создаст полный валидный дефолт.
    if not os.path.exists(cfg_path):
        try:
            subprocess.run(
                [rip_bin, "--config-path", cfg_path, "config", "path"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
            )
        except Exception as e:
            logger.warning(f"streamrip config init failed: {e}")
    if not os.path.exists(cfg_path):
        return False
    # 2) Впишем ARL в [deezer].arl.
    try:
        import tomlkit
        with open(cfg_path, encoding="utf-8") as f:
            doc = tomlkit.parse(f.read())
        if "deezer" not in doc:
            doc["deezer"] = tomlkit.table()
        doc["deezer"]["arl"] = arl
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        return True
    except Exception as e:
        logger.warning(f"streamrip ARL write failed: {e}")
        return False


def _download_via_deezer(item: dict, out_dir: str, timeout: int) -> Optional[str]:
    """Скачивает полный трек с Deezer через streamrip. None при неудаче.

    Принимает готовый Deezer track id (``item["deezer_id"]``) — например от
    поиска track_resolver — или ISRC (``item["isrc"]``) для обратной совместимости.
    """
    arl = settings.deezer_arl
    if not arl:
        return None
    rip = _streamrip_executable()
    if not rip:
        logger.info("streamrip (`rip`) не найден — пропускаю Deezer")
        return None

    dz_id = item.get("deezer_id")
    if not dz_id:
        isrc = item.get("isrc")
        if not isrc:
            return None
        try:
            dz_id = _deezer_id_from_isrc(isrc)
        except Exception as e:
            logger.warning(f"Deezer ISRC lookup failed for {isrc}: {e}")
            return None
        if not dz_id:
            logger.info(f"Deezer: трек по ISRC {isrc} не найден")
            return None

    cfg = _streamrip_config_path()
    if not _ensure_streamrip_config(cfg, arl, rip):
        return None

    before = set(_list_audio(out_dir, recursive=True))
    # rip — python-приложение: без PYTHONIOENCODING оно кодирует свой вывод в
    # локальную cp1251 (Windows) и падает UnicodeEncodeError посреди закачки.
    rip_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    new: list[str] = []
    # quality 1 = 320k (Premium); free-аккаунт на 2.x получает WrongLicense,
    # а не деградацию — поэтому явный fallback на quality 0 (128k).
    for quality in ("1", "0"):
        # `id deezer track <id>` минует баг парсинга URL (#865); --no-db
        # отключает пропуск повторов; --codec MP3.
        cmd = [
            rip, "--config-path", cfg, "--no-db", "--folder", out_dir,
            "--quality", quality, "--codec", "MP3",
            "id", "deezer", "track", str(dz_id),
        ]
        try:
            # encoding: streamrip печатает UTF-8 (прогресс-бары); без явной
            # кодировки Windows декодирует cp1251 и падает в reader-треде.
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=min(timeout, 240), env=rip_env,
            )
            tail = ((proc.stderr or "") + (proc.stdout or ""))[-600:]
            logger.info(f"streamrip [deezer {dz_id} q{quality}] rc={proc.returncode}: {tail}")
        except subprocess.TimeoutExpired:
            logger.warning(f"streamrip timeout for deezer {dz_id}")
            return None
        except Exception as e:
            logger.warning(f"streamrip error for deezer {dz_id}: {e}")
            return None

        new = [p for p in _list_audio(out_dir, recursive=True) if p not in before]
        if new:
            break
    if not new:
        return None
    src = max(new, key=lambda p: os.path.getmtime(p))
    final = _ensure_mp3(src, out_dir, item)
    if final and _probe_duration(final) >= settings.min_track_seconds:
        return final
    # Слишком короткий результат — не считаем полным треком.
    return None


# ---------------------------------------------------------------------------
# Нога 2: YouTube (hardened yt-dlp)
# ---------------------------------------------------------------------------
def _download_via_youtube(item: dict, out_dir: str, timeout: int) -> Optional[str]:
    """Hardened yt-dlp поиск полного трека с проверкой длительности. None при неудаче."""
    yt = shutil.which("yt-dlp")
    if not yt:
        logger.info("yt-dlp не найден — пропускаю YouTube")
        return None

    artist, title = item.get("artist", ""), item.get("title", "")
    safe = _safe_name(artist, title)
    out_tpl = os.path.join(out_dir, f"{safe}.%(ext)s")
    q = f"{artist} {title} audio".strip()

    opts = [
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "-o", out_tpl,
        "--no-playlist", "--no-warnings", "--geo-bypass",
        "--sleep-requests", "1", "--sleep-interval", "5", "--max-sleep-interval", "10",
    ]
    cookie = settings.ytm_cookie_file
    if cookie and os.path.exists(cookie):
        opts += ["--cookies", cookie]

    # web_safari отдаёт HLS без GVS PO-token; android/mweb как запас; SoundCloud в конце.
    providers = [
        ("yt web_safari", f"ytsearch1:{q}",
         ["--extractor-args", "youtube:player_client=web_safari,mweb,android"]),
        ("yt android", f"ytsearch1:{q}",
         ["--extractor-args", "youtube:player_client=android"]),
        ("soundcloud", f"scsearch1:{q}", []),
    ]

    for name, query, extra in providers:
        before = set(_list_mp3(out_dir))
        cmd = [yt, *opts, *extra, query]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=min(timeout, 180)
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"yt-dlp [{name}] timeout '{artist} - {title}'")
            continue
        except Exception as e:
            logger.warning(f"yt-dlp [{name}] error '{artist} - {title}': {e}")
            continue

        if proc.returncode == 0:
            new = [p for p in _list_mp3(out_dir) if p not in before]
            for f in new:
                if _probe_duration(f) >= settings.min_track_seconds:
                    logger.info(f"yt-dlp [{name}] OK '{artist} - {title}'")
                    return f
                # Слишком короткий (тизер/сниппет) — выкидываем.
                try:
                    os.remove(f)
                except OSError:
                    pass
        logger.warning(
            f"yt-dlp [{name}] rc={proc.returncode} '{artist} - {title}': "
            f"{(proc.stderr or '')[-240:]}"
        )

    return None


# ---------------------------------------------------------------------------
# Нога 3: Spotify preview (30 сек) — только как помеченный последний резерв
# ---------------------------------------------------------------------------
def _fetch_embed_preview_url(track_id: str) -> Optional[str]:
    """Скрейпит open.spotify.com/embed/track/{id}, вытаскивает mp3-preview URL."""
    try:
        import re
        import html as html_lib
        url = f"https://open.spotify.com/embed/track/{track_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode(errors="replace")
        m = re.search(r'"audioPreview"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"', text)
        if m:
            return html_lib.unescape(m.group(1)).replace("\\u002F", "/").replace("\\/", "/")
        m = re.search(r'property=["\']og:audio["\'][^>]*content=["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
    except Exception as e:
        logger.warning(f"embed preview fetch failed: {e}")
    return None


def _download_spotify_preview(url: str, out_path: str) -> bool:
    """Скачивает 30-сек preview Spotify в out_path (.mp3). True если успех."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return False
            data = resp.read()
        if len(data) < 10_000:  # <10 KB — явно не mp3
            return False
        with open(out_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logger.warning(f"preview download error: {e}")
        return False


def _download_preview(item: dict, out_dir: str) -> Optional[str]:
    """Помеченное 30-сек превью. None если даже превью недоступно."""
    artist, title = item.get("artist", ""), item.get("title", "")
    out_path = os.path.join(out_dir, f"{_safe_name(artist, title)}.mp3")
    candidate_urls: list[str] = []
    if item.get("preview_url"):
        candidate_urls.append(item["preview_url"])
    if item.get("track_id"):
        emb = _fetch_embed_preview_url(item["track_id"])
        if emb and emb not in candidate_urls:
            candidate_urls.append(emb)
    for purl in candidate_urls:
        if _download_spotify_preview(purl, out_path):
            logger.info(f"preview OK '{artist} - {title}' (30с превью, помечено)")
            return out_path
    return None


# ---------------------------------------------------------------------------
# Оркестратор
# ---------------------------------------------------------------------------
def _download_one(item: dict, out_dir: str, source: str, timeout: int) -> Optional[DownloadedTrack]:
    """Качает один трек по выбранному режиму источника."""
    path: Optional[str] = None
    used: Optional[str] = None

    if source in ("auto", "deezer"):
        path = _download_via_deezer(item, out_dir, timeout)
        if path:
            used = "deezer"
    if not path and source in ("auto", "youtube"):
        path = _download_via_youtube(item, out_dir, timeout)
        if path:
            used = "youtube"

    if path and used:
        return DownloadedTrack(
            path=path,
            artist=item.get("artist", ""),
            title=item.get("title", ""),
            duration=_probe_duration(path),
            source=used,
            is_preview=False,
        )

    # Последний резерв — помеченное 30-сек превью (для всех режимов).
    ppath = _download_preview(item, out_dir)
    if ppath:
        return DownloadedTrack(
            path=ppath,
            artist=item.get("artist", ""),
            title=item.get("title", ""),
            duration=_probe_duration(ppath),
            source="preview",
            is_preview=True,
        )
    return None


def download_artist_tracks(
    spotify_url: str,
    output_dir: str,
    max_tracks: int = 20,
    timeout: int = 300,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    source: str = "auto",
) -> list[DownloadedTrack]:
    """
    Скачивает полные треки по Spotify-ссылке.

    Args:
        spotify_url: ссылка на трек/плейлист/альбом/артиста.
        output_dir: куда сохранять mp3.
        max_tracks: лимит количества треков.
        timeout: таймаут на трек (сек).
        client_id/client_secret: Spotify creds (иначе из env).
        source: "auto" | "deezer" | "youtube".

    Returns:
        Список DownloadedTrack (is_preview=True для 30-сек превью).

    Raises:
        SpotdlError: нет Spotify creds / URL не отдал треков / ничего не скачалось.
    """
    os.makedirs(output_dir, exist_ok=True)

    cid = client_id or settings.spotify_client_id
    csec = client_secret or settings.spotify_client_secret
    if not (cid and csec):
        raise SpotdlError(
            "❌ Не заданы SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET.\n\n"
            "Получить: https://developer.spotify.com/dashboard"
        )

    source = (source or "auto").lower()
    if source not in ("auto", "deezer", "youtube"):
        source = "auto"

    try:
        items = _resolve_spotify_tracks(spotify_url, cid, csec, max_tracks)
    except SpotdlError:
        raise
    except Exception as e:
        raise SpotdlError(f"Не удалось прочитать треки из Spotify: {e}")

    if not items:
        raise SpotdlError("Spotify не вернул треков для этого URL")

    results: list[DownloadedTrack] = []
    for item in items[:max_tracks]:
        dt = _download_one(item, output_dir, source, timeout)
        if dt:
            results.append(dt)
        else:
            logger.warning(
                f"все источники провалились для "
                f"'{item.get('artist','')} - {item.get('title','')}'"
            )

    if not results:
        raise SpotdlError(
            "❌ Не удалось скачать ни одного трека из выбранного источника.\n\n"
            "Spotify сам MP3 не отдаёт — копию ищут в Deezer/YouTube. "
            "Попробуй другой источник или загрузи MP3 вручную через вкладку MinIO."
        )

    return results


def parse_track_metadata(filename: str) -> dict:
    """
    Извлекает artist/title из имени файла ("Artist - Title.mp3" или "Title.mp3").
    Оставлено для обратной совместимости (uploads, ручные пути).
    """
    base = os.path.basename(filename).replace(".mp3", "")
    if " - " in base:
        artist, title = base.split(" - ", 1)
        return {"artist": artist.strip(), "title": title.strip()}
    return {"artist": "", "title": base.strip()}
