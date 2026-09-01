"""Bulk footage pool downloader for mass video production.

Fills ``output/_footage_cache`` with portrait stock clips from Pixabay/Pexels
using ``footage.batch_queries`` from config.yaml (fallback: base_queries),
then dedupes identical videos across query subdirs and drops corrupt files.

Run from the repo root (.env must hold PIXABAY_API_KEY and/or PEXELS_API_KEY):

    python scripts/fetch_footage_pool.py                     # full pool (~150-200 clips)
    python scripts/fetch_footage_pool.py --per-query 2 --rounds 1 --target-total 20  # smoke
    python scripts/fetch_footage_pool.py --validate-only     # just dedupe + ffprobe pass
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from modules.config import settings  # noqa: E402
from modules.footage_prewarm import cache_dir, list_cached_videos  # noqa: E402
from modules.footage_searcher import search_and_download  # noqa: E402
from modules.utils import get_media_duration  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetch_footage_pool")

ROUND_PAUSE_SEC = 60  # keeps us far inside Pixabay 100 req/60s and Pexels hourly limits


def _load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _batch_queries(config: dict) -> list[str]:
    footage = config.get("footage", {}) or {}
    queries = footage.get("batch_queries") or footage.get("base_queries") or []
    return [q for q in queries if isinstance(q, str) and q.strip()]


def _dedupe_cache(output_base: str) -> int:
    """Deletes duplicates of the same (source, video_id) across query subdirs."""
    seen: dict[tuple[str, str], str] = {}
    removed = 0
    for path in sorted(list_cached_videos(output_base)):
        stem = Path(path).stem
        parts = stem.split("_")
        if len(parts) < 4:
            continue  # foreign filename, leave as is
        key = (parts[0], parts[-2])  # (source, video_id); query in between may contain "_"
        if key in seen:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        else:
            seen[key] = path
    if removed:
        logger.info("Дедупликация: удалено %d повторов", removed)
    return removed


def _validate_cache(output_base: str, min_duration: int) -> int:
    """Drops files ffprobe can't parse or that are shorter than min_duration."""
    removed = 0
    for path in list_cached_videos(output_base):
        try:
            duration = get_media_duration(path)
        except Exception:
            duration = 0.0
        if duration < min_duration:
            try:
                os.remove(path)
                removed += 1
                logger.info("Удалён битый/короткий клип (%.1fs): %s", duration, os.path.basename(path))
            except OSError:
                pass
    return removed


def _pool_stats(output_base: str) -> tuple[int, float]:
    clips = list_cached_videos(output_base)
    size_gb = sum(os.path.getsize(p) for p in clips) / 1024**3
    return len(clips), size_gb


async def _run(args: argparse.Namespace) -> int:
    config = _load_config()
    output_base = settings.output_dir
    cache_root = cache_dir(output_base)
    min_duration = int(config.get("footage", {}).get("min_duration_sec", 10) or 10)

    queries = (
        [q.strip() for q in args.queries.split(",") if q.strip()]
        if args.queries
        else _batch_queries(config)
    )
    if not queries:
        logger.error("Список запросов пуст (config footage.batch_queries)")
        return 2

    if args.dry_run:
        print(f"Запросы ({len(queries)}): {', '.join(queries)}")
        count, size_gb = _pool_stats(output_base)
        print(f"Пул сейчас: {count} клипов ({size_gb:.2f} GB) в {cache_root}")
        return 0

    if args.validate_only:
        _dedupe_cache(output_base)
        removed = _validate_cache(output_base, min_duration)
        count, size_gb = _pool_stats(output_base)
        print(f"Валидация: удалено {removed}, осталось {count} клипов ({size_gb:.2f} GB)")
        return 0

    if not (settings.pixabay_api_key or settings.pexels_api_key):
        logger.error("Не заданы PIXABAY_API_KEY / PEXELS_API_KEY в .env")
        return 2

    os.makedirs(cache_root, exist_ok=True)
    for round_num in range(1, args.rounds + 1):
        count, _ = _pool_stats(output_base)
        if count >= args.target_total:
            logger.info("Цель достигнута: %d клипов", count)
            break
        logger.info(
            "Раунд %d/%d: в пуле %d/%d, качаю по %d на запрос...",
            round_num, args.rounds, count, args.target_total, args.per_query,
        )
        started = time.monotonic()
        await search_and_download(
            queries=queries,
            pixabay_key=settings.pixabay_api_key,
            pexels_key=settings.pexels_api_key,
            output_dir=cache_root,
            orientation=args.orientation,
            min_duration=min_duration,
            results_per_query=args.per_query,
            cache_dir=cache_root,
            page_spread=args.page_spread,
            download_timeout=args.download_timeout,
        )
        _dedupe_cache(output_base)
        _validate_cache(output_base, min_duration)
        logger.info("Раунд %d занял %.0f сек", round_num, time.monotonic() - started)

        count, _ = _pool_stats(output_base)
        if count < args.target_total and round_num < args.rounds:
            logger.info("Пауза %d сек (лимиты API)...", ROUND_PAUSE_SEC)
            await asyncio.sleep(ROUND_PAUSE_SEC)

    count, size_gb = _pool_stats(output_base)
    per_dir: dict[str, int] = {}
    for p in list_cached_videos(output_base):
        per_dir[Path(p).parent.name] = per_dir.get(Path(p).parent.name, 0) + 1
    print("\n=== Итог ===")
    for name, n in sorted(per_dir.items()):
        print(f"  {name}: {n}")
    print(f"Всего: {count} клипов ({size_gb:.2f} GB) в {cache_root}")
    if count < args.target_total:
        print(f"Цель {args.target_total} не достигнута — можно перезапустить позже (докачает)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk footage pool downloader (Pixabay/Pexels)")
    parser.add_argument("--target-total", type=int, default=180)
    parser.add_argument("--per-query", type=int, default=5, help="clips per query per source per round")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    parser.add_argument("--page-spread", type=int, default=3, help="random API page range (niche queries have few pages)")
    parser.add_argument("--download-timeout", type=int, default=90, help="per-clip stalled-read timeout, sec (queue wait not counted)")
    parser.add_argument("--queries", default="", help="comma-separated override of config batch_queries")
    parser.add_argument("--validate-only", action="store_true", help="only dedupe + ffprobe-validate the cache")
    parser.add_argument("--dry-run", action="store_true", help="print queries and pool stats, no downloads")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
