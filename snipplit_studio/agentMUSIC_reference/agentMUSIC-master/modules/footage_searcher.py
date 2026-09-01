"""
Module 2: Footage Searcher
Ищет видеофутажи на Pixabay и Pexels по списку запросов.
"""

import os
import logging
import asyncio
import random
from dataclasses import dataclass
from typing import Optional

import aiohttp
import aiofiles

logger = logging.getLogger(__name__)

PIXABAY_API_URL = "https://pixabay.com/api/videos/"
PEXELS_API_URL = "https://api.pexels.com/videos/search"

# Таймаут на скачивание одного файла (секунды)
DOWNLOAD_TIMEOUT = 60


@dataclass
class FootageResult:
    query: str
    source: str          # "pixabay" | "pexels"
    video_url: str
    duration: int        # секунды
    width: int
    height: int
    local_path: str = ""
    video_id: str = ""   # уникальный ID видео (для уникальных имён файлов)


async def _search_pixabay(
    session: aiohttp.ClientSession,
    api_key: str,
    query: str,
    orientation: str,
    min_duration: int,
    per_page: int,
    page_spread: int = 5,
) -> list[FootageResult]:
    # Запрашиваем много результатов и берём случайную страницу
    fetch_count = max(30, per_page * 5)
    rand_page = random.randint(1, max(1, page_spread))
    params = {
        "key": api_key,
        "q": query,
        "video_type": "film",
        "per_page": fetch_count,
        "page": rand_page,
        "safesearch": "true",
    }
    if orientation == "portrait":
        params["min_height"] = 1280
    else:
        params["min_width"] = 1280

    results = []
    try:
        async with session.get(PIXABAY_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Pixabay error {resp.status} for '{query}'")
                return results
            data = await resp.json()

        candidates = []
        for hit in data.get("hits", []):
            videos = hit.get("videos", {})
            video_info = videos.get("large") or videos.get("medium") or {}
            url = video_info.get("url")
            w = video_info.get("width", 0)
            h = video_info.get("height", 0)
            dur = hit.get("duration", 0)

            if not url or dur < min_duration:
                continue

            candidates.append(FootageResult(
                query=query,
                source="pixabay",
                video_url=url,
                duration=dur,
                width=w,
                height=h,
                video_id=str(hit.get("id", "")),
            ))

        # Перемешиваем и берём нужное количество
        random.shuffle(candidates)
        results = candidates[:per_page]
    except Exception as e:
        logger.error(f"Pixabay request failed for '{query}': {e}")

    return results


async def _search_pexels(
    session: aiohttp.ClientSession,
    api_key: str,
    query: str,
    orientation: str,
    min_duration: int,
    per_page: int,
    page_spread: int = 5,
) -> list[FootageResult]:
    headers = {"Authorization": api_key}
    fetch_count = max(30, per_page * 5)
    rand_page = random.randint(1, max(1, page_spread))
    params = {
        "query": query,
        "per_page": fetch_count,
        "page": rand_page,
        "orientation": orientation,
        "size": "large",
    }

    results = []
    try:
        async with session.get(PEXELS_API_URL, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Pexels error {resp.status} for '{query}'")
                return results
            data = await resp.json()

        candidates = []
        for video in data.get("videos", []):
            dur = video.get("duration", 0)
            if dur < min_duration:
                continue

            files = sorted(
                video.get("video_files", []),
                key=lambda f: f.get("width", 0) * f.get("height", 0),
                reverse=True,
            )
            best = next(
                (f for f in files if f.get("file_type") == "video/mp4"),
                None,
            )
            if not best:
                continue

            candidates.append(FootageResult(
                query=query,
                source="pexels",
                video_url=best["link"],
                duration=dur,
                width=best.get("width", 0),
                height=best.get("height", 0),
                video_id=str(video.get("id", "")),
            ))

        # Перемешиваем и берём нужное количество
        random.shuffle(candidates)
        results = candidates[:per_page]
    except Exception as e:
        logger.error(f"Pexels request failed for '{query}': {e}")

    return results


def _cache_key(query: str, orientation: str) -> str:
    """Нормализованный ключ кеша для запроса + ориентации."""
    return query.lower().strip().replace(" ", "_")[:40] + f"_{orientation}"


async def _download_video(
    session: aiohttp.ClientSession,
    result: FootageResult,
    output_dir: str,
    cache_dir: Optional[str] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> FootageResult:
    safe_query = result.query.replace(" ", "_")[:40]
    vid_id = result.video_id or "unknown"
    filename = f"{result.source}_{safe_query}_{vid_id}_{result.width}x{result.height}.mp4"

    # Если есть глобальный кеш — используем его как основное хранилище
    if cache_dir:
        cache_path = os.path.join(cache_dir, filename)
        if os.path.exists(cache_path):
            result.local_path = cache_path
            logger.debug(f"Кеш-хит: {filename}")
            return result

    local_path = os.path.join(cache_dir or output_dir, filename)

    if os.path.exists(local_path):
        result.local_path = local_path
        return result

    try:
        # total=None: очередь за слотами коннектора не должна съедать лимит;
        # sock_read ловит именно зависшие закачки, sock_connect — мёртвые CDN.
        dl_timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=timeout)
        async with session.get(result.video_url, timeout=dl_timeout) as resp:
            resp.raise_for_status()
            async with aiofiles.open(local_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 256):
                    await f.write(chunk)
        result.local_path = local_path
        logger.info(f"Скачан футаж: {filename}")
    except asyncio.TimeoutError:
        logger.warning(f"Таймаут скачивания {result.video_url} (>{timeout}с)")
        _remove_partial(local_path)
    except Exception as e:
        logger.error(f"Ошибка скачивания {result.video_url}: {e}")
        _remove_partial(local_path)

    return result


def _remove_partial(path: str) -> None:
    """Удаляет недокачанный файл, чтобы битый клип не попал в кеш."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def search_and_download(
    queries: list[str],
    pixabay_key: str,
    pexels_key: str,
    output_dir: str,
    orientation: str = "portrait",
    min_duration: int = 15,
    results_per_query: int = 2,
    cache_dir: Optional[str] = None,
    page_spread: int = 5,
    download_timeout: int = DOWNLOAD_TIMEOUT,
) -> dict[str, list[FootageResult]]:
    """
    Ищет и скачивает футажи на каждый запрос из queries.
    Если cache_dir задан — используется как глобальный кеш (файлы не дублируются per-session).
    Возвращает dict: query -> список FootageResult с заполненным local_path.
    """
    os.makedirs(output_dir, exist_ok=True)

    connector = aiohttp.TCPConnector(limit=10)
    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Параллельный поиск по всем запросам
        search_tasks = []
        for query in queries:
            search_tasks.append(
                _search_pixabay(session, pixabay_key, query, orientation, min_duration, results_per_query, page_spread)
            )
            search_tasks.append(
                _search_pexels(session, pexels_key, query, orientation, min_duration, results_per_query, page_spread)
            )

        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Группируем по запросу
        all_results: dict[str, list[FootageResult]] = {q: [] for q in queries}
        for i, query in enumerate(queries):
            pixabay_res = search_results[i * 2]
            pexels_res = search_results[i * 2 + 1]
            if isinstance(pixabay_res, Exception):
                logger.error(f"Pixabay search error for '{query}': {pixabay_res}")
                pixabay_res = []
            if isinstance(pexels_res, Exception):
                logger.error(f"Pexels search error for '{query}': {pexels_res}")
                pexels_res = []
            combined = pixabay_res[:results_per_query] + pexels_res[:results_per_query]
            all_results[query] = combined

        # Параллельное скачивание (в кеш если задан, иначе в session dir)
        download_tasks = []
        for query, results in all_results.items():
            if cache_dir:
                ck = _cache_key(query, orientation)
                dl_dir = os.path.join(cache_dir, ck)
            else:
                dl_dir = os.path.join(output_dir, query.replace(" ", "_")[:30])
            os.makedirs(dl_dir, exist_ok=True)
            for r in results:
                download_tasks.append(
                    _download_video(session, r, dl_dir, cache_dir=None, timeout=download_timeout)
                )

        await asyncio.gather(*download_tasks, return_exceptions=True)

    # Оставляем только успешно скачанные
    final: dict[str, list[FootageResult]] = {}
    for query, results in all_results.items():
        downloaded = [r for r in results if r.local_path and os.path.exists(r.local_path)]
        if downloaded:
            final[query] = downloaded

    total = sum(len(v) for v in final.values())
    logger.info(f"Скачано футажей: {total} по {len(final)} запросам")
    return final
