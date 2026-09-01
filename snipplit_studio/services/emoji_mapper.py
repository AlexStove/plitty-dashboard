import re
from typing import Optional

# Словарь отображения слов на эмодзи (поддержка русского и английского языков)
EMOJI_DICTIONARY = {
    # Деньги / Финансы
    r"деньг|мани|cash|money|богат|рубл|доллар|евро|купюр|бабл|кошелек|доход|прибыль|богач": "💰",
    # Огонь / Жара
    r"огон|огонь|жар|пламя|горит|гори|fire|flame|hot|выжиг": "🔥",
    # Машины / Авто
    r"машин|авто|тачк|бмв|bmw|мерс|порш|гонк|драйв|car|drive|speed|феррари|ауди": "🏎",
    # Музыка / Трек
    r"музык|трек|песн|звук|бит|битмейкер|music|song|track|sound|beat|аудио": "🎵",
    # Власть / Топ
    r"корол|корол|королев|босс|king|queen|boss|top|первы|чемпион|побед": "👑",
    # Любовь / Чувства
    r"любов|любл|сердц|душа|чувств|love|heart|kiss|обним|влюбл": "❤️",
    # Ракета / Взлет
    r"ракет|взлет|старт|рост|высот|rocket|fly|flyin|высоко": "🚀",
    # Молния / Скорость
    r"молни|быстр|скорост|ток|flash|flashin|lightn|импульс": "⚡️",
    # Звезда / Хайп
    r"звезд|хайп|успех|слава|star|hype|famous|вирус": "⭐️",
    # Вечеринка / Алкоголь
    r"туск|вечер|клуб|алко|party|drink|wine|вино|коктейл|дрин": "🍸",
    # Взгляд / Глаза
    r"глаз|взгляд|смотр|вижу|look|eyes|see|seeing": "👁",
    # Время / Часы
    r"время|час|минут|секунд|time|clock|wait|тайм": "⏱",
    # Город / Дом
    r"город|дом|улиц|city|house|home|street|высотк": "🏙",
    # Счастье / Радость
    r"счаст|радост|улыбк|смех|smile|happy|fun": "😊",
    # Космос / Ночь
    r"космос|луна|ноч|звезд|space|moon|night": "🌙",
    # Телефон / Связь
    r"телефон|звон|сообщ|phone|call|chat": "📱",
}

def get_emoji_for_word(word: str) -> Optional[str]:
    """Возвращает соответствующий эмодзи для слова или None, если соответствия нет."""
    if not word:
        return None
    cleaned = re.sub(r'[^\w\s]', '', word.lower()).strip()
    if not cleaned:
        return None

    for pattern, emoji in EMOJI_DICTIONARY.items():
        if re.search(pattern, cleaned):
            return emoji
    return None
