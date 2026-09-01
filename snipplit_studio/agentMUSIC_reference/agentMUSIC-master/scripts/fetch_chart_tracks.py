"""Deezer chart -> downloaded tracks -> transcription -> choruses.

Pulls the public Deezer chart (no API key), downloads full audio through the
existing Deezer(ARL)/yt-dlp chain, then runs the canonical processing path
(whisper transcription + chorus extraction) until ``--target`` tracks succeed.
Resume-safe: progress is kept in ``output/batch/tracks_manifest.json`` and
already-succeeded chart entries are skipped on re-run.

Run from the repo root (.env: DEEZER_ARL recommended, TELEGRAM token not needed):

    python scripts/fetch_chart_tracks.py --dry-run       # print the chart, no downloads
    python scripts/fetch_chart_tracks.py --target 2      # smoke: 2 tracks end-to-end
    python scripts/fetch_chart_tracks.py                 # full: 50 tracks
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from modules import chorus_db, track_db  # noqa: E402
from modules.config import settings  # noqa: E402
from modules.json_index import load_json_list, save_json_atomic  # noqa: E402
from modules.track_resolver import _download_item, _http_get  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetch_chart_tracks")

MANIFEST = "tracks_manifest.json"


def _manifest_path(output_base: str) -> str:
    return os.path.join(output_base, "batch", MANIFEST)


def _norm(s: str) -> str:
    """Normalized (artist, title) key for chart-level dedupe."""
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return " ".join(s.split())


def fetch_chart(chart_id: int, limit: int) -> list[dict]:
    """Deezer chart entries in position order, deduped by (artist, short title)."""
    url = f"https://api.deezer.com/chart/{chart_id}/tracks?limit={limit}"
    data = json.loads(_http_get(url, timeout=20))
    entries = []
    seen: set[tuple[str, str]] = set()
    for t in data.get("data") or []:
        dz_id = t.get("id")
        artist = (t.get("artist") or {}).get("name", "")
        title = t.get("title") or ""
        if not isinstance(dz_id, int) or not title:
            continue
        key = (_norm(artist), _norm(t.get("title_short") or title))
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "deezer_id": dz_id,
            "position": t.get("position") or len(entries) + 1,
            "artist": artist,
            "title": title,
            "duration": float(t.get("duration") or 0),
            "explicit": bool(t.get("explicit_lyrics")),
        })
    return entries


def _chorus_words(record: dict) -> int:
    total = 0
    for line in record.get("lyrics") or []:
        words = line.get("words") or []
        total += len(words) if words else len((line.get("text") or "").split())
    return total


def _best_chorus(choruses: list[dict]) -> dict | None:
    return max(choruses, key=_chorus_words) if choruses else None


def _find_existing_track(output_base: str, user_id: int, deezer_url: str) -> dict | None:
    for t in track_db.list_user_tracks(output_base, user_id):
        if t.get("spotify_url") == deezer_url:
            return t
    return None


def _download_entry(entry: dict, output_base: str, user_id: int, timeout: int) -> dict | None:
    """Downloads full audio and stores it in track_db. None on failure."""
    deezer_url = f"https://www.deezer.com/track/{entry['deezer_id']}"
    existing = _find_existing_track(output_base, user_id, deezer_url)
    if existing:
        logger.info("Уже скачан: %s — %s", entry["artist"], entry["title"])
        return existing

    tmp = tempfile.mkdtemp(prefix="chart_")
    try:
        item = {
            "deezer_id": entry["deezer_id"],
            "artist": entry["artist"],
            "title": entry["title"],
        }
        dt = _download_item(item, tmp, timeout)
        if not dt or dt.is_preview:
            return None
        return track_db.save_track(
            output_base=output_base,
            user_id=user_id,
            src_path=dt.path,
            source=dt.source,
            artist=entry["artist"],
            title=entry["title"],
            duration=dt.duration,
            spotify_url=deezer_url,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _process_entry(track_id: str, output_base: str, user_id: int, reprocess: bool) -> tuple[str, dict | None]:
    """Transcribe + extract choruses via the canonical API path.

    Returns (status, best_chorus): status in {"ok", "no_lyrics", "error"} where
    "ok" only means processing succeeded; the word-count gate is applied by the caller.
    """
    if not reprocess:
        existing = [c for c in chorus_db.list_user_choruses(output_base, user_id) if c.get("track_id") == track_id]
        if existing:
            return "ok", _best_chorus(existing)

    from api_server import process_track  # heavy import (whisper deps) — deferred

    try:
        result = process_track(track_id)
    except HTTPException as e:
        if e.status_code == 422:
            return "no_lyrics", None
        logger.error("process_track(%s) failed: %s", track_id, e.detail)
        return "error", None
    except Exception as e:
        logger.error("process_track(%s) crashed: %s", track_id, e)
        return "error", None
    return "ok", _best_chorus(result.get("choruses") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Deezer chart -> tracks -> choruses")
    parser.add_argument("--target", type=int, default=50, help="how many tracks must fully succeed")
    parser.add_argument("--fetch-limit", type=int, default=80, help="chart positions to fetch (buffer for failures)")
    parser.add_argument("--chart-id", type=int, default=0, help="0 = global; other Deezer editorial ids = country charts")
    parser.add_argument("--user-id", type=int, default=settings.owner_id, help="numeric output/<user_id> owner (must be digits)")
    parser.add_argument("--min-chorus-words", type=int, default=8)
    parser.add_argument("--min-duration", type=float, default=60.0)
    parser.add_argument("--max-duration", type=float, default=480.0)
    parser.add_argument("--timeout", type=int, default=300, help="per-track download timeout, sec")
    parser.add_argument("--dry-run", action="store_true", help="print the chart and exit")
    parser.add_argument("--skip-processing", action="store_true", help="download only, no whisper/choruses")
    parser.add_argument("--reprocess", action="store_true", help="re-run processing even if choruses exist")
    args = parser.parse_args()

    output_base = settings.output_dir
    entries = fetch_chart(args.chart_id, args.fetch_limit)
    if not entries:
        logger.error("Чарт пуст — Deezer API недоступен?")
        return 1
    logger.info("Чарт #%d: %d позиций", args.chart_id, len(entries))

    if args.dry_run:
        for e in entries:
            mark = " [explicit]" if e["explicit"] else ""
            print(f"{e['position']:>3}. {e['artist']} — {e['title']} ({e['duration']:.0f}s){mark}")
        return 0

    manifest_path = _manifest_path(output_base)
    manifest = {m["deezer_id"]: m for m in load_json_list(manifest_path)}

    def _flush() -> None:
        rows = sorted(manifest.values(), key=lambda m: m.get("position", 0))
        save_json_atomic(manifest_path, rows)

    successes = 0
    for entry in entries:
        if successes >= args.target:
            break
        dz_id = entry["deezer_id"]
        row = manifest.get(dz_id, dict(entry))
        row.update({k: entry[k] for k in ("position", "artist", "title", "duration")})
        manifest[dz_id] = row

        # resume: already fully succeeded and files are still on disk
        if row.get("status") == "ok" and row.get("track_id"):
            track = track_db.get_track(output_base, args.user_id, row["track_id"])
            chorus = chorus_db.get_chorus(output_base, args.user_id, row.get("chorus_id", ""))
            if track and chorus:
                successes += 1
                logger.info("[%d/%d] skip (готов): %s — %s", successes, args.target, entry["artist"], entry["title"])
                continue
            row["status"] = "stale"  # files vanished -> redo

        if not (args.min_duration <= entry["duration"] <= args.max_duration):
            row["status"] = "bad_duration"
            _flush()
            continue

        logger.info("Скачиваю: %s — %s (позиция %d)", entry["artist"], entry["title"], entry["position"])
        started = time.monotonic()
        try:
            track = _download_entry(entry, output_base, args.user_id, args.timeout)
        except Exception as e:
            logger.error("download crashed for %s: %s", entry["title"], e)
            track = None
        if not track:
            row["status"] = "download_failed"
            _flush()
            continue
        row.update({"track_id": track["id"], "source": track.get("source", "")})

        if args.skip_processing:
            row["status"] = "downloaded"
            _flush()
            continue

        status, chorus = _process_entry(track["id"], output_base, args.user_id, args.reprocess)
        if status == "ok" and chorus:
            words = _chorus_words(chorus)
            if words >= args.min_chorus_words:
                successes += 1
                row.update({
                    "status": "ok",
                    "chorus_id": chorus["id"],
                    "chorus_words": words,
                    "chorus_start": chorus.get("start", 0.0),
                    "chorus_end": chorus.get("end", 0.0),
                })
                logger.info(
                    "[%d/%d] OK за %.0f сек: %s — %s (%d слов)",
                    successes, args.target, time.monotonic() - started,
                    entry["artist"], entry["title"], words,
                )
            else:
                row["status"] = "no_lyrics"
                logger.info("Мало слов в припеве (%d < %d): %s", words, args.min_chorus_words, entry["title"])
        else:
            row["status"] = status if status != "ok" else "no_lyrics"
        _flush()

    by_status: dict[str, int] = {}
    for m in manifest.values():
        by_status[m.get("status", "?")] = by_status.get(m.get("status", "?"), 0) + 1
    print("\n=== Итог ===")
    for status, n in sorted(by_status.items()):
        print(f"  {status}: {n}")
    print(f"Успешно: {successes}/{args.target}; манифест: {manifest_path}")
    return 0 if successes >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())
