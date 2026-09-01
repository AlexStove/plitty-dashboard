"""
База готовых видео пользователя — JSON-индекс + mp4 файлы.

Хранит историю всех сгенерированных видео.
Структура:
  output/<user_id>/_videos/
    ├── index.json
    ├── <video_id>.mp4
    └── ...
"""

import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import Optional

from modules.json_index import load_json_list, save_json_atomic

logger = logging.getLogger(__name__)


def get_user_videos_dir(output_base: str, user_id: int) -> str:
    d = os.path.join(os.path.abspath(output_base), str(user_id), "_videos")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(videos_dir: str) -> str:
    return os.path.join(videos_dir, "index.json")


def _load_index(videos_dir: str) -> list[dict]:
    p = _index_path(videos_dir)
    try:
        return load_json_list(p)
    except Exception as e:
        logger.warning(f"Не удалось прочитать {p}: {e}")
        return []


def _save_index(videos_dir: str, index: list[dict]) -> None:
    save_json_atomic(_index_path(videos_dir), index)


def save_video(
    output_base: str,
    user_id: int,
    src_path: str,
    chorus_id: str,
    track_id: str,
    scenario: str,
    bg_type: str = "",
    orientation: str = "portrait",
) -> dict:
    """
    Копирует видео в базу пользователя.
    scenario: "karaoke" | "streamer"
    bg_type: "footage" | "animated" (только для karaoke)
    """
    videos_dir = get_user_videos_dir(output_base, user_id)
    video_id = uuid.uuid4().hex[:12]
    dst = os.path.join(videos_dir, f"{video_id}.mp4")
    shutil.copy2(src_path, dst)

    record = {
        "id": video_id,
        "chorus_id": chorus_id,
        "track_id": track_id,
        "path": dst,
        "scenario": scenario,
        "bg_type": bg_type,
        "orientation": orientation,
        "size_bytes": os.path.getsize(dst),
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
    }

    index = _load_index(videos_dir)
    index.append(record)
    _save_index(videos_dir, index)
    logger.info(f"Video saved: user={user_id} id={video_id} scenario={scenario}")
    return record


def _resolve_path(videos_dir: str, path: str) -> str:
    """Резолвит путь: если относительный — относительно videos_dir."""
    if os.path.isabs(path):
        return path
    # Пробуем от videos_dir (файл должен быть рядом с index.json)
    by_name = os.path.join(videos_dir, os.path.basename(path))
    if os.path.exists(by_name):
        return by_name
    return os.path.abspath(path)


def list_user_videos(output_base: str, user_id: int, limit: int = 50) -> list[dict]:
    videos_dir = get_user_videos_dir(output_base, user_id)
    index = _load_index(videos_dir)
    valid = []
    changed = False
    for r in index:
        raw_path = r.get("path", "")
        resolved = _resolve_path(videos_dir, raw_path)
        if os.path.exists(resolved):
            if resolved != raw_path:
                r["path"] = resolved
                changed = True
            valid.append(r)
    if changed or len(valid) != len(index):
        _save_index(videos_dir, valid)
    valid.sort(key=lambda r: r.get("rendered_at", ""), reverse=True)
    return valid[:limit]


def get_video(output_base: str, user_id: int, video_id: str) -> Optional[dict]:
    for r in list_user_videos(output_base, user_id, limit=10000):
        if r["id"] == video_id:
            return r
    return None


def cleanup_old(output_base: str, user_id: int, max_videos: int = 100) -> int:
    """Удаляет старые видео если их больше max. Возвращает кол-во удалённых."""
    videos_dir = get_user_videos_dir(output_base, user_id)
    items = list_user_videos(output_base, user_id, limit=10000)
    if len(items) <= max_videos:
        return 0
    to_delete = items[max_videos:]
    index = _load_index(videos_dir)
    keep_ids = {r["id"] for r in items[:max_videos]}
    new_index = []
    count = 0
    for r in index:
        if r["id"] in keep_ids:
            new_index.append(r)
        else:
            try:
                os.remove(r["path"])
                count += 1
            except OSError:
                pass
    _save_index(videos_dir, new_index)
    return count
