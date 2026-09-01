"""
Claude Agent: генерирует дополнительные поисковые запросы
на основе описания трека.
"""

import logging
import json
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)


def generate_search_queries(
    track_description: str,
    base_queries: list[str],
    api_key: str,
    max_extra: int = 5,
) -> list[str]:
    """
    Дополняет базовый список запросов релевантными запросами,
    сгенерированными Claude на основе описания трека.

    Returns объединённый список (без дубликатов).
    """
    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        f"Я создаю видеоконтент для трека с таким описанием:\n\n"
        f"{track_description}\n\n"
        f"Уже есть базовые поисковые запросы для поиска видеофутажей:\n"
        f"{json.dumps(base_queries, ensure_ascii=False)}\n\n"
        f"Предложи ещё {max_extra} поисковых запросов на английском языке "
        f"для поиска визуально подходящих видеофутажей на Pixabay и Pexels. "
        f"Запросы должны быть короткими (2-4 слова), атмосферными и триггерными "
        f"для эмоции трека. Верни ТОЛЬКО JSON-массив строк, без пояснений."
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # Извлекаем JSON-массив
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            return base_queries
        extra_queries = json.loads(text[start:end])
        if not isinstance(extra_queries, list):
            return base_queries

        # Claude-запросы первыми (они релевантнее для конкретного трека)
        combined = [q for q in extra_queries if isinstance(q, str)]
        seen = set(q.lower() for q in combined)
        for q in base_queries:
            if q.lower() not in seen:
                combined.append(q)
                seen.add(q.lower())

        logger.info(f"Claude добавил {len(combined) - len(base_queries)} запросов")
        return combined

    except Exception as e:
        logger.error(f"Ошибка генерации запросов Claude: {e}")
        return base_queries


def pick_trigger_segment(
    segments: list[dict],
    api_key: str,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
) -> Optional[tuple[float, float, str]]:
    """
    Анализирует весь текст трека через Claude и выбирает самый
    триггерный/вирусный фрагмент (припев, хук, эмоциональный пик).

    segments: список сегментов Whisper [{text, start, end}, ...]
    Returns: (start_sec, end_sec, reason) или None
    """
    if not segments:
        return None

    # Формируем текст с таймингами для Claude
    lines = []
    for i, seg in enumerate(segments):
        s = seg.get("start", 0)
        e = seg.get("end", 0)
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{s:.1f}s - {e:.1f}s] {text}")

    if not lines:
        return None

    full_text = "\n".join(lines)
    total_duration = segments[-1].get("end", 0) - segments[0].get("start", 0)

    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        f"Ты — эксперт по вирусному музыкальному контенту для TikTok/Reels/Shorts.\n\n"
        f"Вот текст трека с таймингами:\n\n{full_text}\n\n"
        f"Выбери ОДИН самый триггерный, цепляющий фрагмент для короткого видео. "
        f"Это может быть:\n"
        f"- Припев (самая запоминающаяся часть)\n"
        f"- Хук (фраза которая цепляет)\n"
        f"- Эмоциональный пик\n"
        f"- Самая вирусная/мемная строчка\n\n"
        f"Фрагмент должен быть от {min_duration:.0f} до {max_duration:.0f} секунд.\n"
        f"Если припев повторяется — выбери ПЕРВОЕ вхождение.\n\n"
        f"Верни ТОЛЬКО JSON без пояснений:\n"
        f'{{"start": <число секунд>, "end": <число секунд>, "reason": "<почему этот фрагмент триггерный>"}}'
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()

        # Извлекаем JSON
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx == -1 or end_idx == 0:
            return None

        data = json.loads(text[start_idx:end_idx])
        seg_start = float(data["start"])
        seg_end = float(data["end"])
        reason = data.get("reason", "")

        # Валидация
        if seg_end <= seg_start:
            return None
        dur = seg_end - seg_start
        if dur < min_duration * 0.5:
            seg_end = seg_start + min_duration
        if dur > max_duration:
            seg_end = seg_start + max_duration

        logger.info(f"Claude выбрал триггер: {seg_start:.1f}s-{seg_end:.1f}s — {reason}")
        return (seg_start, seg_end, reason)

    except Exception as e:
        logger.error(f"Ошибка Claude pick_trigger: {e}")
        return None


