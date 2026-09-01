"""Footage cache prewarm for the API render path.

The bot path fills ``output/_footage_cache`` via footage_searcher before
rendering; the API path historically only *read* the cache, so API-triggered
``bg_type=footage`` silently degraded to ``animated``. This module lets the
worker (and an explicit endpoint) fill the cache without bot.py.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from modules.config import settings
from modules.footage_searcher import search_and_download

logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".mov", ".webm")


def cache_dir(output_base: str) -> str:
    return os.path.join(output_base, "_footage_cache")


def list_cached_videos(output_base: str) -> list[str]:
    """All cached footage files, including per-query subdirectories."""
    root = Path(cache_dir(output_base))
    if not root.is_dir():
        return []
    return [str(p) for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS]


def footage_keys_configured() -> bool:
    return bool(settings.pixabay_api_key or settings.pexels_api_key)


async def prewarm_footage_cache(
    config: dict,
    output_base: str,
    orientation: str = "portrait",
    min_files: int = 4,
    max_queries: int = 5,
) -> list[str]:
    """Ensure the footage cache holds at least ``min_files`` clips.

    Returns the resulting list of cached clip paths (possibly empty when no
    Pixabay/Pexels keys are configured — caller falls back to animated bg).
    """
    existing = list_cached_videos(output_base)
    if len(existing) >= min_files:
        return existing

    if not footage_keys_configured():
        logger.warning(
            "Footage cache is empty and PIXABAY_API_KEY/PEXELS_API_KEY are not set; "
            "footage prewarm skipped."
        )
        return existing

    queries = list(config.get("footage", {}).get("base_queries", []))[:max_queries]
    if not queries:
        logger.warning("config footage.base_queries is empty; footage prewarm skipped")
        return existing

    target = cache_dir(output_base)
    min_duration = int(config.get("footage", {}).get("min_duration_sec", 10) or 10)
    logger.info("Prewarming footage cache: %d queries (%s)", len(queries), orientation)
    try:
        await search_and_download(
            queries=queries,
            pixabay_key=settings.pixabay_api_key,
            pexels_key=settings.pexels_api_key,
            output_dir=target,
            orientation=orientation,
            min_duration=min_duration,
            results_per_query=3,
            cache_dir=target,
        )
    except Exception as e:
        logger.error("Footage prewarm failed: %s", e)

    clips = list_cached_videos(output_base)
    logger.info("Footage cache now holds %d clip(s)", len(clips))
    return clips
