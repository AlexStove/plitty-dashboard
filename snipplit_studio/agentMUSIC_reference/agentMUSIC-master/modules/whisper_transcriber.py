"""
Транскрипция аудио через faster-whisper (large-v3) с пословными таймингами.

Стратегия (без внешних зависимостей) — несколько проходов с эскалацией
параметров, чтобы как можно меньше треков оставалось без текста:
  1. VAD включён, музыкально-мягкие параметры.
  2. VAD выключен (на громком бите VAD режет вокал как тишину).
  3. VAD выключен + condition_on_previous_text=False (разрывает циклы
     галлюцинаций) + повышенный no_speech_threshold.
Из проходов берётся результат с наибольшим количеством «живых» слов.
"""

import logging
from typing import Optional

from .types import LyricsLine, WordTiming

logger = logging.getLogger(__name__)

# Кэш моделей по устройству, чтобы не грузить large-v3 повторно.
_models: dict[str, object] = {}

# Проходы транскрипции: (use_vad, condition_on_previous_text, no_speech_threshold)
_PASSES = [
    {"use_vad": True, "condition": True, "no_speech": 0.6},
    {"use_vad": False, "condition": True, "no_speech": 0.6},
    {"use_vad": False, "condition": False, "no_speech": 0.85},
]


def _get_model(prefer_gpu: bool = True):
    """
    Загружает (с кэшем) faster-whisper large-v3. Пытается GPU, падает на CPU.
    Возвращает модель либо бросает ImportError, если пакет не установлен.
    """
    from faster_whisper import WhisperModel

    if prefer_gpu:
        if "gpu" in _models:
            return _models["gpu"]
        try:
            _models["gpu"] = WhisperModel("large-v3", device="cuda", compute_type="float16")
            logger.info("faster-whisper: large-v3 (GPU, float16)")
            return _models["gpu"]
        except Exception as e:
            logger.info(f"faster-whisper: GPU недоступен ({e}); использую CPU")

    if "cpu" not in _models:
        _models["cpu"] = WhisperModel("large-v3", device="cpu", compute_type="int8")
        logger.info("faster-whisper: large-v3 (CPU, int8)")
    return _models["cpu"]


def transcribe_with_timings(
    audio_path: str,
    language: Optional[str] = None,
    use_vad: bool = True,
) -> list[dict]:
    """
    Транскрибирует аудио через faster-whisper large-v3 с эскалацией проходов.
    Возвращает сегменты с пословными таймингами (может быть пустым списком,
    если в треке реально нет распознаваемого вокала).

    use_vad=False — начать сразу без VAD (для треков, где вокал тонет в музыке).
    """
    try:
        model = _get_model()
    except ImportError:
        logger.error("faster-whisper не установлен. pip install faster-whisper")
        return []
    except Exception as e:
        logger.error(f"Не удалось загрузить модель faster-whisper: {e}")
        return []

    # Если запросили без VAD — пропускаем первый (VAD-) проход.
    passes = _PASSES if use_vad else [p for p in _PASSES if not p["use_vad"]]

    best: list[dict] = []
    for p in passes:
        try:
            segments = _do_transcribe(
                model,
                audio_path,
                language,
                use_vad=p["use_vad"],
                condition=p["condition"],
                no_speech=p["no_speech"],
            )
        except Exception as e:
            logger.warning(f"faster-whisper проход (vad={p['use_vad']}) упал: {e}")
            segments = []

        segments = _drop_hallucinations(segments)
        if _word_count(segments) > _word_count(best):
            best = segments

        # Достаточно текста — дальше можно не эскалировать.
        if _word_count(best) >= 25:
            break

    logger.info(
        f"faster-whisper итог: {len(best)} сегментов, {_word_count(best)} слов"
    )
    return best


