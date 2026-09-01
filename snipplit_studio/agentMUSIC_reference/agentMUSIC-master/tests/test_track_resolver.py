"""Тесты Spotify-free резолвера трека (modules/track_resolver.py).

Внешние вызовы (HTTP к Deezer, yt-dlp, streamrip, DNS) замоканы — проверяем разбор
запроса, парсинг метаданных, роутинг источников и anti-SSRF гарды, без сети/бинарников.
"""

import pytest

from modules import spotify_loader as sl
from modules import track_resolver as tr


# --------------------------------------------------------------------------- URL разбор
def test_is_url():
    assert tr.is_url("https://open.spotify.com/track/x")
    assert tr.is_url("  http://youtu.be/x  ")
    assert not tr.is_url("Artist Title")
    assert not tr.is_url("")


def test_classify_url():
    assert tr.classify_url("https://youtu.be/abc") == "youtube"
    assert tr.classify_url("https://www.youtube.com/watch?v=abc") == "youtube"
    assert tr.classify_url("https://soundcloud.com/a/b") == "soundcloud"
    assert tr.classify_url("https://open.spotify.com/track/x") == "spotify"
    assert tr.classify_url("https://www.deezer.com/track/123") == "deezer"
    assert tr.classify_url("https://music.apple.com/us/album/x/1?i=2") == "apple"
    assert tr.classify_url("https://example.com/song") == "other"


def test_slug_from_url():
    assert tr._slug_from_url("https://ex.com/a/my-cool-song") == "my cool song"
    assert tr._slug_from_url("https://ex.com/track/artist_title.mp3") == "artist title"
    assert tr._slug_from_url("https://ex.com/") == ""


# --------------------------------------------------------------------------- anti-SSRF гарды
def test_is_public_host(monkeypatch):
    monkeypatch.setattr(
        tr.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("127.0.0.1", 0))]
    )
    assert tr._is_public_host("x") is False
    monkeypatch.setattr(
        tr.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("10.0.0.5", 0))]
    )
    assert tr._is_public_host("x") is False
    monkeypatch.setattr(
        tr.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("169.254.1.2", 0))]
    )
    assert tr._is_public_host("x") is False
    monkeypatch.setattr(
        tr.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("8.8.8.8", 0))]
    )
    assert tr._is_public_host("x") is True


def test_is_public_host_dns_failure(monkeypatch):
    def boom(h, p):
        raise OSError("nxdomain")

    monkeypatch.setattr(tr.socket, "getaddrinfo", boom)
    assert tr._is_public_host("x") is False


def test_http_get_rejects_bad_scheme():
    with pytest.raises(ValueError):
        tr._http_get("ftp://api.deezer.com/x")


def test_http_get_blocks_non_allowlisted_host():
    with pytest.raises(ValueError):
        tr._http_get("https://evil.example.com/x")


def test_http_get_blocks_private_ip(monkeypatch):
    # хост в allowlist, но резолвится в приватный -> reject
    monkeypatch.setattr(tr, "_is_public_host", lambda h: False)
    with pytest.raises(ValueError):
        tr._http_get("https://api.deezer.com/x")


class _FakeResp:
    def __init__(self, body):
        self.body = body
        self.read_n = "unset"

    def read(self, n=-1):
        self.read_n = n
        return self.body if n in (-1, None) else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_get_caps_read(monkeypatch):
    monkeypatch.setattr(tr, "_is_public_host", lambda h: True)
    fake = _FakeResp(b"x" * (5 * 1024 * 1024))
    monkeypatch.setattr(tr._opener, "open", lambda req, timeout=15: fake)
    out = tr._http_get("https://api.deezer.com/search?q=x")
    assert fake.read_n == tr._MAX_FETCH_BYTES
    assert len(out) == tr._MAX_FETCH_BYTES


# --------------------------------------------------------------------------- Deezer метаданные
def test_deezer_search_parses(monkeypatch):
    payload = '{"data":[{"id":42,"title":"Song","artist":{"name":"Artist"}}]}'
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: payload)
    assert tr._deezer_search("artist song") == {
        "deezer_id": 42,
        "artist": "Artist",
        "title": "Song",
    }


