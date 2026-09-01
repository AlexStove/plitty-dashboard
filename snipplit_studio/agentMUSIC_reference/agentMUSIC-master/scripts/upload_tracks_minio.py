"""Upload the local track library mp3s to the shared MinIO music-tracks bucket.

This is the PORTABLE track path: any agentMUSIC instance can then import them
via POST /api/tracks/minio/import-batch (which re-transcribes on the server).
Run import-batch ONLY if the fast-path transplant (scripts/transplant_library.py)
was not done — otherwise the library is already warm and import would duplicate.

Run from the repo root (.env: shared-MinIO MINIO_URL/ACCESS/SECRET):

    python scripts/upload_tracks_minio.py --dry-run
    python scripts/upload_tracks_minio.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.config import settings  # noqa: E402
from modules.json_index import load_json_list  # noqa: E402
from modules.minio_client import build_minio_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("upload_tracks_minio")

_FORBIDDEN = '<>:"/\\|?*'


def _sanitize(s: str) -> str:
    cleaned = "".join(c for c in (s or "") if c not in _FORBIDDEN and c.isprintable())
    return " ".join(cleaned.split()).strip(". ") or "Unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload track mp3s to MinIO music-tracks")
    parser.add_argument("--user-id", type=int, default=settings.owner_id)
    parser.add_argument("--bucket", default=settings.minio_tracks_bucket)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    index_path = os.path.join(settings.output_dir, str(args.user_id), "_tracks", "index.json")
    tracks = load_json_list(index_path)
    if not tracks:
        logger.error("Библиотека пуста: %s", index_path)
        return 2

    client = None
    if not args.dry_run:
        client = build_minio_client()
        if client is None:
            logger.error("MinIO не сконфигурирован (.env MINIO_URL/ACCESS/SECRET)")
            return 2
        if not client.bucket_exists(args.bucket):
            client.make_bucket(args.bucket)

    uploaded = skipped = missing = 0
    for track in tracks:
        path = track.get("path", "")
        if not os.path.exists(path):
            missing += 1
            continue
        key = f"{_sanitize(track.get('artist', ''))}/{_sanitize(track.get('title', ''))}.mp3"
        if args.dry_run:
            print(f"{key}  <-  {path}")
            continue
        try:
            client.stat_object(args.bucket, key)
            skipped += 1
            continue
        except Exception:
            pass
        client.fput_object(args.bucket, key, path, content_type="audio/mpeg")
        uploaded += 1
        logger.info("[%d] %s", uploaded, key)

    print(f"\nЗагружено: {uploaded}, уже было: {skipped}, файлов нет на диске: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