# ---------------------------------------------------------------------------
#  Генерация hook-текстов для формата "Открытие трека"
# ---------------------------------------------------------------------------

# Шаблоны-фоллбэки если Claude недоступен
_FALLBACK_HOOKS_EN = [
    {"hook": "I can't believe this song only has {streams} streams", "reaction": "where has this been my whole life"},
    {"hook": "Why does nobody talk about this song", "reaction": "this needs to blow up"},
    {"hook": "POV: you just found your new favorite song", "reaction": "I've been listening on repeat for hours"},
    {"hook": "This song has {streams} streams and it makes no sense", "reaction": "this deserves millions"},
    {"hook": "How is no one talking about this", "reaction": "genuinely speechless right now"},
]

_FALLBACK_HOOKS_RU = [
    {"hook": "У этого трека всего {streams} прослушиваний", "reaction": "где это было всю мою жизнь"},
    {"hook": "Почему никто не говорит про этот трек", "reaction": "это должно взорваться"},
    {"hook": "POV: ты только что нашёл свой новый любимый трек", "reaction": "слушаю на повторе уже час"},
    {"hook": "У этого трека {streams} стримов и это не имеет смысла", "reaction": "он заслуживает миллионы"},
    {"hook": "Как об этом никто не знает", "reaction": "я реально в шоке"},
]


def generate_discovery_hooks(
    api_key: str,
    streams: str = "",
    track_name: str = "",
    lang: str = "en",
) -> dict:
    """
    Генерирует hook и reaction тексты для формата "Открытие трека".

    Returns: {"hook": str, "reaction": str}
    """
    import random

    fallbacks = _FALLBACK_HOOKS_EN if lang == "en" else _FALLBACK_HOOKS_RU
    fallback = random.choice(fallbacks)
    fallback = {
        "hook": fallback["hook"].format(streams=streams or "5K"),
        "reaction": fallback["reaction"],
    }

    if not api_key or api_key == "your_anthropic_api_key_here":
        return fallback

    lang_label = "английском" if lang == "en" else "русском"
    streams_info = f"У трека {streams} прослушиваний." if streams else "Количество стримов неизвестно."
    track_info = f"Название трека: {track_name}." if track_name else ""

    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        f"Ты — эксперт по вирусному контенту TikTok/Reels/Shorts.\n\n"
        f"Мне нужен текст для видео в формате 'Track Discovery' — "
        f"будто ты случайно наткнулся на крутой трек и делишься с другом.\n\n"
        f"{track_info}\n"
        f"{streams_info}\n\n"
        f"Сгенерируй на {lang_label} языке:\n"
        f"1. hook — цепляющая фраза в начале (1 предложение, макс 60 символов)\n"
        f"2. reaction — реакция в конце (1 фраза, макс 45 символов)\n\n"
        f"Правила:\n"
        f"- НЕ должно выглядеть как реклама\n"
        f"- Должно звучать как личная рекомендация друга\n"
        f"- Используй FOMO (страх упустить)\n"
        f"- Если есть стримы — подай малое количество как преимущество\n"
        f"- Будь креативным, НЕ используй шаблонные фразы\n\n"
        f"Верни ТОЛЬКО JSON без пояснений:\n"
        f'{{"hook": "...", "reaction": "..."}}'
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        if start_idx == -1 or end_idx == 0:
            return fallback

        data = json.loads(text[start_idx:end_idx])
        hook = data.get("hook", "").strip()
        reaction = data.get("reaction", "").strip()

        if not hook or not reaction:
            return fallback

        logger.info(f"Discovery hooks: hook='{hook}', reaction='{reaction}'")
        return {"hook": hook, "reaction": reaction}

    except Exception as e:
        logger.error(f"Ошибка генерации discovery hooks: {e}")
        return fallback
