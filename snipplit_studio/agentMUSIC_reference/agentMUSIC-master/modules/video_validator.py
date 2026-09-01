"""
Валидация видео перед отправкой пользователю.

Проверки:
- файл существует и не пустой
- ffprobe видит видео + аудио потоки
- длительность совпадает с ожидаемой (если задана)
- средняя яркость кадров (не чёрный экран)
- разнообразие кадров (не зависший кадр)
"""

import json
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def _ffprobe_streams(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_streams", "-show_format",
        "-of", "json", path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return json.loads(r.stdout)


def _sample_yavg(path: str, fps_sample: int = 1) -> list[float]:
    """Возвращает список средних яркостей по семплированным кадрам (1 кадр/сек)."""
    # -v info нужен чтобы metadata=print попадал в stderr
    cmd = [
        "ffmpeg", "-v", "info", "-i", path,
        "-vf", f"fps={fps_sample},signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    yavgs = []
    for ln in r.stderr.split("\n"):
        if "YAVG" in ln:
            try:
                yavgs.append(float(ln.split("=")[-1].strip()))
            except (ValueError, IndexError):
                pass
    return yavgs


def validate_video(
    path: str,
    expected_duration: Optional[float] = None,
    min_size_bytes: int = 50_000,
    min_yavg: float = 8.0,
    min_yavg_std: float = 0.3,
) -> tuple[bool, str]:
    """
    Проверяет видео и возвращает (ok, причина).

    Args:
        path: путь к mp4
        expected_duration: ожидаемая длительность в секундах (±1.5с допуск)
        min_size_bytes: минимальный размер файла
        min_yavg: минимальная средняя яркость (0-255), ниже — чёрный экран
        min_yavg_std: минимальное std яркости между кадрами, ниже — зависший кадр
    """
    if not os.path.exists(path):
        return False, "файл не существует"

    size = os.path.getsize(path)
    if size < min_size_bytes:
        return False, f"файл слишком маленький ({size} байт)"

    try:
        info = _ffprobe_streams(path)
    except Exception as e:
        return False, f"ffprobe failed: {e}"

    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        return False, "нет видеопотока"
    if not audio_streams:
        return False, "нет аудиопотока"

    # Длительность из format (надёжнее чем из stream)
    fmt = info.get("format", {})
    try:
        duration = float(fmt.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0

    if duration < 1.0:
        return False, f"длительность {duration:.2f}с"

    if expected_duration is not None and abs(duration - expected_duration) > 1.5:
        return False, (
            f"длительность {duration:.1f}с не совпадает с ожидаемой "
            f"{expected_duration:.1f}с"
        )

    # Разрешение sanity check
    vs = video_streams[0]
    width = int(vs.get("width", 0))
    height = int(vs.get("height", 0))
    if width < 100 or height < 100:
        return False, f"разрешение {width}x{height}"

    # Анализ яркости
    yavgs = _sample_yavg(path, fps_sample=1)
    if not yavgs:
        # ffmpeg не вернул данных — не критично, считаем валидным если остальное ok
        logger.warning(f"validate_video: signalstats пусто для {path}")
        return True, f"OK ({duration:.1f}с, {width}x{height}, без анализа яркости)"

    avg_y = sum(yavgs) / len(yavgs)
    if avg_y < min_yavg:
        return False, f"чёрный экран (yavg={avg_y:.1f})"

    # Std для детекции зависшего кадра
    if len(yavgs) >= 3:
        mean = avg_y
        var = sum((y - mean) ** 2 for y in yavgs) / len(yavgs)
        std = var ** 0.5
        if std < min_yavg_std:
            return False, f"зависший кадр (std яркости={std:.2f})"

    return True, (
        f"OK ({duration:.1f}с, {width}x{height}, "
        f"yavg={avg_y:.1f}, frames_sampled={len(yavgs)})"
    )
