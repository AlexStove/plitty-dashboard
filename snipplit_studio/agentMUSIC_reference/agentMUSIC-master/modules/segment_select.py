"""
Ручной выбор фрагмента трека для нарезки.

Два способа:
  - parse_time_range  — разбор пользовательского ввода времени
                        ("45-72", "1:05 - 1:30", "90 120").
  - match_text_to_segment — fuzzy-поиск вставленного куска текста
                        по пословным таймингам Whisper.

Модуль чистый (без сети/файлов) и покрыт unit-тестами.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

# ---------------------------------------------------------------------------
# Разбор диапазона времени
# ---------------------------------------------------------------------------
# Разделители диапазона: дефис/тире разных видов, "..", "to", "до", ";"
_RANGE_SPLIT = re.compile(
    r"\s*(?:-{1,2}|–|—|‒|\.{2,}|…|\bto\b|\bдо\b|;)\s*",
    re.IGNORECASE,
)


def parse_timestamp(token: str) -> Optional[float]:
    """
    '90' -> 90.0, '1:30' -> 90.0, '1:02:03' -> 3723.0, '12.5' -> 12.5.
    Возвращает None если токен не разбирается.
    """
    token = (token or "").strip().replace(",", ".")
    if not token:
        return None
    if ":" in token:
        parts = token.split(":")
        if len(parts) > 3:
            return None
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        seconds = 0.0
        for n in nums:
            if n < 0:
                return None
            seconds = seconds * 60 + n
        return seconds
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value >= 0 else None


def parse_time_range(text: str) -> Optional[tuple[float, float]]:
    """
    Разбирает '45-72', '1:05 - 1:30', '00:45 1:30', '90 120' → (start, end).
    Возвращает None если распарсить не удалось или end <= start.
    """
    if not text:
        return None
    raw = text.strip()

    # 1) явный разделитель диапазона
    parts = [p for p in _RANGE_SPLIT.split(raw) if p.strip()]
    if len(parts) != 2:
        # 2) fallback — два числа через пробел
        parts = [p for p in re.split(r"\s+", raw) if p.strip()]
    if len(parts) != 2:
        return None

    start = parse_timestamp(parts[0])
    end = parse_timestamp(parts[1])
    if start is None or end is None:
        return None
    if end <= start:
        return None
    return (start, end)


# ---------------------------------------------------------------------------
# Fuzzy-поиск текста по таймингам Whisper
# ---------------------------------------------------------------------------
_NON_WORD = re.compile(r"[^\w']+", re.UNICODE)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower().replace("ё", "е")
    return text


def _tokenize(text: str) -> list[str]:
    return [t for t in _NON_WORD.split(_normalize(text)) if t]


def flatten_words(full_segments: list[dict]) -> list[dict]:
    """
    Разворачивает сегменты Whisper в плоский список слов с таймингами.
    Если у сегмента нет пословных таймингов — раскидывает слова равномерно.
    Каждый элемент: {"norm": str, "start": float, "end": float}.
    """
    flat: list[dict] = []
    for seg in full_segments or []:
        seg_start = float(seg.get("start", 0.0) or 0.0)
        seg_end = float(seg.get("end", seg_start) or seg_start)
        words = seg.get("words") or []
        if words:
            for w in words:
                norm = "".join(_tokenize(w.get("word", "")))
                if not norm:
                    continue
                ws = w.get("start")
                we = w.get("end")
                flat.append({
                    "norm": norm,
                    "start": float(ws if ws is not None else seg_start),
                    "end": float(we if we is not None else seg_end),
                })
        else:
            toks = _tokenize(seg.get("text", ""))
            if not toks:
                continue
            step = (seg_end - seg_start) / len(toks) if seg_end > seg_start else 0.0
            for i, t in enumerate(toks):
                flat.append({
                    "norm": t,
                    "start": seg_start + i * step,
                    "end": seg_start + (i + 1) * step,
                })
    return flat


def match_text_to_segment(
    full_segments: list[dict],
    query: str,
    min_score: float = 0.55,
    pad: float = 0.25,
) -> Optional[dict]:
    """
    Находит во всём треке фрагмент, максимально похожий на вставленный текст.

    Использует пословные тайминги Whisper + скользящее окно и SequenceMatcher.
    Возвращает {"start", "end", "score", "text"} либо None, если совпадение
    слишком слабое (score < min_score).

    pad — добавочные секунды по краям, чтобы не срезать крайние слова.
    """
    flat = flatten_words(full_segments)
    q_tokens = _tokenize(query)
    if not flat or not q_tokens:
        return None

    flat_norms = [w["norm"] for w in flat]
    q_str = " ".join(q_tokens)
    q_len = len(q_tokens)
    n = len(flat)

    # Окна вокруг длины запроса (учёт лишних/пропущенных слов при распознавании)
    window_lens = sorted({
        max(1, q_len - 2), max(1, q_len - 1), q_len,
        q_len + 1, q_len + 2, q_len + 3,
    })

    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(q_str)

    best: Optional[tuple[float, int, int]] = None  # (score, i, j)
    for win in window_lens:
        if win > n:
            continue
        for i in range(0, n - win + 1):
            cand = " ".join(flat_norms[i:i + win])
            matcher.set_seq1(cand)
            # quick_ratio — дешёвая верхняя оценка; отсекаем заведомо худшие
            if best is not None and matcher.quick_ratio() <= best[0]:
                continue
            score = matcher.ratio()
            if best is None or score > best[0]:
                best = (score, i, i + win - 1)
        if best is not None and best[0] >= 0.995:
            break

    if best is None or best[0] < min_score:
        return None

    _, i, j = best
    start = max(0.0, flat[i]["start"] - pad)
    end = flat[j]["end"] + pad
    if end <= start:
        return None
    return {
        "start": start,
        "end": end,
        "score": best[0],
        "text": " ".join(flat_norms[i:j + 1]),
    }
