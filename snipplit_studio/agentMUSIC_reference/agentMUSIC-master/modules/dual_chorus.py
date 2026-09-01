"""
Извлечение 2 вариантов припева из трека:
  - Variant A: chorus_extractor (аудио-анализ через librosa)
  - Variant B: claude_agent.pick_trigger_segment (анализ текста Whisper)

Если оба варианта слишком близки (overlap > 50%), возвращаем только один.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from .chorus_extractor import (
    ChorusSegment,
    detect_chorus,
    pick_best_segment_with_text,
    extract_chorus_audio,
)
from .claude_agent import pick_trigger_segment
from .types import LyricsLine

logger = logging.getLogger(__name__)


@dataclass
class ChorusVariant:
    label: str           # "Вариант 1 (аудио)" / "Вариант 2 (триггер из текста)"
    variant: str         # "audio" | "text"
    audio_path: str      # путь к вырезанному mp3
    start: float         # начало в исходном треке
    end: float           # конец в исходном треке
    lyrics: list[LyricsLine] = field(default_factory=list)
    reason: str = ""     # причина выбора (для text-варианта от Claude)


def _segments_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Возвращает долю перекрытия двух сегментов (0..1) относительно меньшего."""
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    if overlap_end <= overlap_start:
        return 0.0
    overlap = overlap_end - overlap_start
    smaller = min(a_end - a_start, b_end - b_start)
    if smaller <= 0:
        return 0.0
    return overlap / smaller


def _crop_lyrics_to_range(
    full_segments: list[dict], start: float, end: float
) -> list[LyricsLine]:
    """
    Берёт сегменты Whisper которые попадают в [start, end] и
    пересчитывает тайминги относительно start.
    """
    from .types import WordTiming
    out = []
    for seg in full_segments:
        s = seg.get("start", 0.0)
        e = seg.get("end", 0.0)
        if e <= start or s >= end:
            continue
        # Обрезаем до границ
        ns = max(s, start) - start
        ne = min(e, end) - start
        text = seg.get("text", "").strip()
        if not text:
            continue
        words = []
        for w in seg.get("words", []) or []:
            ws = w.get("start", 0.0)
            we = w.get("end", 0.0)
            if we <= start or ws >= end:
                continue
            words.append(WordTiming(
                word=w.get("word", "").strip(),
                start=max(ws, start) - start,
                end=min(we, end) - start,
            ))
        out.append(LyricsLine(text=text, start=ns, end=ne, words=words))
    return out


def extract_two_choruses(
    audio_path: str,
    full_segments: list[dict],
    output_dir: str,
    api_key: Optional[str] = None,
    min_duration: float = 15.0,
    max_duration: float = 30.0,
) -> list[ChorusVariant]:
    """
    Извлекает 2 варианта припева:
      - audio: chorus_extractor.pick_best_segment_with_text
      - text:  claude_agent.pick_trigger_segment

    Если варианты слишком близки (overlap > 50%) — возвращает только audio.
    """
    os.makedirs(output_dir, exist_ok=True)
    variants: list[ChorusVariant] = []

    # --- Variant A: аудио-анализ ---
    try:
        seg_audio = pick_best_segment_with_text(
            audio_path=audio_path,
            whisper_segments=full_segments,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        audio_out = os.path.join(output_dir, "chorus_audio.mp3")
        extract_chorus_audio(audio_path, seg_audio, audio_out)
        lyrics_a = _crop_lyrics_to_range(full_segments, seg_audio.start, seg_audio.end)
        variants.append(ChorusVariant(
            label="Вариант 1 (аудио-анализ)",
            variant="audio",
            audio_path=audio_out,
            start=seg_audio.start,
            end=seg_audio.end,
            lyrics=lyrics_a,
            reason=f"Лучший фрагмент по chroma+RMS+рекуррентности (conf={seg_audio.confidence:.2f})",
        ))
    except Exception as e:
        logger.error(f"Variant A (audio) failed: {e}")

    # --- Variant B: текст-анализ через Claude ---
    if api_key and api_key != "your_anthropic_api_key_here":
        try:
            result = pick_trigger_segment(
                segments=full_segments,
                api_key=api_key,
                min_duration=min_duration,
                max_duration=max_duration,
            )
            if result:
                t_start, t_end, reason = result
                # Проверяем, не слишком ли близок к Variant A
                skip = False
                if variants:
                    overlap = _segments_overlap(
                        variants[0].start, variants[0].end, t_start, t_end
                    )
                    if overlap > 0.5:
                        logger.info(
                            f"Variant B (text) слишком близок к A (overlap={overlap:.2f}), пропускаю"
                        )
                        skip = True

                if not skip:
                    seg_text = ChorusSegment(start=t_start, end=t_end, confidence=0.8)
                    text_out = os.path.join(output_dir, "chorus_text.mp3")
                    extract_chorus_audio(audio_path, seg_text, text_out)
                    lyrics_b = _crop_lyrics_to_range(full_segments, t_start, t_end)
                    variants.append(ChorusVariant(
                        label="Вариант 2 (триггер из текста)",
                        variant="text",
                        audio_path=text_out,
                        start=t_start,
                        end=t_end,
                        lyrics=lyrics_b,
                        reason=reason,
                    ))
        except Exception as e:
            logger.error(f"Variant B (text) failed: {e}")

    if not variants:
        # Fallback — простой detect_chorus
        seg = detect_chorus(audio_path, min_duration=min_duration, max_duration=max_duration)
        out = os.path.join(output_dir, "chorus_fallback.mp3")
        extract_chorus_audio(audio_path, seg, out)
        variants.append(ChorusVariant(
            label="Припев (fallback)",
            variant="audio",
            audio_path=out,
            start=seg.start,
            end=seg.end,
            lyrics=_crop_lyrics_to_range(full_segments, seg.start, seg.end),
            reason="Fallback detect_chorus",
        ))

    logger.info(f"extract_two_choruses: получено {len(variants)} вариантов")
    return variants