def _do_transcribe(
    model,
    audio_path: str,
    language: Optional[str] = None,
    use_vad: bool = True,
    condition: bool = True,
    no_speech: float = 0.6,
) -> list[dict]:
    """Запускает один проход транскрипции и собирает сегменты."""
    kwargs = {
        "word_timestamps": True,
        "vad_filter": use_vad,
        "beam_size": 5,
        "best_of": 3,
        "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "condition_on_previous_text": condition,
        "no_speech_threshold": no_speech,
        # Выше порог — реже выкидываем повторяющиеся строки припева как «мусор».
        "compression_ratio_threshold": 3.4,
    }
    # Для музыки делаем VAD мягче — не вырезать фрагменты с фоновой музыкой.
    if use_vad:
        kwargs["vad_parameters"] = {
            "min_silence_duration_ms": 1000,
            "speech_pad_ms": 400,
            "threshold": 0.35,
        }
    if language:
        kwargs["language"] = language

    segments_gen, info = model.transcribe(audio_path, **kwargs)
    logger.info(
        f"faster-whisper: проход vad={use_vad} cond={condition} "
        f"язык={info.language} (p={info.language_probability:.2f})"
    )

    segments = []
    for seg in segments_gen:
        seg_data = {
            "text": seg.text.strip(),
            "start": seg.start,
            "end": seg.end,
            "words": [],
            "no_speech_prob": getattr(seg, "no_speech_prob", 0.0),
            "avg_logprob": getattr(seg, "avg_logprob", 0.0),
        }
        if seg.words:
            for w in seg.words:
                seg_data["words"].append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })
        segments.append(seg_data)

    logger.info(f"faster-whisper: распознано {len(segments)} сегментов")
    return segments


def _word_count(segments: list[dict]) -> int:
    """Количество распознанных слов (для сравнения проходов)."""
    total = 0
    for s in segments:
        words = s.get("words") or []
        total += len(words) if words else len(s.get("text", "").split())
    return total


def _drop_hallucinations(segments: list[dict]) -> list[dict]:
    """
    Убирает типичные галлюцинации faster-whisper:
      - подряд идущие сегменты с одинаковым текстом (цикл повтора) — оставляем
        не более 2 повторов подряд;
      - сегменты с очень высокой вероятностью «нет речи».
    Делается мягко, чтобы не терять реальный текст припева.
    """
    out: list[dict] = []
    prev_norm = None
    repeat = 0
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        # Явный «нет речи» с низким качеством — пропускаем.
        if s.get("no_speech_prob", 0.0) > 0.85 and s.get("avg_logprob", 0.0) < -1.2:
            continue
        norm = text.lower()
        if norm == prev_norm:
            repeat += 1
            if repeat >= 2:
                continue
        else:
            repeat = 0
        prev_norm = norm
        out.append(s)
    return out


def _validate_and_fix_words(
    words: list[WordTiming], segment_text: str, seg_start: float, seg_end: float,
) -> list[WordTiming]:
    """
    Проверяет что слова корректны. Если слиплись — пересоздаёт из текста.
    """
    if not words:
        text_words = segment_text.split()
        if not text_words:
            return []
        dur = seg_end - seg_start
        step = dur / len(text_words)
        return [
            WordTiming(word=w, start=seg_start + i * step, end=seg_start + (i + 1) * step)
            for i, w in enumerate(text_words)
        ]

    text_words = segment_text.split()

    if len(text_words) > len(words) * 1.5 and len(text_words) >= 3:
        logger.info(
            f"Слова слиплись ({len(words)} vs {len(text_words)}), пересоздаю"
        )
        dur = seg_end - seg_start
        step = dur / len(text_words)
        return [
            WordTiming(word=w, start=seg_start + i * step, end=seg_start + (i + 1) * step)
            for i, w in enumerate(text_words)
        ]

    return words


def segments_to_lyrics_lines(segments: list[dict]) -> list[LyricsLine]:
    """Конвертирует сегменты в LyricsLine с пословными таймингами."""
    lines = []
    for s in segments:
        if not s.get("text"):
            continue
        raw_words = [
            WordTiming(word=w["word"], start=w["start"], end=w["end"])
            for w in s.get("words", [])
            if w.get("word")
        ]
        words = _validate_and_fix_words(raw_words, s["text"], s["start"], s["end"])
        lines.append(LyricsLine(
            text=s["text"],
            start=s["start"],
            end=s["end"],
            words=words,
        ))
    return lines
