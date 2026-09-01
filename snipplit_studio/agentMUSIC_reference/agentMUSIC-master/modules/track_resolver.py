"""
Spotify-free резолвер трека: свободный запрос (название ИЛИ ссылка) -> скачанный mp3.

Зачем: Spotify Web API с февраля 2026 отдаёт 403 без Premium-владельца приложения,
что ломало и поиск по имени, и резолв по ссылке (оба дёргали spotipy первым). Здесь
метаданные берём без Spotify:
  - имя         -> публичный Deezer search (api.deezer.com) -> Deezer/yt-dlp;
  - ссылка YT/SC -> yt-dlp по самой ссылке напрямую;
  - ссылка Deezer-> публичный Deezer track API -> streamrip по id;
  - ссылка Spotify/Apple -> og:title страницы (без API) -> дальше как имя.

Скачивание переиспользует существующие «ноги» modules.spotify_loader
(_download_via_deezer / _download_via_youtube), которые от Spotify не зависят.
Порядок источников: Deezer (ARL) -> yt-dlp (YouTube/SoundCloud); 30-сек превью
никогда не выдаётся (preview-нога здесь не вызывается).

Безопасность: значение приходит из пользовательского prompt, поэтому любой серверный
HTTP-фетч (Deezer API / og-скрейп) ограничен allowlist публичных музыкальных хостов,
резолвится только в публичные IP и не следует редиректам на непубличные хосты (SSRF).
"""

import html as html_lib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from modules import spotify_loader as sl
from modules.config import settings

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0"
_MAX_FETCH_BYTES = 2 * 1024 * 1024  # og-теги / Deezer-JSON: 2 МиБ с запасом

# Единственные хосты, которые нам можно фетчить с сервера. Всё остальное — не наше
# дело и потенциальный SSRF-вектор, поэтому не ходим туда вообще.
_ALLOWED_FETCH_HOSTS = frozenset(
    {
        "api.deezer.com",
        "deezer.com",
        "www.deezer.com",
        "open.spotify.com",
        "spotify.com",
        "www.spotify.com",
        "music.apple.com",
        "itunes.apple.com",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "soundcloud.com",
        "www.soundcloud.com",
    }
)


# --------------------------------------------------------------------------- Разбор запроса
def is_url(s: str) -> bool:
    return (s or "").strip().lower().startswith(("http://", "https://"))


