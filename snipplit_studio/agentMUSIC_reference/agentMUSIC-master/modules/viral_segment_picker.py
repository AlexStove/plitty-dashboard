"""
Viral Segment Picker — надстройка над dual_chorus.

Из готового припева (15-60с) вырезает вирусный 21-секундный hook под TikTok/Reels/Shorts:
  - стартует за 2-3с до самой "цепляющей" лирической строки (pre-hook tension)
  - заканчивается на down-beat (ровный музыкальный обрыв для loop-stitch)
  - целится в 21с (магическая длина US short-form)

ВАЖНО: модуль ничего не ломает в существующем pipeline.
Он принимает на вход данные, которые уже собирают другие модули
(dual_chorus, whisper_transcriber, bpm_analyzer), и возвращает
новую структуру ViralHookCut — опциональную, не заменяющую ChorusVariant.

Чистый Python + librosa. Опционально работает с BPM-гридом (если передан).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# --- Константы US short-form ---
# Магическое окно 21с — согласно публичным бенчмаркам TikTok/Reels.
TARGET_DURATION_DEFAULT = 21.0
MIN_DURATION_DEFAULT = 15.0
MAX_DURATION_DEFAULT = 30.0

# Отступ ДО hook-строки: "накачиваем давление" перед самой яркой фразой.
PRE_HOOK_TENSION_MIN = 1.8
PRE_HOOK_TENSION_MAX = 3.2

# Допустимое окно выбора финала вокруг down-beat'а (для cut-on-beat).
BEAT_SNAP_WINDOW = 0.25


@dataclass
class LyricLineScore:
    """Скор одной строки внутри припева."""
    text: str
    start: float            # абсолютное время в треке
    end: float              # абсолютное время в треке
    length_chars: int
    repetition: float       # 0-1, похожесть на другие строки припева
    brevity: float          # 0-1, чем короче — тем выше (оптимум 5-8 слов)
    phonetic_punch: float   # 0-1, открытые гласные + повтор согласных
    position_bonus: float   # 0-1, начало/середина припева ценнее чем конец
    total: float            # финальный взвешенный скор


@dataclass
class ViralHookCut:
    """Результат выбора 21с виального отрезка."""
    start: float            # абсолютное время в треке (секунды)
    end: float              # абсолютное время в треке (секунды)
    hook_line: Optional[LyricLineScore]
    pre_tension: float      # сколько секунд "нагнетания" перед hook-строкой
    ends_on_beat: bool      # получилось ли закончить на down-beat'е
    confidence: float       # 0-1, насколько мы уверены в выборе
    reasoning: str          # текстовое объяснение (для логов и дебага)
    candidates: list[LyricLineScore] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------------------------------------------------------------------------
#  Scoring отдельных строк
# ---------------------------------------------------------------------------

# Открытые гласные (en) — фонетически "звонкие", дают вирусность.
_OPEN_VOWELS = set("aeiou")

# Stop-words короткие, за них не считаем "содержательность".
_STOP_WORDS = {"the", "a", "an", "and", "or", "but", "is", "are",
               "to", "of", "in", "on", "at", "it", "i", "you", "me"}


def _count_syllables_rough(word: str) -> int:
    """Грубая оценка слогов по гласным. Быстрая, без nltk."""
    word = word.lower()
    prev_vowel = False
    count = 0
    for ch in word:
        is_vowel = ch in _OPEN_VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


def _brevity_score(text: str) -> float:
    """Оптимум 5-8 слов: получает 1.0. Длиннее/короче — падение."""
    words = [w for w in text.strip().split() if w]
    n = len(words)
    if n == 0:
        return 0.0
    if 5 <= n <= 8:
        return 1.0
    if n < 5:
        return n / 5.0
    return max(0.0, 1.0 - (n - 8) / 10.0)


def _phonetic_punch_score(text: str) -> float:
    """
    Смесь двух сигналов:
      - доля открытых гласных в общем символьном объёме
      - плотность повторяющихся согласных (alliteration)
    Оба помогают "зацепиться" на слух.
    """
    letters = [c.lower() for c in text if c.isalpha()]
    if not letters:
        return 0.0
    vowel_ratio = sum(1 for c in letters if c in _OPEN_VOWELS) / len(letters)
    # Alliteration: первые буквы подряд идущих слов совпадают.
    words = [w for w in text.lower().split() if w and w[0].isalpha()]
    if len(words) < 2:
        alliteration = 0.0
    else:
        pairs = sum(1 for a, b in zip(words, words[1:]) if a[0] == b[0])
        alliteration = pairs / (len(words) - 1)
    # Баланс: вокал-долю тянем к "красивым" 0.4-0.55.
    vowel_score = 1.0 - abs(vowel_ratio - 0.47) * 2.0
    vowel_score = max(0.0, min(1.0, vowel_score))
    return 0.65 * vowel_score + 0.35 * alliteration


def _repetition_score(
    target_idx: int,
    target: str,
    all_lines: list[str],
) -> float:
    """
    Насколько часто эта строка (или её ключевой n-gram) повторяется.
    Простой Jaccard по словам — быстро, без эмбеддингов.
    Сравниваем по индексу, чтобы идентичные дубли ловились как повтор.
    """
    target_words = {w.lower() for w in target.split() if w.lower() not in _STOP_WORDS}
    if not target_words:
        return 0.0
    best = 0.0
    counted = 0
    for i, other in enumerate(all_lines):
        if i == target_idx:
            continue
        other_words = {w.lower() for w in other.split() if w.lower() not in _STOP_WORDS}
        if not other_words:
            continue
        counted += 1
        inter = len(target_words & other_words)
        union = len(target_words | other_words)
        if union:
            best = max(best, inter / union)
    # Если в припеве всего 1-2 строки — не наказываем отсутствие повтора.
    if counted == 0:
        return 0.5
    return best


def _position_bonus(line_start: float, chorus_start: float, chorus_end: float) -> float:
    """
    Внутри припева: первая треть = 1.0, середина = 0.8, конец = 0.5.
    Это отражает реальность US TikTok — hook обычно в первых 40% припева.
    """
    chorus_dur = max(0.01, chorus_end - chorus_start)
    rel = (line_start - chorus_start) / chorus_dur
    if rel <= 0.4:
        return 1.0
    if rel <= 0.7:
        return 0.8
    return 0.5


def _score_line(
    index: int,
    line: dict,
    all_lines_text: list[str],
    chorus_start: float,
    chorus_end: float,
) -> LyricLineScore:
    text = (line.get("text") or "").strip()
    start = float(line.get("start", 0.0))
    end = float(line.get("end", start))
    repetition = _repetition_score(index, text, all_lines_text)
    brevity = _brevity_score(text)
    phonetic = _phonetic_punch_score(text)
    pos = _position_bonus(start, chorus_start, chorus_end)
    # Веса подобраны так, чтобы ни один сигнал не доминировал.
    total = (
        0.30 * repetition +
        0.20 * brevity +
        0.25 * phonetic +
        0.25 * pos
    )
    return LyricLineScore(
        text=text,
        start=start,
        end=end,
        length_chars=len(text),
        repetition=repetition,
        brevity=brevity,
        phonetic_punch=phonetic,
        position_bonus=pos,
        total=total,
    )


# ---------------------------------------------------------------------------
#  Beat snapping (опционально)
# ---------------------------------------------------------------------------


def _snap_to_nearest_beat(
    target_time: float,
    beat_times: Optional[list[float]],
    window: float = BEAT_SNAP_WINDOW,
) -> tuple[float, bool]:
    """Двигаем target_time к ближайшему биту, если он в пределах window."""
    if not beat_times:
        return target_time, False
    nearest = min(beat_times, key=lambda b: abs(b - target_time))
    if abs(nearest - target_time) <= window:
        return nearest, True
    return target_time, False


# ---------------------------------------------------------------------------
#  Главная функция
# ---------------------------------------------------------------------------


def pick_viral_hook(
    whisper_segments: list[dict],
    chorus_start: float,
    chorus_end: float,
    track_duration: float,
    beat_times: Optional[list[float]] = None,
    target_duration: float = TARGET_DURATION_DEFAULT,
    min_duration: float = MIN_DURATION_DEFAULT,
    max_duration: float = MAX_DURATION_DEFAULT,
) -> ViralHookCut:
    """
    Вырезает 21-секундный вирусный hook из готового припева.

    Args:
        whisper_segments: список Whisper-сегментов всего трека ({start,end,text,words}).
                          Модуль сам выберет те, что попадают в окно припева.
        chorus_start, chorus_end: границы припева в абсолютных секундах трека
                          (получены из dual_chorus.ChorusVariant).
        track_duration: полная длина трека.
        beat_times: опциональный список времён ударов (из bpm_analyzer).
                   Если передан — финал hook'а "прилипает" к down-beat.
        target_duration: целевая длина hook'а (21с — магическая для US).
        min_duration, max_duration: жёсткие границы.

    Returns:
        ViralHookCut с абсолютными таймингами.

    НИЧЕГО не изменяет во входных данных, не пишет на диск.
    Это чистая функция — её можно звать параллельно для batch-обработки.
    """
    # 1. Отбираем строки, которые попадают в окно припева.
    chorus_lines = []
    for seg in whisper_segments:
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s))
        if e <= chorus_start or s >= chorus_end:
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        chorus_lines.append({"start": s, "end": e, "text": text})

    # 2. Если строк нет — безопасный fallback: центр припева, без hook-line.
    if not chorus_lines:
        return _fallback_cut(
            chorus_start, chorus_end, track_duration,
            target_duration, min_duration, max_duration,
            beat_times, reason="no_lyrics_in_chorus",
        )

    # 3. Скорим каждую строку.
    all_texts = [l["text"] for l in chorus_lines]
    scored = [
        _score_line(i, l, all_texts, chorus_start, chorus_end)
        for i, l in enumerate(chorus_lines)
    ]
    scored.sort(key=lambda s: s.total, reverse=True)
    hook_line = scored[0]

    # 4. Строим окно: старт = hook_line.start - pre-tension.
    #    pre-tension интерполируем по длине строки: короткая строка → больше воздуха.
    pre_tension = PRE_HOOK_TENSION_MIN + (PRE_HOOK_TENSION_MAX - PRE_HOOK_TENSION_MIN) * (
        1.0 - min(1.0, hook_line.length_chars / 50.0)
    )
    raw_start = hook_line.start - pre_tension
    raw_end = raw_start + target_duration

    # 5. Клиппинг по трек-границам и припев-границам.
    #    Мы НЕ выходим за пределы припева больше чем на pre_tension
    #    (pre-tension можно взять из pre-chorus секции трека).
    hard_min_start = max(0.0, chorus_start - pre_tension)
    hard_max_end = min(track_duration, chorus_end + 2.0)

    if raw_start < hard_min_start:
        raw_start = hard_min_start
        raw_end = raw_start + target_duration
    if raw_end > hard_max_end:
        raw_end = hard_max_end
        raw_start = max(hard_min_start, raw_end - target_duration)

    # 6. Обеспечиваем границы длины.
    dur = raw_end - raw_start
    if dur < min_duration:
        deficit = min_duration - dur
        raw_end = min(hard_max_end, raw_end + deficit)
        if raw_end - raw_start < min_duration:
            raw_start = max(hard_min_start, raw_end - min_duration)
    elif dur > max_duration:
        raw_end = raw_start + max_duration

    # 7. Финал "прилипает" к down-beat, если есть grid.
    snapped_end, snapped = _snap_to_nearest_beat(raw_end, beat_times)
    if snapped and abs(snapped_end - raw_start) >= min_duration:
        raw_end = snapped_end

    # 8. Confidence: насколько убедителен hook-line + насколько попали в грид.
    confidence = 0.45 + 0.45 * hook_line.total + (0.10 if snapped else 0.0)
    confidence = max(0.0, min(1.0, confidence))

    reasoning = (
        f"hook-line '{hook_line.text[:60]}' "
        f"(rep={hook_line.repetition:.2f}, punch={hook_line.phonetic_punch:.2f}) "
        f"+ pre-tension {pre_tension:.1f}s"
        + (" + beat-snap" if snapped else "")
    )

    logger.info(
        f"pick_viral_hook: {raw_start:.2f}s-{raw_end:.2f}s "
        f"({raw_end - raw_start:.1f}s), confidence={confidence:.2f}"
    )

    return ViralHookCut(
        start=raw_start,
        end=raw_end,
        hook_line=hook_line,
        pre_tension=pre_tension,
        ends_on_beat=snapped,
        confidence=confidence,
        reasoning=reasoning,
        candidates=scored[:5],
    )


def _fallback_cut(
    chorus_start: float,
    chorus_end: float,
    track_duration: float,
    target_duration: float,
    min_duration: float,
    max_duration: float,
    beat_times: Optional[list[float]],
    reason: str,
) -> ViralHookCut:
    """Без lyrics — берём центр припева, снапим к биту."""
    chorus_dur = chorus_end - chorus_start
    dur = min(max_duration, max(min_duration, min(target_duration, chorus_dur)))
    center = (chorus_start + chorus_end) / 2.0
    start = max(0.0, center - dur / 2.0)
    end = min(track_duration, start + dur)
    snapped_end, snapped = _snap_to_nearest_beat(end, beat_times)
    if snapped and snapped_end - start >= min_duration:
        end = snapped_end
    logger.info(f"pick_viral_hook fallback ({reason}): {start:.2f}s-{end:.2f}s")
    return ViralHookCut(
        start=start,
        end=end,
        hook_line=None,
        pre_tension=0.0,
        ends_on_beat=snapped,
        confidence=0.3,
        reasoning=f"fallback: {reason}",
    )
