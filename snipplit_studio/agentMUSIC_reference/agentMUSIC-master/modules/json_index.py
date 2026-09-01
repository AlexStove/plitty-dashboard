"""Small atomic JSON index helpers for file-backed repositories."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json_list(path: str | Path) -> list[dict[str, Any]]:
    index_path = Path(path)
    if not index_path.exists():
        return []
    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_json_atomic(path: str | Path, data: list[dict[str, Any]]) -> None:
    index_path = Path(path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.",
        suffix=".tmp",
        dir=str(index_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, index_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
