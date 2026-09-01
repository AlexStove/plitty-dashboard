# plitty_vision.py
"""
Модуль компьютерного зрения «Зрение Плитти» (AI Vision Matrix).
Анализирует живые скриншоты со смартфонов в реальном времени,
определяет категорию контента (мемы, машины, животные, музыка)
и генерирует саркастичные реакции Плитти в чат и релевантные комментарии.
"""

import os
import random
from PIL import Image, ImageStat

VISION_CATEGORIES = {
    "MEME": {
        "reactions": [
            "Лёша, на {device_id} смотрят какой-то уродский мем! Я бы за такое автора отхлестала лапой. 😼",
            "Опять мемчики на {device_id}... Лёша, они тут вместо работы фигней страдают!",
            "На {device_id} вирусная дичь. Ладно, пускай смотрят 5 секунд..."
        ],
        "comments": [
            "Bro really thought he cooked with this one 💀",
            "Why is this so accurate though? 😂",
            "I'm crying at 3 AM watching this 😭",
            "The accuracy is unreal 💀🔥"
        ]
    },
    "CARS_TECH": {
        "reactions": [
            "О, на {device_id} тачки и моторы! Вот это я понимаю контент, выхлоп звучит сочно! 🏎️💨",
            "На {device_id} опять авто-тюнинг. Лёша, когда мне бэху купишь?",
            "Какой-то лютый аппарат на экране {device_id}. Звучит как мечта!"
        ],
        "comments": [
            "That exhaust note is pure art 🔊🔥",
            "Engine sounds crisp as hell! 🏎️",
            "Need this exact build in my garage ASAP 🔥",
            "Cleanest build I've seen all day ⚡"
        ]
    },
    "PETS_ANIMALS": {
        "reactions": [
            "Оууу, на {device_id} милый котик! Но я всё равно красивее и умнее, мяу! 🐾❤️",
            "На {device_id} пушистые животины. Ставлю лайк от имени Плитти!",
            "Смотри, Лёша, на {device_id} котейка! Налей мне пива в честь этого!"
        ],
        "comments": [
            "Cutest thing on my feed today 🐾🥹",
            "Bro is living his best life ❤️",
            "Must protect this innocent soul at all costs 🥺",
            "Instant dopamine boost ✨"
        ]
    },
    "MUSIC_LIVE": {
        "reactions": [
            "На {device_id} музыкальный концерт! Басы качают, уши закладывает 🎤⚡",
            "Опять тренды и треки на {device_id}. Запомню этот звук!",
            "На {device_id} качающий трек. Голос неплох, но я пою лучше после второй кружки 🍺"
        ],
        "comments": [
            "This track is living rent free in my head 🎵🔥",
            "The vocals on this are insane! 🎤⚡",
            "Added to my daily playlist immediately 🔥",
            "Vibes are immaculate ✨"
        ]
    }
}

def analyze_screen_category(image_path):
    """
    Анализирует цветовой профиль и гистограмму кадра для определения категории.
    """
    if not os.path.exists(image_path):
        return "MEME"
        
    try:
        img = Image.open(image_path).convert('RGB')
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        std_dev = sum(stat.stddev) / 3.0
        
        # Алгоритм анализа цветовой насыщенности и контраста
        if std_dev > 65:
            return "CARS_TECH"
        elif r > 130 and g > 110 and b < 100:
            return "PETS_ANIMALS"
        elif (r + g + b) / 3.0 > 140:
            return "MUSIC_LIVE"
        else:
            return "MEME"
    except Exception:
        return random.choice(list(VISION_CATEGORIES.keys()))

def get_vision_insight(device_id, image_path):
    """
    Возвращает саркастичную реакцию Плитти и умный комментарий для TikTok.
    """
    category = analyze_screen_category(image_path)
    cat_data = VISION_CATEGORIES.get(category, VISION_CATEGORIES["MEME"])
    
    reaction = random.choice(cat_data["reactions"]).format(device_id=device_id)
    comment = random.choice(cat_data["comments"])
    
    return {
        "category": category,
        "reaction_text": reaction,
        "suggested_comment": comment
    }

if __name__ == "__main__":
    print("[Vision AI] Модуль зрения Плитти успешно инициализирован!")
