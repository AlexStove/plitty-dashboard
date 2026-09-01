"""
База треков пользователя — JSON-индекс + mp3 файлы.

Хранит: загруженные треки + скачанные через spotDL.
Структура:
  output/<user_id>/_tracks/
    ├── index.json
    ├── <track_id>.mp3
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


def get_user_tracks_dir(output_base: str, user_id: int) -> str:
    """Возвращает путь к папке треков пользователя, создавая если нужно."""
    d = os.path.join(output_base, str(user_id), "_tracks")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(tracks_dir: str) -> str:
    return os.path.join(tracks_dir, "index.json")


def _load_index(tracks_dir: str) -> list[dict]:
    p = _index_path(tracks_dir)
    try:
        return load_json_list(p)
    except Exception as e:
        logger.warning(f"Не удалось прочитать {p}: {e}")
        return []


def _save_index(tracks_dir: str, index: list[dict]) -> None:
    save_json_atomic(_index_path(tracks_dir), index)


def save_track(
    output_base: str,
    user_id: int,
    src_path: str,
    source: str = "upload",
    artist: str = "",
    title: str = "",
    duration: float = 0.0,
    spotify_url: str = "",
    is_preview: bool = False,
) -> dict:
    """
    Копирует трек в базу пользователя и добавляет запись в index.
    Возвращает dict-метаданные трека.
    """
    tracks_dir = get_user_tracks_dir(output_base, user_id)
    track_id = uuid.uuid4().hex[:12]
    dst = os.path.join(tracks_dir, f"{track_id}.mp3")
    shutil.copy2(src_path, dst)

    # Длительность: если не передана — пробуем измерить (ffprobe).
    if not duration or float(duration) <= 0:
        try:
            from modules.utils import get_media_duration
            duration = get_media_duration(dst)
        except Exception as e:
            logger.warning(f"duration probe failed for {dst}: {e}")
            duration = 0.0

    record = {
        "id": track_id,
        "path": dst,
        "source": source,
        "artist": artist,
        "title": title,
        "duration": float(duration),
        "spotify_url": spotify_url,
        "is_preview": bool(is_preview),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }

    index = _load_index(tracks_dir)
    index.append(record)
    _save_index(tracks_dir, index)
    logger.info(f"Track saved: user={user_id} id={track_id} title='{title}'")
    return record


def list_user_tracks(output_base: str, user_id: int) -> list[dict]:
    """Возвращает список всех треков пользователя (по убыванию даты)."""
    tracks_dir = get_user_tracks_dir(output_base, user_id)
    index = _load_index(tracks_dir)
    # Фильтруем удалённые файлы
    valid = [r for r in index if os.path.exists(r.get("path", ""))]
    if len(valid) != len(index):
        _save_index(tracks_dir, valid)
    valid.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    return valid


def get_track(output_base: str, user_id: int, track_id: str) -> Optional[dict]:
    """Возвращает запись трека по id или None."""
    for r in list_user_tracks(output_base, user_id):
        if r["id"] == track_id:
            return r
    return None


def update_track(output_base: str, user_id: int, track_id: str, **fields) -> Optional[dict]:
    """
    Обновляет поля записи трека по id (мерджит **fields в запись).
    None-значения игнорируются, чтобы не затирать уже имеющиеся данные.
    Возвращает обновлённую запись или None, если трек не найден.
    """
    tracks_dir = get_user_tracks_dir(output_base, user_id)
    index = _load_index(tracks_dir)
    updated = None
    for r in index:
        if r.get("id") == track_id:
            for k, v in fields.items():
                if v is not None:
                    r[k] = v
            updated = r
            break
    if updated is not None:
        _save_index(tracks_dir, index)
        logger.info(f"Track updated: user={user_id} id={track_id} fields={list(fields)}")
    else:
        logger.warning(f"update_track: трек не найден user={user_id} id={track_id}")
    return updated


def delete_track(output_base: str, user_id: int, track_id: str) -> bool:
    """Удаляет трек из базы и файловой системы."""
    tracks_dir = get_user_tracks_dir(output_base, user_id)
    index = _load_index(tracks_dir)
    new_index = []
    deleted = False
    for r in index:
        if r["id"] == track_id:
            try:
                os.remove(r["path"])
            except OSError:
                pass
            deleted = True
        else:
            new_index.append(r)
    if deleted:
        _save_index(tracks_dir, new_index)
    return deleted
