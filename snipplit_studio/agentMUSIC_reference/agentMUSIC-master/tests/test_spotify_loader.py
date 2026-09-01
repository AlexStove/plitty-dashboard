"""Unit-тесты оркестрации источников скачивания (без сети/бинарников)."""

import json

import modules.spotify_loader as sl


def _item() -> dict:
    return {
        "artist": "A", "title": "T", "track_id": "id",
        "isrc": "US1234567890", "preview_url": None, "duration": 200.0,
    }


def test_auto_prefers_deezer(monkeypatch):
    monkeypatch.setattr(sl, "_download_via_deezer", lambda i, o, t: "/x/deezer.mp3")
    monkeypatch.setattr(sl, "_download_via_youtube", lambda i, o, t: "/x/yt.mp3")
    monkeypatch.setattr(sl, "_download_preview", lambda i, o: "/x/prev.mp3")
    monkeypatch.setattr(sl, "_probe_duration", lambda p: 200.0)

    dt = sl._download_one(_item(), "/out", "auto", 300)
    assert dt is not None
    assert dt.source == "deezer"
    assert dt.is_preview is False
    assert dt.path == "/x/deezer.mp3"


def test_youtube_mode_skips_deezer(monkeypatch):
    called = {"deezer": False}

    def _dz(i, o, t):
        called["deezer"] = True
        return "/x/deezer.mp3"

    monkeypatch.setattr(sl, "_download_via_deezer", _dz)
    monkeypatch.setattr(sl, "_download_via_youtube", lambda i, o, t: "/x/yt.mp3")
    monkeypatch.setattr(sl, "_download_preview", lambda i, o: None)
    monkeypatch.setattr(sl, "_probe_duration", lambda p: 200.0)

    dt = sl._download_one(_item(), "/out", "youtube", 300)
    assert called["deezer"] is False
    assert dt is not None and dt.source == "youtube"


def test_deezer_mode_skips_youtube_then_labeled_preview(monkeypatch):
    called = {"yt": False}

    def _yt(i, o, t):
        called["yt"] = True
        return "/x/yt.mp3"

    monkeypatch.setattr(sl, "_download_via_deezer", lambda i, o, t: None)
    monkeypatch.setattr(sl, "_download_via_youtube", _yt)
    monkeypatch.setattr(sl, "_download_preview", lambda i, o: "/x/prev.mp3")
    monkeypatch.setattr(sl, "_probe_duration", lambda p: 30.0)

    dt = sl._download_one(_item(), "/out", "deezer", 300)
    assert called["yt"] is False
    assert dt is not None
    assert dt.source == "preview"
    assert dt.is_preview is True


def test_auto_falls_back_to_labeled_preview(monkeypatch):
    monkeypatch.setattr(sl, "_download_via_deezer", lambda i, o, t: None)
    monkeypatch.setattr(sl, "_download_via_youtube", lambda i, o, t: None)
    monkeypatch.setattr(sl, "_download_preview", lambda i, o: "/x/prev.mp3")
    monkeypatch.setattr(sl, "_probe_duration", lambda p: 30.0)

    dt = sl._download_one(_item(), "/out", "auto", 300)
    assert dt is not None
    assert dt.is_preview is True
    assert dt.source == "preview"


def test_all_sources_fail_returns_none(monkeypatch):
    monkeypatch.setattr(sl, "_download_via_deezer", lambda i, o, t: None)
    monkeypatch.setattr(sl, "_download_via_youtube", lambda i, o, t: None)
    monkeypatch.setattr(sl, "_download_preview", lambda i, o: None)

    assert sl._download_one(_item(), "/out", "auto", 300) is None


class _FakeResp:
    def __init__(self, data):
        self._d = data

    def read(self):
        return json.dumps(self._d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_deezer_id_from_isrc_found(monkeypatch):
    monkeypatch.setattr(
        sl.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp({"id": 123, "title": "X"}),
    )
    assert sl._deezer_id_from_isrc("US1234567890") == 123


def test_deezer_id_from_isrc_not_found(monkeypatch):
    monkeypatch.setattr(
        sl.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp({"error": {"code": 800, "message": "no data"}}),
    )
    assert sl._deezer_id_from_isrc("BADISRC") is None
