"""
BPM-анализ аудио через librosa.

Определяет темп трека (BPM) и временные метки ударов.
Используется для синхронизации анимаций (Wave-пресет).
"""

import logging
from dataclasses import dataclass

import librosa
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BPMInfo:
    bpm: float              # удары в минуту
    beat_times: np.ndarray  # массив секунд, когда происходит удар


def analyze_bpm(audio_path: str, sr: int = 22050) -> BPMInfo:
    """
    Анализирует BPM трека и возвращает темп + массив времён ударов.

    Args:
        audio_path: путь к аудиофайлу (MP3, WAV, etc.)
        sr: sample rate (22050 — как в chorus_extractor)

    Returns:
        BPMInfo с bpm и beat_times
    """
    y, sr = librosa.load(audio_path, sr=sr, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    # librosa 0.10.x может вернуть scalar или array
    bpm = float(np.atleast_1d(tempo)[0])
    logger.info(f"BPM: {bpm:.1f}, ударов: {len(beat_times)}")
    return BPMInfo(bpm=bpm, beat_times=beat_times)
