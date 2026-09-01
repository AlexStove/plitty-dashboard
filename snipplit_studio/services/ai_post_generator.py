import random
from typing import Dict, List, Any

# Трендовые наборы хэштегов по темам
HASHTAG_POOLS = [
    "#viral #fyp #reels #shorts #trending #music #topmusic #hit #vibes",
    "#tiktokmusic #song #newmusic #lyricsvideo #visualizer #edit #capcut",
    "#музыка #трек #песня #хит2026 #премьера #вирусное #рек #топ",
    "#новинка #музыкадлядуши #эстетика #рекомендации #музыкавмашину",
]

# Штампы призывов к действию (CTA)
CTA_TEMPLATES = [
    "🔥 Сохраняй трек в плейлист и делись с друзьями!",
    "🎧 Напиши в комментариях, как тебе звучание от 1 до 10!",
    "🚀 Слушай полную версию по ссылке в профиле!",
    "🎵 Добавляй к себе в медиатеку прямо сейчас!",
    "👑 Ставь лайк, если зашло этот видео сниппет!",
]

def generate_social_post_caption(title: str, artist: str = "") -> str:
    """
    Генерирует готовое вирусно оформленное описание поста с призывом и хэштегами.
    """
    artist_str = f" — {artist}" if artist and artist != "Unknown Artist" else ""
    full_name = f"{title}{artist_str}"
    
    cta = random.choice(CTA_TEMPLATES)
    tags = random.choice(HASHTAG_POOLS)
    
    caption = (
        f"🎧 **{full_name}**\n\n"
        f"{cta}\n\n"
        f"💬 Что думаешь об этом отрезке?\n\n"
        f"📌 {tags}"
    )
    return caption
