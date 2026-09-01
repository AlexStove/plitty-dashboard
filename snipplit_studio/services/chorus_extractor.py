"""
Модуль для автоматического поиска наиболе яркого/вирусного припева в музыкальном треке.
Использует спектральный анализ librosa (chroma + RMS энергия).
"""

import os
import logging
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)

@dataclass
class ChorusSegment:
    start: float   # Секунды
    end: float     # Секунды
    confidence: float # 0.0 - 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start

def detect_chorus(
    audio_path: str,
    target_duration: float = 15.0,
    n_segments: int = 12
) -> ChorusSegment:
    """
    Автоматически находит припев в треке через анализатор librosa.
    Возвращает (start, end, confidence).
    """
    try:
        import numpy as np
        import scipy.signal
        if not hasattr(scipy.signal, "hann"):
            scipy.signal.hann = scipy.signal.windows.hann
        import librosa

        logger.info(f"[Auto-Chorus] Загрузка файла для анализа: {audio_path}")
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        total_duration = librosa.get_duration(y=y, sr=sr)

        # Если трек очень короткий (меньше 25с), берем середину
        if total_duration <= target_duration + 5:
            start_t = max(0.0, (total_duration - target_duration) / 2)
            return ChorusSegment(start=start_t, end=min(total_duration, start_t + target_duration), confidence=1.0)

        hop_length = 2048
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]

        # Рекуррентная матрица повторов гармоний
        R = librosa.segment.recurrence_matrix(chroma, width=3, mode="affinity", sym=True)
        times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop_length)

        best_score = -1.0
        best_start = 0.0

        seg_len_frames = chroma.shape[1] // n_segments

        for i in range(n_segments):
            s = i * seg_len_frames
            e = min(s + seg_len_frames, chroma.shape[1])
            if e <= s:
                continue

            t_start = times[s]
            t_end = times[e - 1]

            # Игнорируем вступление (первые 5% трека) и концовку (последние 10%)
            rel_pos = t_start / total_duration
            if rel_pos < 0.05 or rel_pos > 0.85:
                continue

            energy = float(np.mean(rms[s:e]))
            recurrence = float(np.mean(R[s:e, :]))

            # Бонус за кульминационную зону трека (между 25% и 75%)
            pos_bonus = 1.0 - abs(rel_pos - 0.45)

            score = (energy * 0.45) + (recurrence * 0.35) + (pos_bonus * 0.20)

            if score > best_score:
                best_score = score
                best_start = t_start

        # Корректируем конечный отрезок ровно под target_duration (15 сек)
        start = round(best_start, 1)
        end = round(min(total_duration, start + target_duration), 1)

        logger.info(f"[Auto-Chorus] Припев найден: {start}s - {end}s (оценка: {best_score:.2f})")
        return ChorusSegment(start=start, end=end, confidence=min(1.0, float(best_score)))

    except Exception as err:
        logger.error(f"[Auto-Chorus] Ошибка определения припева: {err}")
        return ChorusSegment(start=15.0, end=30.0, confidence=0.5)

def detect_multiple_choruses(audio_path: str, target_duration: float = 15.0, top_n: int = 3):
    """
    Находит несколько (до 3-х) наиболее вирусных и энергичных отрезков в треке.
    Возвращает список кортежей (label, ChorusSegment).
    """
    try:
        import numpy as np
        import scipy.signal
        if not hasattr(scipy.signal, "hann"):
            scipy.signal.hann = scipy.signal.windows.hann
        import librosa

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        total_duration = librosa.get_duration(y=y, sr=sr)

        if total_duration <= target_duration + 5:
            return [("🔥 Припев", ChorusSegment(start=0.0, end=min(total_duration, target_duration), confidence=1.0))]

        hop_length = 2048
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        R = librosa.segment.recurrence_matrix(chroma, width=3, mode="affinity", sym=True)
        times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop_length)

        candidates = []
        n_segments = 16
        seg_len_frames = chroma.shape[1] // n_segments

        for i in range(n_segments):
            s = i * seg_len_frames
            e = min(s + seg_len_frames, chroma.shape[1])
            if e <= s:
                continue

            t_start = times[s]
            rel_pos = t_start / total_duration
            if rel_pos < 0.05 or rel_pos > 0.9:
                continue

            energy = float(np.mean(rms[s:e]))
            recurrence = float(np.mean(R[s:e, :]))
            pos_bonus = 1.0 - abs(rel_pos - 0.45)
            score = (energy * 0.45) + (recurrence * 0.35) + (pos_bonus * 0.20)

            candidates.append((score, t_start))

        candidates.sort(key=lambda x: x[0], reverse=True)

        selected = []
        labels = ["🔥 Главный припев", "⚡️ Кульминация / Дроп", "🎤 Энергичный куплет"]
        
        for score, t_start in candidates:
            start = round(t_start, 1)
            end = round(min(total_duration, start + target_duration), 1)

            # Проверяем на перекрытие с уже выбранными отрезками
            overlap = False
            for _, seg in selected:
                if abs(seg.start - start) < target_duration * 0.6:
                    overlap = True
                    break

            if not overlap:
                label = labels[len(selected)] if len(selected) < len(labels) else f"🎵 Отрезок #{len(selected)+1}"
                selected.append((label, ChorusSegment(start=start, end=end, confidence=min(1.0, float(score)))))
                if len(selected) >= top_n:
                    break

        if not selected:
            selected = [("🔥 Главный припев", ChorusSegment(start=15.0, end=30.0, confidence=0.5))]

        return selected
    except Exception as e:
        logger.error(f"[Multi-Chorus] Ошибка: {e}")
        return [("🔥 Припев", ChorusSegment(start=15.0, end=30.0, confidence=0.5))]

