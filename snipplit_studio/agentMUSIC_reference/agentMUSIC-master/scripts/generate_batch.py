"""Mass karaoke video generation: N videos per chart track, distinct footage each.

Reads successful tracks from ``output/batch/tracks_manifest.json`` (built by
scripts/fetch_chart_tracks.py) and the footage pool from ``output/_footage_cache``
(built by scripts/fetch_footage_pool.py), then renders
``output/batch/<run-name>/<NN_artist_title>/karaoke_01..NN.mp4``.

Footage assignment is seeded per track and persisted into the run manifest, so
re-runs are resume-safe and deterministic: already-rendered files are skipped.

Run from the repo root:

    python scripts/generate_batch.py --limit 2 --videos-per-track 2   # smoke (4 videos)
    python scripts/generate_batch.py                                  # full (50x10 = 500)
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from modules import chorus_db, video_db  # noqa: E402
from modules.api_worker import _deserialize_lyrics  # noqa: E402
from modules.bundle1_karaoke import build_karaoke  # noqa: E402
from modules.config import settings  # noqa: E402
from modules.footage_prewarm import list_cached_videos  # noqa: E402
from modules.json_index import load_json_list, save_json_atomic  # noqa: E402
from modules.styles import DEFAULT_STYLE, STYLE_PRESETS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("generate_batch")

_FORBIDDEN = '<>:"/\\|?*'


def _load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _slug(artist: str, title: str, position: int) -> str:
    raw = f"{artist} {title}".strip() or "track"
    cleaned = "".join(c for c in raw if c not in _FORBIDDEN and c.isprintable())
    cleaned = "_".join(cleaned.split())[:50].strip("._ ") or "track"
    return f"{position:02d}_{cleaned}"


def _assign_footage(track_id: str, pool: list[str], count: int, seed: int) -> list[str]:
    """Deterministic per-track pick of `count` distinct clips (repeats only if pool is small)."""
    rng = random.Random(f"{seed}:{track_id}")
    if len(pool) >= count:
        return rng.sample(pool, count)
    logger.warning("Пул футажей (%d) меньше videos-per-track (%d) — будут повторы", len(pool), count)
    picks: list[str] = []
    while len(picks) < count:
        picks.extend(rng.sample(pool, len(pool)))
    return picks[:count]


def _style_for(index: int, base_style: str, rotate: bool) -> str:
    if not rotate:
        return base_style
    keys = list(STYLE_PRESETS)
    return keys[(index - 1) % len(keys)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Mass karaoke generation from chart tracks + footage pool")
    parser.add_argument("--videos-per-track", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="only first N tracks (0 = all)")
    parser.add_argument("--run-name", default="chart_top50")
    parser.add_argument("--user-id", type=int, default=settings.owner_id)
    parser.add_argument("--style", choices=sorted(STYLE_PRESETS), default=DEFAULT_STYLE)
    parser.add_argument("--rotate-styles", action="store_true", help="cycle all styles across a track's videos")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    parser.add_argument("--register-videos", action="store_true", help="also copy results into video_db (doubles disk)")
    parser.add_argument("--dry-run", action="store_true", help="print the render plan, no ffmpeg")
    args = parser.parse_args()

    config = _load_config()
    output_base = settings.output_dir
    fonts_dir = config.get("paths", {}).get("fonts_dir", "./fonts")
    highlight_color = config.get("karaoke", {}).get("highlight_color", "0xFFD700")

    tracks = [
        t for t in load_json_list(os.path.join(output_base, "batch", "tracks_manifest.json"))
        if t.get("status") == "ok" and t.get("chorus_id")
    ]
    tracks.sort(key=lambda t: t.get("position", 0))
    if args.limit:
        tracks = tracks[: args.limit]
    if not tracks:
        logger.error("Нет готовых треков — сначала запустите scripts/fetch_chart_tracks.py")
        return 2

    pool = sorted(list_cached_videos(output_base))
    if not pool:
        logger.error("Пул футажей пуст — сначала запустите scripts/fetch_footage_pool.py")
        return 2
    logger.info("Треков: %d, футажей в пуле: %d, видео на трек: %d", len(tracks), len(pool), args.videos_per_track)

    run_dir = os.path.join(output_base, "batch", args.run_name)
    os.makedirs(run_dir, exist_ok=True)
    manifest_path = os.path.join(run_dir, "manifest.json")
    manifest = {(r["track_id"], r["video_index"]): r for r in load_json_list(manifest_path)}

    def _flush() -> None:
        if args.dry_run:
            return  # план фиксируется в манифесте только при реальном рендере
        rows = sorted(manifest.values(), key=lambda r: (r.get("position", 0), r["video_index"]))
        save_json_atomic(manifest_path, rows)

    rendered = skipped = failed = 0
    for track in tracks:
        chorus = chorus_db.get_chorus(output_base, args.user_id, track["chorus_id"])
        if not chorus:
            logger.error("Припев %s не найден (трек %s) — пропуск", track["chorus_id"], track["title"])
            failed += args.videos_per_track
            continue
        lyrics = _deserialize_lyrics(chorus.get("lyrics") or [])
        track_dir = os.path.join(run_dir, _slug(track["artist"], track["title"], track.get("position", 0)))
        assignment = _assign_footage(track["track_id"], pool, args.videos_per_track, args.seed)

        for idx in range(1, args.videos_per_track + 1):
            key = (track["track_id"], idx)
            row = manifest.get(key) or {
                "track_id": track["track_id"],
                "chorus_id": track["chorus_id"],
                "artist": track["artist"],
                "title": track["title"],
                "position": track.get("position", 0),
                "video_index": idx,
                "footage": assignment[idx - 1],
                "style": _style_for(idx, args.style, args.rotate_styles),
                "palette_seed": idx - 1,
                "output": os.path.join(track_dir, f"karaoke_{idx:02d}.mp4"),
                "status": "pending",
            }
            manifest[key] = row

            if os.path.exists(row["output"]) and os.path.getsize(row["output"]) > 0:
                if row.get("status") != "ok":
                    row["status"] = "ok"
                skipped += 1
                continue

            if not os.path.exists(row["footage"]):
                substitute = random.Random(f"{args.seed}:{key}").choice(pool)
                logger.warning("Футаж пропал (%s) — замена на %s", os.path.basename(row["footage"]), os.path.basename(substitute))
                row["footage"] = substitute
                row["substituted"] = True

            if args.dry_run:
                print(f"{row['output']}  <-  {os.path.basename(row['footage'])}  [{row['style']}]")
                continue

            tmp_dir = os.path.join(run_dir, "_tmp", f"{track['track_id']}_{idx}")
            os.makedirs(tmp_dir, exist_ok=True)
            started = time.monotonic()
            try:
                result = build_karaoke(
                    lyrics_lines=lyrics,
                    background_videos=[row["footage"]],
                    chorus_audio_path=chorus["path"],
                    output_dir=tmp_dir,
                    fonts_dir=fonts_dir,
                    orientation=args.orientation,
                    highlight_color=highlight_color,
                    style=dict(STYLE_PRESETS[row["style"]]),  # copy: renderer mutates it
                    use_animated_bg=False,
                    palette_seed=row["palette_seed"],
                )
            except Exception as e:
                logger.error("Рендер упал (%s #%d): %s", track["title"], idx, e)
                result = None

            row["render_seconds"] = round(time.monotonic() - started, 1)
            if result and os.path.exists(result.output_path):
                os.makedirs(track_dir, exist_ok=True)
                shutil.move(result.output_path, row["output"])
                row["status"] = "ok"
                rendered += 1
                logger.info(
                    "[%d] %s #%d за %.0f сек (%s)",
                    rendered, track["title"], idx, row["render_seconds"], os.path.basename(row["footage"]),
                )
                if args.register_videos:
                    try:
                        video_db.save_video(
                            output_base=output_base, user_id=args.user_id,
                            src_path=row["output"], chorus_id=track["chorus_id"],
                            track_id=track["track_id"], scenario="karaoke",
                            bg_type="footage", orientation=args.orientation,
                        )
                    except Exception as e:
                        logger.warning("video_db registration failed: %s", e)
            else:
                row["status"] = "error"
                failed += 1
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _flush()
        _flush()

    shutil.rmtree(os.path.join(run_dir, "_tmp"), ignore_errors=True)
    total = len(tracks) * args.videos_per_track
    print("\n=== Итог ===")
    print(f"  отрендерено: {rendered}, пропущено (готовые): {skipped}, ошибок: {failed}, всего план: {total}")
    print(f"  манифест: {manifest_path}")
    if failed:
        print("  перезапустите команду — ошибочные позиции будут повторены")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
