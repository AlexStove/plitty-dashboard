"""Unit-тесты базы треков (track_db) — save / update / get."""

from modules import track_db


def _make_src(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"ID3fakeaudio" * 100)
    return str(src)


def test_save_and_get_track(tmp_path):
    out = str(tmp_path / "output")
    src = _make_src(tmp_path)
    rec = track_db.save_track(out, user_id=1, src_path=src, source="upload", title="Song")
    assert rec["title"] == "Song"
    got = track_db.get_track(out, 1, rec["id"])
    assert got is not None
    assert got["id"] == rec["id"]


def test_update_track_merges_fields(tmp_path):
    out = str(tmp_path / "output")
    src = _make_src(tmp_path)
    rec = track_db.save_track(out, user_id=7, src_path=src, title="Old")

    updated = track_db.update_track(
        out, 7, rec["id"],
        title="New Title",
        artist="Artist",
        cover_local_path="/x/cover.jpg",
    )
    assert updated is not None
    assert updated["title"] == "New Title"
    assert updated["artist"] == "Artist"
    assert updated["cover_local_path"] == "/x/cover.jpg"

    # Перечитываем с диска — изменения сохранены
    got = track_db.get_track(out, 7, rec["id"])
    assert got["title"] == "New Title"
    assert got["cover_local_path"] == "/x/cover.jpg"


def test_update_track_ignores_none(tmp_path):
    out = str(tmp_path / "output")
    src = _make_src(tmp_path)
    rec = track_db.save_track(out, user_id=3, src_path=src, artist="Keep")

    track_db.update_track(out, 3, rec["id"], artist=None, title="T")
    got = track_db.get_track(out, 3, rec["id"])
    assert got["artist"] == "Keep"   # None не затёр
    assert got["title"] == "T"


def test_update_track_unknown_id_returns_none(tmp_path):
    out = str(tmp_path / "output")
    src = _make_src(tmp_path)
    track_db.save_track(out, user_id=5, src_path=src)
    assert track_db.update_track(out, 5, "doesnotexist", title="x") is None