def test_deezer_search_empty(monkeypatch):
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: '{"data":[]}')
    assert tr._deezer_search("nothing") is None


def test_deezer_search_broken_first_hit(monkeypatch):
    # первый хит без числового id -> None, а не исключение
    monkeypatch.setattr(
        tr, "_http_get", lambda url, timeout=15: '{"data":[{"title":"X"}]}'
    )
    assert tr._deezer_search("x") is None
    monkeypatch.setattr(
        tr, "_http_get", lambda url, timeout=15: '{"data":[{"id":"abc"}]}'
    )
    assert tr._deezer_search("x") is None


def test_deezer_search_http_error_returns_none(monkeypatch):
    def boom(url, timeout=15):
        raise OSError("network down")

    monkeypatch.setattr(tr, "_http_get", boom)
    assert tr._deezer_search("x") is None


def test_deezer_track_from_url(monkeypatch):
    payload = '{"id":7,"title":"T","artist":{"name":"A"},"isrc":"US123"}'
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: payload)
    item = tr._deezer_track_from_url("https://www.deezer.com/en/track/7")
    assert item == {"deezer_id": 7, "artist": "A", "title": "T", "isrc": "US123"}


def test_deezer_track_from_url_no_id():
    assert tr._deezer_track_from_url("https://www.deezer.com/album/9") is None


# --------------------------------------------------------------------------- og:title скрейп
def test_scrape_url_title_basic(monkeypatch):
    html = '<meta property="og:title" content="Artist - Song">'
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: html)
    assert tr._scrape_url_title("https://open.spotify.com/track/x") == "Artist - Song"


def test_scrape_url_title_combines_spotify_artist(monkeypatch):
    html = (
        '<meta property="og:title" content="Song Name">'
        '<meta property="og:description" content="Cool Artist · Song · 2024">'
    )
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: html)
    assert (
        tr._scrape_url_title("https://open.spotify.com/track/x")
        == "Cool Artist Song Name"
    )


def test_scrape_url_title_skips_sentence_desc(monkeypatch):
    html = (
        '<meta property="og:title" content="Song Name">'
        '<meta property="og:description" content="Listen to Song Name on Spotify. X · Song">'
    )
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: html)
    assert tr._scrape_url_title("https://open.spotify.com/track/x") == "Song Name"


def test_scrape_url_title_none(monkeypatch):
    monkeypatch.setattr(tr, "_http_get", lambda url, timeout=15: "<html>no meta</html>")
    assert tr._scrape_url_title("https://open.spotify.com/track/x") == ""


def test_scrape_url_title_blocked_host_returns_empty(monkeypatch):
    # _http_get реджектит непубличный/недопустимый хост -> скрейп деградирует в ""
    monkeypatch.setattr(tr, "_is_public_host", lambda h: False)
    assert tr._scrape_url_title("https://open.spotify.com/track/x") == ""


# --------------------------------------------------------------------------- download_freeform роутинг
def _dt(source, title="T"):
    return sl.DownloadedTrack(
        path="/tmp/x.mp3",
        artist="A",
        title=title,
        duration=120.0,
        source=source,
        is_preview=False,
    )


def test_freeform_empty_returns_none(tmp_path):
    assert tr.download_freeform("   ", str(tmp_path)) is None


def test_freeform_youtube_url_direct(monkeypatch, tmp_path):
    """YouTube-ссылка -> прямой yt-dlp, без Deezer-поиска и _download_item."""
    monkeypatch.setattr(
        tr, "_ytdlp_download_url", lambda u, o, t: "/tmp/Artist - Title.mp3"
    )
    monkeypatch.setattr(sl, "_probe_duration", lambda p: 200.0)
    called = {"deezer_search": False, "download_item": False}
    monkeypatch.setattr(
        tr, "_deezer_search", lambda q: called.__setitem__("deezer_search", True)
    )
    monkeypatch.setattr(
        tr, "_download_item", lambda *a: called.__setitem__("download_item", True)
    )

    dt = tr.download_freeform("https://youtu.be/abc", str(tmp_path))
    assert dt is not None
    assert dt.source == "youtube"
    assert dt.artist == "Artist" and dt.title == "Title"
    assert called == {"deezer_search": False, "download_item": False}


