"""Upload the 500 pre-rendered pool videos to the shared MinIO af-content bucket.

For every video in the batch manifest this script mints a catalog identity
(UUIDv7 content_id, sha256 content_hash), uploads original.mp4 + thumb.jpg
under the catalog key convention `music/video/{yyyy}/{mm}/{dd}/{content_id}/`,
and finally emits an identity-only `register_manifest.json` for the colleague's
`pool_register_catalog.py` (policy fields — allowed_platforms/source/kind — are
deliberately NOT frozen here; they are bound at register time on the farm side).

Resume-safe: identities are minted and persisted BEFORE any network I/O
(`ingest_state.json`), uploads are skipped when the object already exists.

Run from the repo root (.env must hold shared-MinIO MINIO_URL/ACCESS/SECRET):

    python scripts/pool_upload_minio.py --limit 1 --dry-run   # plan only
    python scripts/pool_upload_minio.py --limit 1             # smoke unit
    python scripts/pool_upload_minio.py                       # all 500
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.json_index import load_json_list, save_json_atomic  # noqa: E402
from modules.minio_client import build_minio_client  # noqa: E402
from modules.utils import get_media_duration  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pool_upload_minio")

CONTENT_BUCKET = "af-content"
PROJECT = "music"
CONTENT_TYPE = "video"
INGEST_PREFIX = "_ingest/agentmusic-pool-500"


def _uuid7() -> str:
    """Inline RFC 9562 UUIDv7 (Python 3.11 has no uuid7; catalog requires v7)."""
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    value = ts_ms << 80
    value |= 0x7 << 76                  # version 7
    value |= secrets.randbits(12) << 64  # rand_a
    value |= 0b10 << 62                 # variant
    value |= secrets.randbits(62)       # rand_b
    return str(uuid.UUID(int=value))


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.stat_object(bucket, key)
        return True
    except Exception:
        return False


def _resolve_local(manifest_dir: str, raw: str) -> str:
    """Manifest paths are dev-box-relative; when the tree is relocated (e.g. to
    output/_pool_src, safe from bot startup cleanup), fall back to resolving the
    last two path components next to the manifest itself."""
    p = (raw or "").replace("\\", "/")
    if os.path.exists(p):
        return p
    parts = [x for x in p.split("/") if x]
    if len(parts) >= 2:
        cand = os.path.join(manifest_dir, *parts[-2:])
        if os.path.exists(cand):
            return cand
    return p


def _make_thumb(video_path: str, out_path: str) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", "1", "-i", video_path,
           "-frames:v", "1", "-vf", "scale=360:-2", out_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        return proc.returncode == 0 and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.warning("thumb failed for %s: %s", video_path, e)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload pool videos to shared MinIO af-content")
    parser.add_argument("--manifest", default="output/batch/chart_top50/manifest.json")
    parser.add_argument("--state", default="output/batch/chart_top50/ingest_state.json")
    parser.add_argument("--register-manifest", default="output/batch/chart_top50/register_manifest.json")
    parser.add_argument("--limit", type=int, default=0, help="only first N videos (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    videos = [r for r in load_json_list(args.manifest) if r.get("status") == "ok"]
    videos.sort(key=lambda r: (r.get("position", 0), r.get("video_index", 0)))
    if args.limit:
        videos = videos[: args.limit]
    if not videos:
        logger.error("Манифест пуст: %s", args.manifest)
        return 2

    state_rows = load_json_list(args.state)
    state = {r["output"]: r for r in state_rows}

    def _flush() -> None:
        save_json_atomic(args.state, list(state.values()))

    client = None
    if not args.dry_run:
        client = build_minio_client()
        if client is None:
            logger.error("MinIO не сконфигурирован (.env MINIO_URL/ACCESS/SECRET — общий сервер)")
            return 2
        if not client.bucket_exists(CONTENT_BUCKET):
            logger.error("Бакет %s не существует на MinIO — создайте его (mc mb)", CONTENT_BUCKET)
            return 2

    manifest_dir = os.path.dirname(os.path.abspath(args.manifest))
    uploaded = skipped = failed = 0
    for video in videos:
        local = _resolve_local(manifest_dir, video.get("output"))
        if not os.path.exists(local):
            logger.error("Файл пропал: %s", local)
            failed += 1
            continue

        rec = state.get(local)
        if rec is None:
            # mint -> persist BEFORE any network I/O (crash-safe identity)
            content_id = _uuid7()
            ingest_date = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            prefix = f"{PROJECT}/{CONTENT_TYPE}/{ingest_date}/{content_id}"
            rec = {
                "output": local,
                "track_id": video.get("track_id", ""),
                "video_index": video.get("video_index", 0),
                "position": video.get("position", 0),
                "artist": video.get("artist", ""),
                "title": video.get("title", ""),
                "content_id": content_id,
                "command_id": _uuid7(),
                "ingest_date": ingest_date,
                "original_key": f"{prefix}/original.mp4",
                "thumb_key": f"{prefix}/thumb.jpg",
                "uploaded_original": False,
                "uploaded_thumb": False,
            }
            state[local] = rec
            if not args.dry_run:
                _flush()

        if args.dry_run:
            print(f"{rec['content_id']}  <-  {local}")
            continue

        try:
            if not rec.get("content_hash"):
                rec["content_hash"] = _sha256_file(local)
                _flush()
            if not rec.get("duration_seconds"):
                rec["duration_seconds"] = round(get_media_duration(local), 2)
                _flush()

            if not rec.get("uploaded_original"):
                if not _object_exists(client, CONTENT_BUCKET, rec["original_key"]):
                    client.fput_object(CONTENT_BUCKET, rec["original_key"], local,
                                       content_type="video/mp4")
                rec["uploaded_original"] = True
                _flush()

            if not rec.get("uploaded_thumb"):
                tmp = tempfile.mktemp(suffix=".jpg")
                if not _object_exists(client, CONTENT_BUCKET, rec["thumb_key"]):
                    if _make_thumb(local, tmp):
                        client.fput_object(CONTENT_BUCKET, rec["thumb_key"], tmp,
                                           content_type="image/jpeg")
                    else:
                        logger.warning("Без превью: %s", local)
                rec["uploaded_thumb"] = True
                _flush()
                try:
                    os.remove(tmp)
                except OSError:
                    pass

            uploaded += 1
            logger.info("[%d/%d] %s — %s #%d", uploaded + skipped, len(videos),
                        rec["artist"], rec["title"], rec["video_index"])
        except Exception as e:
            logger.error("Ошибка юнита %s: %s", local, e)
            failed += 1

    if args.dry_run:
        print(f"\nПлан: {len(videos)} видео -> {CONTENT_BUCKET}/{PROJECT}/{CONTENT_TYPE}/...")
        return 0

    # identity-only register manifest: policy (allowed_platforms/source/kind)
    # is intentionally absent — it is bound at register time on the farm side
    register_rows = []
    for video in videos:
        rec = state.get(_resolve_local(manifest_dir, video.get("output")))
        if not rec or not rec.get("uploaded_original"):
            continue
        register_rows.append({
            "content_id": rec["content_id"],
            "command_id": rec["command_id"],
            "content_hash": rec["content_hash"],
            "bucket": CONTENT_BUCKET,
            "original_key": rec["original_key"],
            "thumb_key": rec["thumb_key"],
            "project": PROJECT,
            "content_type": CONTENT_TYPE,
            "width": 1080,
            "height": 1920,
            "duration_seconds": rec.get("duration_seconds", 0),
            "label": f"{rec['position']:02d} {rec['artist']} - {rec['title']} #{rec['video_index']}",
            "source_job_id": f"pool-{rec['track_id']}-{rec['video_index']:02d}",
        })
    save_json_atomic(args.register_manifest, register_rows)

    # publish the handoff pair into MinIO: durable anonymous-read path + presigned URLs
    handoff = {
        f"{INGEST_PREFIX}/register_manifest.json": args.register_manifest,
        f"{INGEST_PREFIX}/pool_register_catalog.py": str(ROOT / "scripts" / "pool_register_catalog.py"),
    }
    print("\n=== Передача коллеге ===")
    for key, path in handoff.items():
        client.fput_object(CONTENT_BUCKET, key, path, content_type="application/octet-stream")
        try:
            from datetime import timedelta
            url = client.presigned_get_object(CONTENT_BUCKET, key, expires=timedelta(days=7))
            print(f"  {key}\n    presigned (7 дней): {url}")
        except Exception as e:
            logger.warning("presigned URL failed for %s: %s", key, e)
    print(f"  Долговечный путь (если на af-content включён anonymous read): "
          f"<minio-endpoint>/{CONTENT_BUCKET}/{INGEST_PREFIX}/...")

    print("\n=== Итог ===")
    print(f"  готово: {uploaded}, ошибок: {failed}, в register-манифесте: {len(register_rows)}")
    print(f"  манифест: {args.register_manifest}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
