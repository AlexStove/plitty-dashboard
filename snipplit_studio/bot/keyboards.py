from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает главную клавиатуру с кнопкой запуска Mini App, базами и отрезками."""
    web_app_url = f"{config.MINI_APP_URL}/static/index.html?user_id={user_id}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎬 Открыть Mini App (в Telegram)",
                web_app=WebAppInfo(url=web_app_url)
            )
        ],
        [
            InlineKeyboardButton(
                text="🌐 Открыть Веб-Сайт в браузере",
                url=f"{config.MINI_APP_URL}/static/index.html"
            )
        ],
        [
            InlineKeyboardButton(text="🎵 База треков", callback_data="list_tracks")
        ],

        [
            InlineKeyboardButton(text="✂️ Готовые отрезки", callback_data="list_snippets")
        ],
        [
            InlineKeyboardButton(text="🎭 ИИ-Инфлюенсеры (Split-Screen)", callback_data="list_influencers"),
            InlineKeyboardButton(text="⭐ Мои Пресеты", callback_data="my_presets")
        ],

        [
            InlineKeyboardButton(text="📥 Загрузить трек", callback_data="upload_track_info"),
            InlineKeyboardButton(text="📥 Загрузить футаж", callback_data="upload_footage_info")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить бота", callback_data="reload_bot"),
            InlineKeyboardButton(text="ℹ️ Справка", callback_data="help_info")
        ]
    ])

    return keyboard

def get_after_upload_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура после загрузки трека или футажа."""
    web_app_url = f"{config.MINI_APP_URL}/static/index.html?user_id={user_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎬 Продолжить создание сниппета",
                web_app=WebAppInfo(url=web_app_url)
            )
        ],
        [
            InlineKeyboardButton(text="🏠 Возврат к главному окну", callback_data="main_menu")
        ]
    ])
    return keyboard

def get_after_media_keyboard(user_id: int, track_id: Optional[int] = None) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура под отправленным аудио/видео сообщением для продолжения работы."""
    web_app_url = f"{config.MINI_APP_URL}/static/index.html?user_id={user_id}"
    
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text="🎬 Создать сниппет в конструкторе",
                web_app=WebAppInfo(url=web_app_url)
            )
        ]
    ]

    if track_id:
        inline_keyboard.append([
            InlineKeyboardButton(text="▶️ Прослушать", callback_data=f"play_track:{track_id}"),
            InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_track:{track_id}")
        ])
        inline_keyboard.append([
            InlineKeyboardButton(text="📝 Текст песни", callback_data=f"add_lyrics:{track_id}"),
            InlineKeyboardButton(text="🎯 Авторендеринг", callback_data=f"fast_batch_menu:track:{track_id}")
        ])
        inline_keyboard.append([
            InlineKeyboardButton(text="✂️ Cut (Обрезка)", callback_data=f"cut_track:{track_id}")
        ])

    inline_keyboard.extend([
        [
            InlineKeyboardButton(text="🎵 Выбрать другой трек", callback_data="list_tracks")
        ],
        [
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
        ]
    ])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для возврата в главное меню."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
        ]
    ])
    return keyboard