def classify_url(url: str) -> str:
    """youtube | soundcloud | spotify | deezer | apple | other."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "youtu" in host:
        return "youtube"
    if "soundcloud" in host:
        return "soundcloud"
    if "spotify" in host:
        return "spotify"
    if "deezer" in host:
        return "deezer"
    if "apple" in host:  # music.apple.com / itunes.apple.com
        return "apple"
    return "other"


def _slug_from_url(url: str) -> str:
    """Деградационный текст поиска из последнего сегмента пути ссылки."""
    path = urllib.parse.urlparse(url).path
    seg = [p for p in path.split("/") if p]
    if not seg:
        return ""
    tail = urllib.parse.unquote(seg[-1])
    tail = re.sub(r"\.[a-z0-9]{1,4}$", "", tail, flags=re.I)  # срезать расширение
    return re.sub(r"[-_+]+", " ", tail).strip()


# --------------------------------------------------------------------------- Безопасный HTTP (anti-SSRF)
def _is_public_host(host: str) -> bool:
    """True, если host резолвится ТОЛЬКО в публичные IP (private/loopback/link-local/… -> False)."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return False
    return True


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Разрешает редиректы только на публичные хосты (иначе allowlisted-хост мог бы 302-нуть внутрь)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlparse(newurl)
        if p.scheme not in ("http", "https") or not _is_public_host(p.hostname or ""):
            raise urllib.error.HTTPError(
                req.full_url, code, f"blocked redirect -> {newurl}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirect)


def _http_get(url: str, timeout: int = 15) -> str:
    """GET с anti-SSRF: только http(s), только allowlist-хост в публичном IP, редиректы гардятся, тело капается."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_FETCH_HOSTS:
        raise ValueError(f"host not allowed: {host}")
    if not _is_public_host(host):
        raise ValueError(f"host not public: {host}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with _opener.open(req, timeout=timeout) as resp:
        return resp.read(_MAX_FETCH_BYTES).decode(errors="replace")


# --------------------------------------------------------------------------- Метаданные без Spotify
def _deezer_search(query: str, timeout: int = 15) -> Optional[dict]:
    """Первый хит публичного Deezer search -> {deezer_id, artist, title}. None при любой ошибке."""
    url = "https://api.deezer.com/search?limit=1&q=" + urllib.parse.quote(query)
    try:
        data = json.loads(_http_get(url, timeout))
        arr = (data or {}).get("data") or []
        if not arr:
            return None
        t = arr[0]
        dz_id = t.get("id")
        if not isinstance(dz_id, int):
            return None
        return {
            "deezer_id": dz_id,
            "artist": (t.get("artist") or {}).get("name", ""),
            "title": t.get("title", ""),
        }
    except Exception as e:
        logger.warning(f"Deezer search failed for '{query}': {e}")
        return None


def _deezer_track_from_url(url: str, timeout: int = 15) -> Optional[dict]:
    """Deezer track-ссылка -> {deezer_id, artist, title, isrc} через публичный API."""
    m = re.search(r"/track/(\d+)", url)
    if not m:
        return None
    try:
        data = json.loads(
            _http_get(f"https://api.deezer.com/track/{m.group(1)}", timeout)
        )
    except Exception as e:
        logger.warning(f"Deezer track lookup failed for {url}: {e}")
        return None
    if not isinstance(data, dict) or data.get("error") or not data.get("id"):
        return None
    return {
        "deezer_id": int(data["id"]),
        "artist": (data.get("artist") or {}).get("name", ""),
        "title": data.get("title", ""),
        "isrc": data.get("isrc"),
    }


def _meta_content(text: str, prop: str) -> str:
    """Достаёт content из <meta property="prop" content="..."> (в любом порядке)."""
    for pat in (
        rf'property=["\']{prop}["\'][^>]*content=["\']([^"\']+)["\']',
        rf'content=["\']([^"\']+)["\'][^>]*property=["\']{prop}["\']',
    ):
        m = re.search(pat, text)
        if m:
            return html_lib.unescape(m.group(1)).strip()
    return ""


def _scrape_url_title(url: str, timeout: int = 15) -> str:
    """ "artist title" из og-мета страницы (только allowlist-хост, см. _http_get). '' если не вышло."""
    try:
        text = _http_get(url, timeout)
    except Exception as e:
        logger.warning(f"title scrape failed for {url}: {e}")
        return ""
    title = _meta_content(text, "og:title")
    desc = _meta_content(text, "og:description")
    # Spotify: og:title = песня, og:description = "ARTIST · Song · год". Берём артиста
    # из описания, но пропускаем описания-предложения ("Listen to …") — там не артист.
    if title and desc and "·" in desc:
        artist = desc.split("·")[0].strip()
        low = artist.lower()
        sentence = low.startswith(("listen", "watch", "provided", "слушай", "смотри"))
        if artist and not sentence and low not in title.lower():
            return f"{artist} {title}".strip()
    return title


# --------------------------------------------------------------------------- Скачивание
def _ytdlp_download_url(url: str, out_dir: str, timeout: int = 300) -> Optional[str]:
    """yt-dlp по прямой ссылке (YouTube/SoundCloud). Путь к mp3 или None."""
    yt = shutil.which("yt-dlp")
    if not yt:
        logger.info("yt-dlp не найден — пропускаю прямую ссылку")
        return None
    before = set(sl._list_mp3(out_dir))
    out_tpl = os.path.join(out_dir, "%(title).100s.%(ext)s")
    opts = [
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "-o",
        out_tpl,
        "--no-playlist",
        "--no-warnings",
        "--geo-bypass",
        "--sleep-requests",
        "1",
    ]
    cookie = settings.ytm_cookie_file
    if cookie and os.path.exists(cookie):
        opts += ["--cookies", cookie]
    try:
        proc = subprocess.run(
            [yt, *opts, url], capture_output=True, text=True, timeout=min(timeout, 300)
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"yt-dlp timeout for URL {url}")
        return None
    except Exception as e:
        logger.warning(f"yt-dlp error for URL {url}: {e}")
        return None
    if proc.returncode != 0:
        logger.warning(
            f"yt-dlp rc={proc.returncode} for {url}: {(proc.stderr or '')[-240:]}"
        )
        return None
    new = [p for p in sl._list_mp3(out_dir) if p not in before]
    for f in new:
        if sl._probe_duration(f) >= settings.min_track_seconds:
            return f
        try:
            os.remove(f)
        except OSError:
            pass
    return None


def _wrap(path: str, meta: dict, source: str) -> "sl.DownloadedTrack":
    return sl.DownloadedTrack(
        path=path,
        artist=meta.get("artist", ""),
        title=meta.get("title", "") or os.path.splitext(os.path.basename(path))[0],
        duration=sl._probe_duration(path),
        source=source,
        is_preview=False,
    )


def _download_item(
    item: dict, out_dir: str, timeout: int
) -> Optional["sl.DownloadedTrack"]:
    """Скачивает item по нотам Deezer(ARL) -> yt-dlp. БЕЗ preview-ноги, порядок явный."""
    path = sl._download_via_deezer(item, out_dir, timeout)
    used = "deezer"
    if not path:
        path = sl._download_via_youtube(item, out_dir, timeout)
        used = "youtube"
    if not path:
        return None
    return sl.DownloadedTrack(
        path=path,
        artist=item.get("artist", ""),
        title=item.get("title", "") or os.path.splitext(os.path.basename(path))[0],
        duration=sl._probe_duration(path),
        source=used,
        is_preview=False,
    )


def download_freeform(
    query: str, out_dir: str, timeout: int = 300
) -> Optional["sl.DownloadedTrack"]:
    """Скачивает трек по имени ИЛИ ссылке, минуя Spotify API. None при неудаче.

    Deezer (ARL) -> yt-dlp (YouTube/SoundCloud). Никаких молчаливых 30-сек превью.
    """
    os.makedirs(out_dir, exist_ok=True)
    query = (query or "").strip()
    if not query:
        return None

    if is_url(query):
        kind = classify_url(query)
        if kind in ("youtube", "soundcloud"):
            path = _ytdlp_download_url(query, out_dir, timeout)
            if path:
                return _wrap(path, sl.parse_track_metadata(path), kind)
            # прямая ссылка не скачалась -> имя из og:title (allowlisted host) -> поиск
            query = _scrape_url_title(query)
            if not query:
                return None
        elif kind == "deezer":
            item = _deezer_track_from_url(query)
            if item:
                dt = _download_item(item, out_dir, timeout)
                if dt:
                    return dt
            query = _scrape_url_title(query) or _slug_from_url(query)
            if not query:
                return None
        elif kind in ("spotify", "apple"):
            # известная площадка -> резолвим ссылку в название через og:title
            query = _scrape_url_title(query) or _slug_from_url(query)
            if not query:
                return None
        else:  # other — с сервера НЕ фетчим (SSRF): только слаг из URL
            query = _slug_from_url(query)
            if not query:
                return None

    # свободный текст (имя) — сюда же попадаем после резолва ссылки в название
    item = _deezer_search(query) or {"artist": "", "title": query}
    return _download_item(item, out_dir, timeout)
