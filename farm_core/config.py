# config.py
"""
Конфигурационный файл для скрипта автоматизации TikTok.
Содержит настройки времени работы, пауз, вероятностей, параметров скроллинга и пула комментариев.
"""

# Время просмотра видео в ленте рекомендации (от 5 до 35 секунд)
WATCH_MIN_SEC = 5
WATCH_MAX_SEC = 35

# Stage 1 configuration (initial feed scroll duration in seconds, 8 to 12 minutes)
STAGE_1_DURATION_MIN = 480
STAGE_1_DURATION_MAX = 720
STAGE_1_DURATION_SEC = 30

# Stage 2 configuration (4 to 6 random accounts visited, watch profile for 60-90s, scroll feed for 25-45s between visits)
SKIP_STAGE_2 = True
STAGE_2_ACCOUNTS_MIN = 0
STAGE_2_ACCOUNTS_MAX = 0
STAGE_2_PROFILE_WATCH_MIN = 0
STAGE_2_PROFILE_WATCH_MAX = 0
STAGE_2_VIDEO_WATCH_MIN = 0
STAGE_2_VIDEO_WATCH_MAX = 0
STAGE_2_BETWEEN_SCROLL_MIN = 0
STAGE_2_BETWEEN_SCROLL_MAX = 0

# Stage 3 final recommendation feed scroll duration (1 to 2 minutes)
STAGE_3_DURATION_MIN = 60
STAGE_3_DURATION_MAX = 120

# Like and Comment chances (0% - pure feed scrolling)
LIKE_CHANCE = 0.0
COMMENT_CHANCE = 0.0

# Max initial stagger delay (in seconds)
INITIAL_STAGGER_MIN_SEC = 1
INITIAL_STAGGER_MAX_SEC = 10

# Scroll parameters in millimeters
SCROLL_MIN_MM = 120
SCROLL_MAX_MM = 550

# Scroll duration in milliseconds
SCROLL_DURATION_MIN_MS = 250
SCROLL_DURATION_MAX_MS = 500

# Pause between scrolls in seconds
PAUSE_MIN_SEC = 2
PAUSE_MAX_SEC = 8

# Chance to enter profile of video author in Stage 1 & Stage 3 (disabled)
ENTER_PROFILE_CHANCE = 0.0

# Video count and watch times in random profiles during Stage 1 & Stage 3
RANDOM_PROFILE_VIDEOS_MIN = 0
RANDOM_PROFILE_VIDEOS_MAX = 0
RANDOM_PROFILE_VIDEO_WATCH_MIN = 0
RANDOM_PROFILE_VIDEO_WATCH_MAX = 0

# Known TikTok packages
TIKTOK_PACKAGES = ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill", "com.ss.android.ugc.aweme"]

# Target accounts list (20 Popular Music Artists + leshaplita)
AKI_ACCOUNTS = [
    "arianagrande",
    "billieeilish",
    "edsheeran",
    "taylorswift",
    "justinbieber",
    "selenagomez",
    "dualipa",
    "shakira",
    "theweeknd",
    "mileycyrus",
    "genius",
    "imaginedragons",
    "coldplay",
    "onedirection",
    "gorillaz",
    "queen",
    "billboard",
    "linkinpark",
    "brunomars",
    "charlieputh",
    "leshaplita"
]

# Пул комментариев с эмодзи
COMMENT_POOL = [
    "So cool! 😎",
    "Love this! ❤️",
    "Amazing! 🙌",
    "Love it. 😍",
    "This is great! 👍",
    "So clean. ✨",
    "Perfect! 💯",
    "Wow! 😲",
    "Love this vibe. 🌌",
    "Awesome video! 🎬",
    "So good. 🔥",
    "Too good! 👏",
    "Nice one! 🤙",
    "Brilliant! 💡",
    "This is fire. ⚡",
    "Honestly, same. 😅",
    "Living for this. 🌟",
    "Incredible! 💥",
    "Actually cool. 😮",
    "Vibe check: pass. ✅",
    "Obsessed! 👀",
    "Too cool. 🥶",
    "Love the vibe. 🎵",
    "Unreal! 🤯",
    "So satisfying. 😌",
    "Pure art. 🎨",
    "Love the energy! 🔋",
    "Masterpiece! 🏆",
    "Stunning! ✨",
    "So aesthetic. 🌿",
    "Speechless. 🙊",
    "Mind blown. 🧠💥",
    "Best one yet! 🥇",
    "Absolute fire. 🌶️",
    "Mood! 🛌",
    "Legendary. 👑",
    "Elite content. 💎",
    "Next level! 🚀",
    "So creative. 👾",
    "Love everything here. 🫶",
    "God took His time with you.",
    "Stunning is an understatement.",
    "Visual peak right here.",
    "The camera is obsessed with you.",
    "Are we even the same species?",
    "Literal perfection, no notes.",
    "You dropped this: 👑",
    "How does it feel to be the main visual?",
    "Unmatched elegance.",
    "You just raised the beauty standards.",
    "The amount of creativity in this video is absolutely insane! 🤯",
    "How did you even come up with this brilliant idea? 💡",
    "This editing is on a whole different level of clean. ✨",
    "Your visual style is always so incredibly unique and inspiring. 🎨",
    "This is easily one of the most creative videos here. 🏆",
    "I have never seen anyone execute this concept so perfectly. 🎯",
    "The attention to detail in every single frame is unmatched. 🖼️",
    "You just raised the bar for editing on this app. 📈",
    "This is not just a video, it is pure art. 🎭",
    "I keep rewatching just to understand how you did it. 👀",
    "The transition at the end was absolutely mind-blowing, genius! ⚡",
    "You turned a simple concept into a visual masterpiece today. 💎",
    "I love how you think completely outside the box here. 📦❌",
    "This is the most original content I have seen today. 🌟",
    "Your editing skills are honestly out of this world, wow. 💻",
    "I am completely obsessed with the aesthetic of this video. 🌌",
    "You put so much effort into this and it shows. 💪",
    "This concept deserves to go viral immediately, so clever! 🚀",
    "The storytelling in such a short clip is simply amazing. 📖",
    "Everything about this video from start to finish is perfect."
]

# ==========================================
# КОНФИГУРАЦИЯ БОТА И ИНТЕГРАЦИЙ
# ==========================================
# API-ключ для Google Gemini (получить на https://aistudio.google.com/app/apikey)
GEMINI_API_KEY = "AQ.Ab8RN6LPjfjbyWv5Q213f7Qn53rL3b5-F-KOeJEfHGDjhMm3uA"

# Telegram Bot (SnipPlit / Plitty Bridge)
TELEGRAM_BOT_TOKEN = "8654316556:AAH_j5i5wrb1OLJMxeWesoSGVPYZT_56-tU"
TELEGRAM_CHAT_ID = ""



# Hugging Face Free API Key for ultra 2D anime generation (https://huggingface.co/settings/tokens)
HUGGINGFACE_API_KEY = "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"
