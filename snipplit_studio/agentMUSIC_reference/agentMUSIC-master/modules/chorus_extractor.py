"""
Module 1: Chorus Extractor
Определяет временной сегмент припева в треке с помощью librosa.
"""

import os
import logging
from dataclasses import dataclass

import numpy as np
# Совместимость librosa со scipy >= 1.13
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann
import librosa
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class ChorusSegment:
    start: float   # секунды
    end: float     # секунды
    confidence: float  # 0.0 – 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    def __str__(self) -> str:
        m_start, s_start = divmod(int(self.start), 60)
        m_end, s_end = divmod(int(self.end), 60)
        return f"{m_start}:{s_start:02d} – {m_end}:{s_end:02d}"


def detect_chorus(
    audio_path: str,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    n_segments: int = 10,
) -> ChorusSegment:
    """
    Определяет припев через структурный анализ аудио.

    Алгоритм:
    1. Вычисляем chroma + RMS энергию
    2. Строим матрицу рекуррентности по chroma-фичам
    3. Находим повторяющиеся сегменты с наибольшей энергией
    4. Возвращаем наиболее вероятный припев
    """
    logger.info(f"Загружаю аудио: {audio_path}")
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    logger.info(f"Длительность: {duration:.1f}с, SR: {sr}")

    # Hop size ~0.1с
    hop_length = 2048

    # Chroma для структурного анализа
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)

    # RMS энергия
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]

    # Матрица рекуррентности
    R = librosa.segment.recurrence_matrix(
        chroma,
        width=3,
        mode="affinity",
        sym=True,
    )

    # Временная ось
    times = librosa.frames_to_time(
        np.arange(chroma.shape[1]), sr=sr, hop_length=hop_length
    )

    # Делим трек на n_segments равных частей, оцениваем каждую
    segment_scores = []
    seg_len_frames = chroma.shape[1] // n_segments

    for i in range(n_segments):
        s = i * seg_len_frames
        e = min(s + seg_len_frames, chroma.shape[1])
        t_start = times[s]
        t_end = times[e - 1]

        seg_duration = t_end - t_start
        if seg_duration < min_duration * 0.5:
            continue

        # Средняя энергия сегмента
        energy = float(np.mean(rms[s:e]))

        # Рекуррентность: насколько этот сегмент похож на другие части трека
        recurrence = float(np.mean(R[s:e, :]))

        # Позиционный бонус: припев обычно во второй трети трека
        position = i / n_segments
        pos_score = 1.0 - abs(position - 0.55) * 2  # пик около 55% трека

        score = energy * 0.5 + recurrence * 0.3 + max(0.0, pos_score) * 0.2
        segment_scores.append((score, t_start, t_end))

    if not segment_scores:
        # Fallback: берём середину трека
        mid = duration / 2
        start = max(0.0, mid - 20)
        end = min(duration, mid + 20)
        return ChorusSegment(start=start, end=end, confidence=0.3)

    segment_scores.sort(reverse=True)
    best_score, best_start, best_end = segment_scores[0]

    # Нормализуем confidence в [0, 1]
    all_scores = [s for s, _, _ in segment_scores]
    score_range = max(all_scores) - min(all_scores) if len(all_scores) > 1 else 1.0
    confidence = min(1.0, (best_score - min(all_scores)) / (score_range + 1e-9) + 0.4)

    # Ограничиваем длину
    chorus_dur = best_end - best_start
    if chorus_dur > max_duration:
        best_end = best_start + max_duration

    logger.info(
        f"Найден припев: {best_start:.1f}с – {best_end:.1f}с "
        f"(confidence={confidence:.2f})"
    )
    return ChorusSegment(start=best_start, end=best_end, confidence=confidence)


