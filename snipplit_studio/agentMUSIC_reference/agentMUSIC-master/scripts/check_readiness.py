"""Readiness check for the AF platform integration.

Verifies env keys, external API reachability (Pixabay/Pexels), MinIO bucket
access, and local compute (ffmpeg/ffprobe, optional whisper model load).

Usage:
    python scripts/check_readiness.py            # fast checks
    python scripts/check_readiness.py --whisper  # + load faster-whisper large-v3 (slow, downloads model)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.config import settings  # noqa: E402

OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"

_failures = 0


def report(level: str, name: str, detail: str = "") -> None:
    global _failures
    if level == FAIL:
        _failures += 1
    print(f"{level} {name}" + (f" — {detail}" if detail else ""))


def check_env() -> None:
    required = {
        "AGENTMUSIC_API_KEYS": bool(settings.api_keys),
        "MINIO_URL/ACCESS/SECRET": settings.minio_configured,
    }
    recommended = {
        "PIXABAY_API_KEY": bool(settings.pixabay_api_key),
        "PEXELS_API_KEY": bool(settings.pexels_api_key),
        "DEEZER_ARL": bool(settings.deezer_arl),
        "SPOTIFY_CLIENT_ID/SECRET": bool(settings.spotify_client_id and settings.spotify_client_secret),
        "ANTHROPIC_API_KEY": bool(settings.anthropic_api_key),
    }
    for name, present in required.items():
        if present:
            report(OK, name)
        elif settings.environment == "local":
            report(WARN, name, "не задан (допустимо только для local)")
        else:
            report(FAIL, name, f"не задан при APP_ENV={settings.environment}")
    for name, present in recommended.items():
        report(OK if present else WARN, name, "" if present else "не задан")


def _http_status(url: str, timeout: int = 15) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "agentmusic-readiness"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def check_footage_apis() -> None:
    if settings.pixabay_api_key:
        url = (
            "https://pixabay.com/api/videos/?key="
            + urllib.parse.quote(settings.pixabay_api_key)
            + "&q=sunset&per_page=3"
        )
        try:
            report(OK if _http_status(url) == 200 else FAIL, "Pixabay API")
        except Exception as e:
            report(FAIL, "Pixabay API", str(e))
    else:
        report(WARN, "Pixabay API", "ключ не задан, проверка пропущена")

    if settings.pexels_api_key:
        try:
            req = urllib.request.Request(
                "https://api.pexels.com/videos/search?query=sunset&per_page=1",
                headers={"Authorization": settings.pexels_api_key},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                report(OK if resp.status == 200 else FAIL, "Pexels API")
        except Exception as e:
            report(FAIL, "Pexels API", str(e))
    else:
        report(WARN, "Pexels API", "ключ не задан, проверка пропущена")


def check_minio() -> None:
    if not settings.minio_configured:
        report(WARN, "MinIO", "не сконфигурирован, проверка пропущена")
        return
    try:
        from modules.minio_client import build_minio_client

        client = build_minio_client()
        for bucket in (settings.minio_bucket, settings.minio_tracks_bucket):
            exists = client.bucket_exists(bucket)
            report(OK if exists else WARN, f"MinIO bucket {bucket}", "" if exists else "не существует")
    except Exception as e:
        report(FAIL, "MinIO", str(e))


def check_downloaders() -> None:
    """Загрузчики для генерации по названию/ссылке (track_resolver: Deezer -> yt-dlp)."""
    from modules.spotify_loader import _streamrip_executable

    yt = shutil.which("yt-dlp")
    rip = _streamrip_executable()
    arl = bool(settings.deezer_arl)

    report(
        OK if yt else WARN,
        "yt-dlp",
        "" if yt else "не найден — фолбэк YouTube/SoundCloud недоступен",
    )
    if rip and arl:
        report(OK, "streamrip (`rip`) + DEEZER_ARL", "нога Deezer готова")
    elif rip:
        report(WARN, "streamrip (`rip`)", "есть, но DEEZER_ARL пуст — нога Deezer не качает")
    else:
        report(WARN, "streamrip (`rip`)", "не найден — нога Deezer недоступна")

    if not yt and not (rip and arl):
        report(
            FAIL,
            "Загрузка по названию/ссылке",
            "нет ни yt-dlp, ни Deezer(ARL) — доступен только источник minio_key",
        )


def check_compute(with_whisper: bool) -> None:
    for tool in ("ffmpeg", "ffprobe"):
        report(OK if shutil.which(tool) else FAIL, tool, "" if shutil.which(tool) else "не найден в PATH")

    if not with_whisper:
        report(WARN, "whisper large-v3", "пропущено (запустите с --whisper для полной проверки)")
        return
    try:
        start = time.time()
        from faster_whisper import WhisperModel

        try:
            WhisperModel("large-v3", device="cuda", compute_type="float16")
            device = "cuda"
        except Exception:
            WhisperModel("large-v3", device="cpu", compute_type="int8")
            device = "cpu"
        elapsed = time.time() - start
        detail = f"загружена за {elapsed:.0f}с, device={device}"
        if device == "cpu":
            detail += " (CPU: холодная генерация займёт минуты — см. бюджет латентности в доке)"
        report(OK, "whisper large-v3", detail)
    except Exception as e:
        report(FAIL, "whisper large-v3", str(e))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whisper", action="store_true", help="load faster-whisper large-v3 (slow)")
    args = parser.parse_args()

    print(f"agentMUSIC readiness (APP_ENV={settings.environment})\n")
    check_env()
    print()
    check_footage_apis()
    print()
    check_minio()
    print()
    check_downloaders()
    print()
    check_compute(args.whisper)

    print()
    summary = {"failures": _failures, "ready": _failures == 0}
    print(json.dumps(summary))
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
