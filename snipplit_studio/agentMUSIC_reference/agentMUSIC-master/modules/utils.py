"""
Общие утилиты для проекта agentMUSIC.
"""

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

RESOLUTIONS = {
    "portrait": (1080, 1920),
    "landscape": (1920, 1080),
}


def get_media_duration(path: str) -> float:
    """
    Возвращает длительность медиафайла в секундах через ffprobe.
    Raises RuntimeError при ошибке.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe вернул код {result.returncode} для {path}: {result.stderr.strip()}"
            )
        raw = result.stdout.strip()
        if not raw:
            raise RuntimeError(f"ffprobe вернул пустой вывод для {path}")
        return float(raw)
    except ValueError:
        raise RuntimeError(f"ffprobe вернул невалидные данные для {path}: '{raw}'")
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe не найден. Установите ffmpeg:\n"
            "  Linux:   sudo apt install ffmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Windows: https://ffmpeg.org/download.html"
        )


def extract_thumbnail(video_path: str, output_path: str, seek: float = 2.0) -> bool:
    """Извлекает кадр из видео в JPEG. Возвращает True при успехе."""
    cmd = [
        "ffmpeg", "-y", "-ss", str(seek),
        "-i", video_path,
        "-vframes", "1",
        "-vf", "scale=320:-1",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"Ошибка извлечения превью из {video_path}: {e}")
        return False


def check_ffmpeg() -> bool:
    """
    Проверяет наличие ffmpeg и ffprobe в системе.
    Возвращает True если всё ОК, иначе выводит сообщение и возвращает False.
    """
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            logger.error(
                f"{tool} не найден в PATH. Установите ffmpeg:\n"
                f"  Linux:   sudo apt install ffmpeg\n"
                f"  macOS:   brew install ffmpeg\n"
                f"  Windows: скачайте с https://ffmpeg.org/download.html и добавьте в PATH"
            )
            return False
    return True