def pick_best_segment_with_text(
    audio_path: str,
    whisper_segments: list[dict],
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    n_segments: int = 10,
    exclude_ranges: list[tuple[float, float]] | None = None,
) -> ChorusSegment:
    """
    Выбирает лучший фрагмент, комбинируя аудио-анализ и плотность текста.
    Если есть текст — приоритет фрагментам с максимальным количеством строк.
    """
    logger.info(f"Загружаю аудио для анализа: {audio_path}")
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    hop_length = 2048
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    R = librosa.segment.recurrence_matrix(chroma, width=3, mode="affinity", sym=True)
    times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop_length)

    import random
    # Скользящее окно — шаг 5 секунд, длина рандом в диапазоне min-max
    step = 5.0
    target_dur = random.uniform(min_duration, max_duration)
    # Проверяем несколько длин вокруг таргета для лучшего выбора
    window_sizes = [target_dur, target_dur - 3, target_dur + 3]
    window_sizes = [w for w in window_sizes if min_duration <= w <= max_duration]

    segment_scores = []

    for win_dur in window_sizes:
        if win_dur > duration:
            continue
        t = 0.0
        while t + win_dur <= duration:
            t_start = t
            t_end = t + win_dur

            # Фреймы
            s_frame = int(t_start / (hop_length / sr))
            e_frame = min(int(t_end / (hop_length / sr)), chroma.shape[1])
            if e_frame <= s_frame:
                t += step
                continue

            # Энергия
            energy = float(np.mean(rms[s_frame:e_frame]))

            # Рекуррентность
            recurrence = float(np.mean(R[s_frame:e_frame, :]))

            # Плотность текста: сколько строк Whisper попадает в окно
            text_count = 0
            text_chars = 0
            for seg in whisper_segments:
                seg_s = seg.get("start", 0)
                seg_e = seg.get("end", 0)
                if seg_e > t_start and seg_s < t_end:
                    text_count += 1
                    text_chars += len(seg.get("text", ""))

            # Нормализация плотности текста
            text_density = text_count / max(1, len(whisper_segments)) if whisper_segments else 0

            # Позиционный бонус (припев обычно 30-70% трека)
            position = (t_start + win_dur / 2) / duration
            pos_score = 1.0 - abs(position - 0.5) * 2.5
            pos_score = max(0.0, pos_score)

            # Комбинированный скор: текст важнее всего
            score = (
                energy * 0.2
                + recurrence * 0.2
                + text_density * 0.4
                + pos_score * 0.1
                + (min(text_chars, 200) / 200) * 0.1
            )

            # Пропускаем фрагменты, перекрывающиеся с исключёнными зонами
            if exclude_ranges:
                overlap = False
                for ex_start, ex_end in exclude_ranges:
                    # Более 50% перекрытие — пропускаем
                    overlap_start = max(t_start, ex_start)
                    overlap_end = min(t_end, ex_end)
                    if overlap_end > overlap_start:
                        overlap_dur = overlap_end - overlap_start
                        if overlap_dur > win_dur * 0.5:
                            overlap = True
                            break
                if overlap:
                    t += step
                    continue

            segment_scores.append((score, t_start, t_end, text_count))
            t += step

    if not segment_scores:
        mid = duration / 2
        return ChorusSegment(start=max(0.0, mid - 15), end=min(duration, mid + 15), confidence=0.3)

    segment_scores.sort(reverse=True)
    best_score, best_start, best_end, best_text = segment_scores[0]

    logger.info(
        f"Лучший фрагмент: {best_start:.1f}с – {best_end:.1f}с "
        f"(score={best_score:.3f}, строк текста={best_text})"
    )

    confidence = min(1.0, best_score * 2 + 0.3)
    return ChorusSegment(start=best_start, end=best_end, confidence=confidence)


def extract_chorus_audio(
    audio_path: str,
    segment: ChorusSegment,
    output_path: str,
) -> str:
    """Вырезает аудио сегмент и сохраняет в output_path."""
    y, sr = librosa.load(
        audio_path,
        sr=None,
        offset=segment.start,
        duration=segment.duration,
        mono=False,
    )
    # Если моно — добавляем ось
    if y.ndim == 1:
        y = y[np.newaxis, :]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    sf.write(output_path, y.T, sr, format="mp3", subtype="MPEG_LAYER_III")
    logger.info(f"Припев сохранён: {output_path}")
    return output_path
