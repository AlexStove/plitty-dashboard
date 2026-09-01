"""
База припевов пользователя — JSON-индекс + mp3 файлы.

Хранит: выбранные пользователем варианты припева (после двойного выбора).
Структура:
  output/<user_id>/_choruses/
    ├── index.json
    ├── <chorus_id>.mp3
    └── ...
"""

import logging
import os
import shutil
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Optional

from modules.json_index import load_json_list, save_json_atomic

logger = logging.getLogger(__name__)


def get_user_choruses_dir(output_base: str, user_id: int) -> str:
    d = os.path.join(output_base, str(user_id), "_choruses")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(choruses_dir: str) -> str:
    return os.path.join(choruses_dir, "index.json")


def _load_index(choruses_dir: str) -> list[dict]:
    p = _index_path(choruses_dir)
    try:
        return load_json_list(p)
    except Exception as e:
        logger.warning(f"Не удалось прочитать {p}: {e}")
        return []


def _save_index(choruses_dir: str, index: list[dict]) -> None:
    save_json_atomic(_index_path(choruses_dir), index)


def _serialize_lyrics(lyrics_lines: list) -> list[dict]:
    """Сериализует LyricsLine/WordTiming в JSON-friendly dict."""
    out = []
    for ll in lyrics_lines or []:
        if is_dataclass(ll):
            d = asdict(ll)
        elif isinstance(ll, dict):
            d = ll
        else:
            continue
        out.append(d)
    return out


def save_chorus(
    output_base: str,
    user_id: int,
    src_chorus_path: str,
    track_id: str,
    name: str,
    lyrics_lines: list,
    variant: str,
    start: float = 0.0,
    end: float = 0.0,
    is_preview: bool = False,
) -> dict:
    """
    Копирует припев в базу пользователя.
    variant: "audio" (chorus_extractor) или "text" (claude trigger).
    is_preview: True, если припев извлечён из 30-сек превью (не полного трека).
    """
    choruses_dir = get_user_choruses_dir(output_base, user_id)
    chorus_id = uuid.uuid4().hex[:12]
    dst = os.path.join(choruses_dir, f"{chorus_id}.mp3")
    shutil.copy2(src_chorus_path, dst)

    record = {
        "id": chorus_id,
        "track_id": track_id,
        "path": dst,
        "name": name,
        "variant": variant,
        "start": float(start),
        "end": float(end),
        "lyrics": _serialize_lyrics(lyrics_lines),
        "is_preview": bool(is_preview),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }

    index = _load_index(choruses_dir)
    index.append(record)
    _save_index(choruses_dir, index)
    logger.info(f"Chorus saved: user={user_id} id={chorus_id} variant={variant} name='{name}'")
    return record


def list_user_choruses(output_base: str, user_id: int) -> list[dict]:
    """Возвращает все припевы пользователя (по убыванию даты)."""
    choruses_dir = get_user_choruses_dir(output_base, user_id)
    index = _load_index(choruses_dir)
    valid = [r for r in index if os.path.exists(r.get("path", ""))]
    if len(valid) != len(index):
        _save_index(choruses_dir, valid)
    valid.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    return valid


def get_chorus(output_base: str, user_id: int, chorus_id: str) -> Optional[dict]:
    for r in list_user_choruses(output_base, user_id):
        if r["id"] == chorus_id:
            return r
    return None


def delete_chorus(output_base: str, user_id: int, chorus_id: str) -> bool:
    choruses_dir = get_user_choruses_dir(output_base, user_id)
    index = _load_index(choruses_dir)
    new_index = []
    deleted = False
    for r in index:
        if r["id"] == chorus_id:
            try:
                os.remove(r["path"])
            except OSError:
                pass
            deleted = True
        else:
            new_index.append(r)
    if deleted:
        _save_index(choruses_dir, new_index)
    return deleted


def cleanup_old(output_base: str, user_id: int, max_choruses: int = 50) -> int:
    """Удаляет старые припевы если их больше max. Возвращает кол-во удалённых."""
    items = list_user_choruses(output_base, user_id)
    if len(items) <= max_choruses:
        return 0
    to_delete = items[max_choruses:]
    count = 0
    for r in to_delete:
        if delete_chorus(output_base, user_id, r["id"]):
            count += 1
    return count
