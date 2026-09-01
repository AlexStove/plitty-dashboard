import os
from pathlib import Path

# Базовый путь проекта
BASE_DIR = Path(__file__).resolve().parent

# Токен Telegram Бота (загружается из окружения или прописывается вручную)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8654316556:AAH_j5i5wrb1OLJMxeWesoSGVPYZT_56-tU")

# Токен Yandex Music API для прямого скачивания 320kbps MP3
YANDEX_MUSIC_TOKEN = os.getenv("YANDEX_MUSIC_TOKEN", "y0_AgAAAABCdQ_hAAG8XgAAAADrKNUK-JEBsswyQUaBQLxCQ-0eeXoR_qI")


# Настройки базы данных
DB_PATH = BASE_DIR / "database" / "bot.db"

# Пути к папкам хранения медиафайлов
DOWNLOADS_DIR = BASE_DIR / "downloads"
MUSIC_DIR = DOWNLOADS_DIR / "music"
FOOTAGE_DIR = DOWNLOADS_DIR / "footages"
OUTPUT_DIR = DOWNLOADS_DIR / "outputs"

# Шрифт для караоке-субтитров
FONT_DIR = BASE_DIR / "fonts"
FONT_PATH = FONT_DIR / "Montserrat-Bold.ttf"

# Настройки веб-сервера (Mini App Backend)
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", 8000))

# URL-адрес Mini App (для интеграции с ботом)
# Для работы в Telegram Mini App требуется HTTPS. Для локального тестирования
# рекомендуется запустить ngrok (например: ngrok http 8000) и вставить адрес сюда.
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://seasons-herein-aud-covered.trycloudflare.com")

# Доступные стили субтитров и видеофильтры
SUBTITLE_STYLES = ["tiktok", "neon", "gradient", "karaoke_yellow", "minimal_white"]
VIDEO_FILTERS = ["none", "vhs", "cyberpunk", "warm_cinematic", "bw"]




# Создаем необходимые папки, если их нет
for directory in [MUSIC_DIR, FOOTAGE_DIR, OUTPUT_DIR, FONT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