def test_freeform_youtube_url_falls_back_to_search(monkeypatch, tmp_path):
    """Прямой yt-dlp не смог -> og:title -> поиск по имени."""
    monkeypatch.setattr(tr, "_ytdlp_download_url", lambda u, o, t: None)
    monkeypatch.setattr(tr, "_scrape_url_title", lambda u: "Fallback Name")
    seen = {}

    def fake_search(q):
        seen["q"] = q
        return {"deezer_id": 1, "artist": "A", "title": "T"}

    monkeypatch.setattr(tr, "_deezer_search", fake_search)
    monkeypatch.setattr(tr, "_download_item", lambda item, o, t: _dt("deezer"))

    dt = tr.download_freeform("https://youtu.be/broken", str(tmp_path))
    assert dt.source == "deezer"
    assert seen["q"] == "Fallback Name"


def test_freeform_name_uses_deezer_then_download(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tr, "_deezer_search", lambda q: {"deezer_id": 99, "artist": "A", "title": "T"}
    )
    captured = {}

    def fake_item(item, out_dir, timeout):
        captured["item"] = item
        return _dt("deezer")

    monkeypatch.setattr(tr, "_download_item", fake_item)
    dt = tr.download_freeform("Some Artist Song", str(tmp_path))
    assert dt.source == "deezer"
    assert captured["item"]["deezer_id"] == 99


def test_freeform_name_no_deezer_hit_still_tries_youtube(monkeypatch, tmp_path):
    """Deezer-поиск пуст -> item с одним title -> _download_item (yt-dlp по artist/title)."""
    monkeypatch.setattr(tr, "_deezer_search", lambda q: None)
    captured = {}

    def fake_item(item, out_dir, timeout):
        captured["item"] = item
        return _dt("youtube")

    monkeypatch.setattr(tr, "_download_item", fake_item)
    dt = tr.download_freeform("Obscure Track", str(tmp_path))
    assert dt.source == "youtube"
    assert captured["item"] == {"artist": "", "title": "Obscure Track"}


def test_freeform_deezer_url_direct(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tr,
        "_deezer_track_from_url",
        lambda u: {"deezer_id": 5, "artist": "A", "title": "T", "isrc": "X"},
    )
    captured = {}

    def fake_item(item, out_dir, timeout):
        captured["item"] = item
        return _dt("deezer")

    monkeypatch.setattr(tr, "_download_item", fake_item)
    dt = tr.download_freeform("https://www.deezer.com/track/5", str(tmp_path))
    assert dt.source == "deezer"
    assert captured["item"]["deezer_id"] == 5


def test_freeform_spotify_url_scrapes_then_searches(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "_scrape_url_title", lambda u: "Resolved Artist Title")
    seen = {}

    def fake_search(q):
        seen["q"] = q
        return {"deezer_id": 1, "artist": "A", "title": "T"}

    monkeypatch.setattr(tr, "_deezer_search", fake_search)
    monkeypatch.setattr(tr, "_download_item", lambda item, o, t: _dt("deezer"))
    dt = tr.download_freeform("https://open.spotify.com/track/xyz", str(tmp_path))
    assert dt.source == "deezer"
    assert seen["q"] == "Resolved Artist Title"


def test_freeform_other_url_uses_slug_no_fetch(monkeypatch, tmp_path):
    """'other'-хост НЕ фетчим с сервера (SSRF) — берём слаг из URL."""

    def no_fetch(*a, **k):
        raise AssertionError("must not fetch on 'other' branch")

    monkeypatch.setattr(tr, "_scrape_url_title", no_fetch)
    monkeypatch.setattr(tr, "_deezer_search", lambda q: None)
    captured = {}

    def fake_item(item, out_dir, timeout):
        captured["item"] = item
        return _dt("youtube")

    monkeypatch.setattr(tr, "_download_item", fake_item)
    dt = tr.download_freeform("https://example.com/my-song-name", str(tmp_path))
    assert dt.source == "youtube"
    assert captured["item"]["title"] == "my song name"


def test_freeform_spotify_url_unresolvable_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "_scrape_url_title", lambda u: "")
    # og:title пуст и слаг пуст (нет пути) -> None
    assert tr.download_freeform("https://open.spotify.com/", str(tmp_path)) is None
