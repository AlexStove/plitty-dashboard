import os
import sys
import asyncio
import random
import uuid
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup



sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database.db import db
import config
from bot.keyboards import get_main_keyboard, get_back_keyboard, get_after_media_keyboard

router = Router()

def get_welcome_text() -> str:
    return (
        "🚀 **SnipPlitAiStudio — Автоматическая Фабрика Роликов (9:16)**\n\n"
        "🔥 **Главные возможности платформы:**\n\n"
        "1. 🎭 **ИИ-Инфлюенсеры & Split-Screen** — Создавайте реакции аватара на футажи и мемы. 1 генерация = 50 готовых роликов!\n"
        "2. 🎯 **AI-Поиск Припевов (Multi-Chorus)** — Нейросеть сама находит самые вирусные 15-30 секунд в любом треке.\n"
        "3. ⚡️ **Субтитры MrBeast & Hormozi + AI Emoji** — Авто-караоке субтитры с динамической анимацией и авто-эмодзи.\n"
        "4. 📦 **Авто-Пак 30 Роликов в 1 Клик** — Генерируйте контент-пак на всю неделю в едином ZIP-архиве.\n"
        "5. 🌐 **Веб-Сайт & REST API Service** — Полный доступ через браузер или внешний API.\n\n"
        "🔗 **Ссылки для входа в Веб-Сервис:**\n"
        f"• 🌐 **Онлайн в браузере:** {config.MINI_APP_URL}/static/index.html\n"
        "• 💻 **Локально на ПК:** http://localhost:8000/static/index.html\n\n"
        "🎵 **Инструкция по загрузке:**\n"
        "• Отправьте `.mp3` файл или ссылку на **YouTube**, **TikTok**, **Spotify**, **Яндекс Музыку**.\n"
        "• Отправьте `.mp4` видео для пополнения базы футажей.\n\n"
        "Нажмите кнопки ниже для старта работы!"
    )


HELP_TEXT = (
    "Вы можете загружать свои медиафайлы напрямую в этот чат:\n\n"
    "🎵 **Как добавить музыку:**\n"
    "• Отправьте аудиофайл (`.mp3`, `.m4a`, `.wav`) с вашего ПК/телефона.\n"
    "• Или пришлите ссылку на **YouTube**, **Spotify** или **Яндекс Музыку** (мы скачаем аудио автоматически).\n\n"
    "📹 **Как добавить видеофутаж:**\n"
    "• Отправьте видеофайл (`.mp4`) в виде документа или обычного видео.\n\n"
    "📝 **Как добавить субтитры (караоке):**\n"
    "• Отправьте файл субтитров в формате `.lrc` (тайминг + текст).\n\n"
    "Нажмите на кнопку **«🎬 Открыть конструктор»** ниже, чтобы открыть визуальный редактор и собрать сниппет!"
)


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None, parse_mode=None):
    """
    Если сообщение текстовое — редактируем его.
    Если сообщение содержит видео, аудио или медиа-файл — высылаем новое текстовое сообщение.
    """
    try:
        msg = callback.message
        if msg and msg.text is not None and not msg.video and not msg.audio and not msg.document:
            return await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            return await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        print(f"[!] safe_edit_text fallback error: {e}")
        try:
            # Фолбек без parse_mode при ошибках парсинга спецсимволов
            if callback.message:
                return await callback.message.answer(text, reply_markup=reply_markup)
        except Exception:
            pass

DIRECT_SNIPPET_HOLDER = {}

async def start_influencer_wizard_with_snippet(callback: CallbackQuery, snippet_path: str = None, page: int = 0):
    """Проваливаемся в выбор ИИ-Инфлюенсера для создания видео реакций со сниппетом."""
    try:
        from main import sync_influencers_from_folder
        sync_influencers_from_folder()
    except Exception:
        pass
        
    influencers = db.get_all_influencers()
    if not influencers:
        await safe_edit_text(
            callback,
            "📭 В базе пока нет ИИ-Инфлюенсеров. Положите видео реакции в папку `downloads/influencers/`!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]])
        )
        return
        
    if snippet_path:
        DIRECT_SNIPPET_HOLDER[callback.from_user.id] = snippet_path
        
    text = f"👤 **Выберите ИИ-Инфлюенсера для создания видеореакции (ИИ-Инфлюенсер + Сниппет):**\n\nВсего профилей в базе: `{len(influencers)}`."
    
    total = len(influencers)
    per_page = 10
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total)
    page_influencers = influencers[start_idx:end_idx]
    
    inline_keyboard = []
    row = []
    for inf in page_influencers:
        row.append(InlineKeyboardButton(text=f"👤 {inf['name']}", callback_data=f"render_direct_inf:{inf['id']}"))
        if len(row) == 2:
            inline_keyboard.append(row)
            row = []
    if row:
        inline_keyboard.append(row)
        
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"direct_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="ignore_noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"direct_page:{page+1}"))
        inline_keyboard.append(nav_row)
        
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Рандомный инфлюенсер", callback_data="render_direct_inf:random")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("direct_page:"))
async def cb_direct_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[1])
    await start_influencer_wizard_with_snippet(callback, snippet_path=None, page=page)


@router.callback_query(F.data.startswith("render_direct_inf:"))
async def cb_render_direct_inf(callback: CallbackQuery):
    await callback.answer("🚀 Создаю видеореакцию ИИ-Инфлюенсер + Сниппет...")
    inf_id_str = callback.data.split(":")[1]
    
    snip_path = DIRECT_SNIPPET_HOLDER.get(callback.from_user.id)
    if not snip_path or not Path(snip_path).exists():
        # Берем случайный сохраненный сниппет из базы
        saved = db.get_all_saved_video_snippets()
        if saved:
            snip_path = random.choice(saved)["file_path"]
            
    if not snip_path or not Path(snip_path).exists():
        await callback.message.answer("❌ Файл сниппета не найден. Создайте сниппет через бота!")
        return
        
    influencers = db.get_all_influencers()
    if not influencers:
        await callback.message.answer("❌ В базе нет ИИ-Инфлюенсеров.")
        return
        
    if inf_id_str == "random":
        curr_inf = random.choice(influencers)
    else:
        curr_inf = db.get_influencer(int(inf_id_str)) or influencers[0]
        
    clean_name = curr_inf['name'].replace(" ", "_").replace("/", "").replace("\\", "")
    out_filename = f"{clean_name}_snippet_reaction_{uuid.uuid4().hex[:4]}.mp4"
    from services.video_engine import render_split_screen_reaction

    
    loop = asyncio.get_running_loop()
    res_path = await loop.run_in_executor(
        None,
        render_split_screen_reaction,
        snip_path,
        curr_inf["video_path"],
        out_filename,
        "split50"
    )
    
    back_to_main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Сгенерировать ещё ролики", callback_data="list_influencers")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    video = FSInputFile(res_path)
    await callback.message.answer_video(
        video=video,
        caption=f"🎬 **Split-Screen Ролик (ИИ-Инфлюенсер + Сниппет) готов!**\n\n👤 ИИ-Инфлюенсер: {curr_inf['name']}",
        parse_mode="Markdown",
        reply_markup=back_to_main_kb
    )

@router.callback_query(F.data == "list_influencers")
async def cb_list_influencers(callback: CallbackQuery):
    await callback.answer()
    try:
        from main import sync_influencers_from_folder
        sync_influencers_from_folder()
    except Exception:
        pass
    influencers = db.get_all_influencers()
    count_inf = len(influencers)
    
    text = (
        "🎭 **Фабрика ИИ-Инфлюенсеров (Split-Screen 50/50)**\n\n"
        f"Добавлено профилей инфлюенсеров в базу: `{count_inf}`\n\n"
        "Выберите формат контента для генерации:"
    )
    
    inline_keyboard = [
        [InlineKeyboardButton(text="🪝 ИИ-Инфлюенсер + Хуки (Авто-склейка)", callback_data="inf_step1:hooks")],
        [InlineKeyboardButton(text="🎬 ИИ-Инфлюенсер + Сниппет (Живой рендер)", callback_data="inf_step1:live_snippet")],
        [InlineKeyboardButton(text="💾 ИИ-Инфлюенсер + Сохраненные сниппеты", callback_data="inf_step1:snippets")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ]
    
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

def build_influencers_keyboard(mode: str, influencers: list, page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    total = len(influencers)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total)
    page_influencers = influencers[start_idx:end_idx]
    
    inline_keyboard = [
        [InlineKeyboardButton(text=f"🔥 Сгенерить для КАЖДОГО ({total} инфлюенсеров)", callback_data=f"inf_run_all:{mode}")]
    ]
    
    # Размещаем по 2 инфлюенсера в строке для удобства
    row = []
    for inf in page_influencers:
        row.append(InlineKeyboardButton(text=f"👤 {inf['name']}", callback_data=f"inf_step2:{mode}:{inf['id']}"))
        if len(row) == 2:
            inline_keyboard.append(row)
            row = []
    if row:
        inline_keyboard.append(row)
        
    # Строка переключения страниц
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"inf_step1:{mode}:{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="ignore_noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"inf_step1:{mode}:{page+1}"))
        inline_keyboard.append(nav_row)
        
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Рандомный инфлюенсер", callback_data=f"inf_step2:{mode}:random")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="list_influencers")])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

@router.callback_query(F.data == "ignore_noop")
async def cb_ignore_noop(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(F.data.startswith("inf_step1:"))
async def cb_inf_step1(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass

    parts = callback.data.split(":")
    mode = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0
    
    try:
        from main import sync_influencers_from_folder
        sync_influencers_from_folder()
    except Exception:
        pass
        
    influencers = db.get_all_influencers()
    if not influencers:
        await safe_edit_text(
            callback,
            "📭 В базе пока нет ИИ-Инфлюенсеров. Положите ролик с реакцией в папку `downloads/influencers/`!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="list_influencers")]])
        )
        return
        
    if mode == "hooks":
        mode_title = "🪝 ИИ-Инфлюенсер + Хуки"
    elif mode == "live_snippet":
        mode_title = "🎬 ИИ-Инфлюенсер + Сниппет"
    else:
        mode_title = "💾 ИИ-Инфлюенсер + Сниппеты"

    text = (
        f"👤 **Шаг 1 из 3: Выберите ИИ-Инфлюенсера** ({mode_title})\n\n"
        f"Всего профилей в базе: `{len(influencers)}`.\n"
        f"Выберите персонажа или используйте кнопки страниц ◀️ ▶️:"
    )
    
    kb = build_influencers_keyboard(mode, influencers, page=page)
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("inf_run_all:"))
async def cb_inf_run_all(callback: CallbackQuery):
    await callback.answer("🚀 Запускаю массовую генерацию роликов для каждого инфлюенсера...")
    mode = callback.data.split(":")[1]
    
    influencers = db.get_all_influencers()
    if not influencers:
        await callback.message.answer("❌ В базе нет ИИ-Инфлюенсеров.")
        return
        
    total_count = len(influencers)
    status_msg = await callback.message.answer(
        f"⏳ **Массовая уникальная генерация роликов для каждого из {total_count} инфлюенсеров...**\n\n"
        f"Пожалуйста, подождите, идёт рендеринг по 1 уникальному ролику на каждого персонажа...",
        parse_mode="Markdown"
    )
    
    import zipfile
    from services.video_engine import render_split_screen_reaction, render_snippet
    
    # Сбор уникальных пулов без повторов
    shuffled_infs = random.sample(influencers, k=len(influencers))
    
    top_pool = []
    style_pool = []
    filter_pool = []
    
    all_hook_paths = []
    if mode == "hooks":
        hooks_dir = config.DOWNLOADS_DIR / "footages" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_files = list(hooks_dir.glob("*.mp4")) + list(hooks_dir.glob("*.mov"))
        db_hooks = [Path(f["file_path"]) for f in db.get_all_footages(category="hooks") if Path(f["file_path"]).exists()]
        all_hook_paths = list(set([str(p) for p in (hook_files + db_hooks)]))
        if not all_hook_paths:
            all_footages = db.get_all_footages()
            all_hook_paths = [f["file_path"] for f in all_footages if Path(f["file_path"]).exists()]
        if not all_hook_paths:
            await status_msg.edit_text("❌ В категории «Хуки» нет доступных файлов.")
            return
    elif mode == "snippets":
        saved_snips = [s["file_path"] for s in db.get_all_saved_video_snippets() if Path(s["file_path"]).exists()]
        all_footages = [f["file_path"] for f in db.get_all_footages() if Path(f["file_path"]).exists()]
        unique_pool = list(dict.fromkeys(saved_snips + all_footages))
        if not unique_pool:
            await status_msg.edit_text("❌ В базе нет сохраненных сниппетов или видео-футажей.")
            return
        shuffled_pool = random.sample(unique_pool, k=len(unique_pool))
        top_pool = [shuffled_pool[i % len(shuffled_pool)] for i in range(total_count)]
    elif mode == "live_snippet":
        all_footages = [f for f in db.get_all_footages() if Path(f["file_path"]).exists()]
        if not all_footages:
            await status_msg.edit_text("❌ В базе нет видео-футажей для создания сниппета.")
            return
        shuffled_footages = random.sample(all_footages, k=len(all_footages))
        top_pool = [shuffled_footages[i % len(shuffled_footages)] for i in range(total_count)]
        shuffled_styles = random.sample(config.SUBTITLE_STYLES, k=len(config.SUBTITLE_STYLES))
        style_pool = [shuffled_styles[i % len(config.SUBTITLE_STYLES)] for i in range(total_count)]
        shuffled_filters = random.sample(config.VIDEO_FILTERS, k=len(config.VIDEO_FILTERS))
        filter_pool = [shuffled_filters[i % len(config.VIDEO_FILTERS)] for i in range(total_count)]
        
    generated_paths = []
    duration = 20.0
    
    for idx in range(1, total_count + 1):
        curr_inf = shuffled_infs[idx - 1]
        try:
            await status_msg.edit_text(
                f"⏳ **Генерация уникальных роликов ({idx}/{total_count}):** {curr_inf['name']}...\n"
                f"▓▓▓▓▓▓▓▓░░ {int(idx/total_count*100)}%",
                parse_mode="Markdown"
            )
            
            clean_inf_name = curr_inf['name'].replace(" ", "_").replace("/", "").replace("\\", "")
            out_filename = f"{clean_inf_name}_reaction_{idx}_{uuid.uuid4().hex[:4]}.mp4"
            
            if mode == "live_snippet":
                curr_footage = top_pool[idx - 1]
                curr_style = style_pool[idx - 1]
                curr_filter = filter_pool[idx - 1]
                
                segments = db.get_all_audio_segments()
                tracks = db.get_all_tracks()
                
                if not tracks and not segments:
                    await status_msg.edit_text("❌ В базе нет треков или отрезков. Загрузите аудиофайл!")
                    return

                if segments:
                    seg = segments[(idx - 1) % len(segments)]
                    audio_file_path = seg['file_path']
                    duration = min(float(seg.get('duration') or 20.0), 20.0)
                else:
                    active_track = tracks[(idx - 1) % len(tracks)]
                    audio_file_path = active_track['file_path']
                
                temp_snip_name = f"temp_live_snip_{uuid.uuid4().hex[:6]}.mp4"
                loop = asyncio.get_running_loop()
                temp_snip_path = await loop.run_in_executor(
                    None,
                    render_snippet,
                    audio_file_path,
                    curr_footage['file_path'],
                    0.0,
                    duration,
                    [],
                    temp_snip_name,
                    True,
                    curr_style,
                    curr_filter,
                    True,
                    "word",
                    "bottom"
                )
                
                res_path = await loop.run_in_executor(
                    None,
                    render_split_screen_reaction,
                    temp_snip_path,
                    curr_inf["video_path"],
                    out_filename,
                    "split50",
                    duration
                )
                try:
                    Path(temp_snip_path).unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                top_source = random.sample(all_hook_paths, k=len(all_hook_paths)) if mode == "hooks" else top_pool[idx - 1]
                loop = asyncio.get_running_loop()
                res_path = await loop.run_in_executor(
                    None,
                    render_split_screen_reaction,
                    top_source,
                    curr_inf["video_path"],
                    out_filename,
                    "split50",
                    duration
                )
            generated_paths.append((res_path, curr_inf['name']))
        except Exception as err:
            print(f"[!] Ошибка рендеринга для {curr_inf['name']}: {err}")
            
    if not generated_paths:
        await status_msg.edit_text("❌ Не удалось сгенерировать ролики.")
        return
        
    await status_msg.edit_text(f"✅ **Успешно сгенерировано {len(generated_paths)} уникальных роликов! Отправляю...**", parse_mode="Markdown")
    
    back_to_main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Сгенерировать ещё ролики", callback_data="list_influencers")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    if len(generated_paths) <= 3:
        for idx_p, (p, inf_name) in enumerate(generated_paths):
            video = FSInputFile(p)
            kb = back_to_main_kb if idx_p == len(generated_paths) - 1 else None
            try:
                await callback.message.answer_video(
                    video=video,
                    caption=f"🎬 **Split-Screen Ролик готов!**\n👤 ИИ-Инфлюенсер: {inf_name}",
                    parse_mode="Markdown",
                    reply_markup=kb,
                    request_timeout=300
                )
            except Exception as e:
                print(f"[!] Ошибка отправки видео {p}: {e}")
    else:
        zip_filename = f"All_Influencers_Pack_{len(generated_paths)}_Videos.zip"
        zip_path = config.OUTPUT_DIR / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for p, _ in generated_paths:
                zf.write(p, arcname=Path(p).name)
                
        zip_size_mb = round(zip_path.stat().st_size / (1024 * 1024), 1)
        await callback.message.answer(
            f"📦 **Пакетный ZIP-архив ИИ-Инфлюенсеров готов!**\n\n"
            f"⏱ **Количество роликов:** {len(generated_paths)} шт.\n"
            f"💾 **Размер архива:** `{zip_size_mb} MB`\n\n"
            f"📁 **Локальный путь к архиву на ПК:**\n"
            f"`{zip_path}`",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb
        )



def build_influencers_preset_keyboard(item_type: str, item_id: int, duration: int, influencers: list, page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    total = len(influencers)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total)
    page_influencers = influencers[start_idx:end_idx]
    
    inline_keyboard = [
        [InlineKeyboardButton(text=f"🔥 Сгенерить для КАЖДОГО ({total} инфлюенсеров)", callback_data=f"inf_run_all:live_snippet")]
    ]
    
    row = []
    for inf in page_influencers:
        row.append(InlineKeyboardButton(text=f"👤 {inf['name']}", callback_data=f"inf_step3:live_snippet:{inf['id']}:{duration}"))
        if len(row) == 2:
            inline_keyboard.append(row)
            row = []
    if row:
        inline_keyboard.append(row)
        
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"inf_preset_page:{item_type}:{item_id}:{duration}:{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="ignore_noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"inf_preset_page:{item_type}:{item_id}:{duration}:{page+1}"))
        inline_keyboard.append(nav_row)
        
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Рандомный инфлюенсер", callback_data=f"inf_step3:live_snippet:random:{duration}")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data=f"batch_dur:{item_type}:{item_id}:{duration}")])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

@router.callback_query(F.data.startswith("inf_preset:"))
@router.callback_query(F.data.startswith("inf_preset_page:"))
async def cb_inf_preset(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])
    duration = int(parts[3])
    page = int(parts[4]) if len(parts) > 4 else 0

    influencers = db.get_all_influencers()
    if not influencers:
        await safe_edit_text(
            callback,
            "📭 В базе пока нет ИИ-Инфлюенсеров.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"batch_dur:{item_type}:{item_id}:{duration}")]])
        )
        return

    text = (
        f"👤 <b>Выберите ИИ-Инфлюенсера</b> (Сплит-Экран 50/50)\n\n"
        f"⏱ <b>Зафиксированная длительность:</b> <code>{duration} секунд</code>\n"
        f"Всего профилей в базе: <code>{len(influencers)}</code>.\n"
        f"Выберите персонажа или нажмите «🔥 Сгенерить для КАЖДОГО»:"
    )

    kb = build_influencers_preset_keyboard(item_type, item_id, duration, influencers, page=page)
    await safe_edit_text(
        callback,
        text,
        parse_mode="HTML",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("inf_step2:"))
async def cb_inf_step2(callback: CallbackQuery):

    await callback.answer()
    parts = callback.data.split(":")
    mode = parts[1]
    inf_id = parts[2]
    
    inf_name = "Рандомный инфлюенсер"
    if inf_id != "random":
        inf = db.get_influencer(int(inf_id))
        if inf:
            inf_name = inf["name"]
            
    if mode == "hooks":
        mode_title = "🪝 Хуки (Авто-склейка)"
    elif mode == "live_snippet":
        mode_title = "🎬 Сниппет (Живой рендер)"
    else:
        mode_title = "💾 Сохраненные сниппеты"

    text = (
        f"⏱ **Шаг 2 из 4: Выберите хронометраж видео**\n\n"
        f"• Персонаж: **{inf_name}**\n"
        f"• Режим: **{mode_title}**\n\n"
        f"Какую длительность готовых видеореакций установить?"
    )
    
    inline_keyboard = [
        [
            InlineKeyboardButton(text="⏱ 15 сек", callback_data=f"inf_step3:{mode}:{inf_id}:15"),
            InlineKeyboardButton(text="⏱ 20 сек (Рекомендуется)", callback_data=f"inf_step3:{mode}:{inf_id}:20")
        ],
        [
            InlineKeyboardButton(text="⏱ 25 сек", callback_data=f"inf_step3:{mode}:{inf_id}:25"),
            InlineKeyboardButton(text="⏱ 30 сек", callback_data=f"inf_step3:{mode}:{inf_id}:30")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"inf_step1:{mode}")]
    ]
    
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("inf_step3:"))
async def cb_inf_step3(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    mode = parts[1]
    inf_id = parts[2]
    duration = int(parts[3])
    
    inf_name = "Рандомный инфлюенсер"
    if inf_id != "random":
        inf = db.get_influencer(int(inf_id))
        if inf:
            inf_name = inf["name"]
            
    if mode == "hooks":
        mode_title = "🪝 ИИ-Инфлюенсер + Хуки"
    elif mode == "live_snippet":
        mode_title = "🎬 ИИ-Инфлюенсер + Сниппет"
    else:
        mode_title = "💾 ИИ-Инфлюенсер + Сниппеты"

    text = (
        f"📊 **Шаг 3 из 4: Выберите количество роликов**\n\n"
        f"• **Режим:** {mode_title}\n"
        f"• **Инфлюенсер:** {inf_name}\n"
        f"• **Длительность:** {duration} сек.\n\n"
        f"Сколько готовых роликов сгенерировать в этой пачке?\n"
        f"<i>При выборе 10+ роликов гарантируется 100% уникальность сниппетов и инфлюенсеров в паке (без повторов)!</i>"
    )
    
    inline_keyboard = [
        [
            InlineKeyboardButton(text="1 ролик", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:1"),
            InlineKeyboardButton(text="3 ролика", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:3")
        ],
        [
            InlineKeyboardButton(text="5 роликов", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:5"),
            InlineKeyboardButton(text="10 роликов (Уникальные)", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:10")
        ],
        [
            InlineKeyboardButton(text="15 роликов (Уникальные)", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:15"),
            InlineKeyboardButton(text="20 роликов (Уникальные)", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:20")
        ],
        [
            InlineKeyboardButton(text="30 роликов (Уникальные)", callback_data=f"inf_confirm:{mode}:{inf_id}:{duration}:30")
        ],
        [InlineKeyboardButton(text="🔙 Назад к длительности", callback_data=f"inf_step2:{mode}:{inf_id}")]
    ]
    
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("inf_confirm:"))
async def cb_inf_confirm(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    mode = parts[1]
    inf_id = parts[2]
    duration = int(parts[3])
    count = int(parts[4])
    
    inf_name = "Рандомный инфлюенсер"
    if inf_id != "random":
        inf = db.get_influencer(int(inf_id))
        if inf:
            inf_name = inf["name"]
            
    if mode == "hooks":
        mode_title = "🪝 ИИ-Инфлюенсер + Хуки"
    elif mode == "live_snippet":
        mode_title = "🎬 ИИ-Инфлюенсер + Сниппет"
    else:
        mode_title = "💾 ИИ-Инфлюенсер + Сниппеты"

    text = (
        f"🚀 **Шаг 4 из 4: Подтверждение генерации**\n\n"
        f"• **Режим:** {mode_title}\n"
        f"• **Инфлюенсер:** {inf_name}\n"
        f"• **Длительность:** {duration} сек.\n"
        f"• **Количество:** {count} шт. (Уникальные)\n\n"
        f"Нажмите кнопку ниже для старта рендеринга!"
    )
    
    inline_keyboard = [
        [InlineKeyboardButton(text=f"🚀 Запустить уникальную генерацию ({count} роликов по {duration}с)", callback_data=f"inf_run:{mode}:{inf_id}:{duration}:{count}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
    ]
    
    await safe_edit_text(
        callback,
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("inf_run:"))
async def cb_inf_run(callback: CallbackQuery):
    await callback.answer("🚀 Запускаю рендеринг видеореакций...")
    parts = callback.data.split(":")
    mode = parts[1]
    inf_id_str = parts[2]
    if len(parts) >= 5:
        duration = float(parts[3])
        count = int(parts[4])
    else:
        duration = 20.0
        count = int(parts[3])
    
    status_msg = await callback.message.answer(
        f"⏳ **Старт уникальной генерации пачки ({count} роликов по {int(duration)}с)...**\n\n"
        f"Пожалуйста, подождите, идёт рендеринг сниппетов и кадрирование без повторов...",
        parse_mode="Markdown"
    )
    
    import zipfile
    from services.video_engine import render_split_screen_reaction, render_snippet
    
    influencers = db.get_all_influencers()
    if not influencers:
        await status_msg.edit_text("❌ В базе нет ИИ-инфлюенсеров.")
        return
        
    # Сбор строго уникальных пулов без повторов в рамках одной пачки
    shuffled_infs = random.sample(influencers, k=len(influencers))
    if inf_id_str == "random":
        inf_pool = [shuffled_infs[i % len(shuffled_infs)] for i in range(count)]
    else:
        chosen_inf = db.get_influencer(int(inf_id_str)) if inf_id_str.isdigit() else influencers[0]
        inf_pool = [chosen_inf or influencers[0]] * count

    top_pool = []
    style_pool = []
    filter_pool = []

    if mode == "hooks":
        hooks_dir = config.DOWNLOADS_DIR / "footages" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_files = list(hooks_dir.glob("*.mp4")) + list(hooks_dir.glob("*.mov"))
        db_hooks = [Path(f["file_path"]) for f in db.get_all_footages(category="hooks") if Path(f["file_path"]).exists()]
        all_hook_paths = list(set([str(p) for p in (hook_files + db_hooks)]))
        
        if not all_hook_paths:
            all_footages = db.get_all_footages()
            all_hook_paths = [f["file_path"] for f in all_footages if Path(f["file_path"]).exists()]
            
        if not all_hook_paths:
            await status_msg.edit_text("❌ В категории «Хуки» нет доступных файлов.")
            return

    elif mode == "snippets":
        saved_snips = [s["file_path"] for s in db.get_all_saved_video_snippets() if Path(s["file_path"]).exists()]
        all_footages = [f["file_path"] for f in db.get_all_footages() if Path(f["file_path"]).exists()]
        unique_pool = list(dict.fromkeys(saved_snips + all_footages))
        if not unique_pool:
            await status_msg.edit_text("❌ В базе нет сохраненных сниппетов или видео-футажей.")
            return
        shuffled_pool = random.sample(unique_pool, k=len(unique_pool))
        top_pool = [shuffled_pool[i % len(shuffled_pool)] for i in range(count)]

    elif mode == "live_snippet":
        all_footages = [f for f in db.get_all_footages() if Path(f["file_path"]).exists()]
        if not all_footages:
            await status_msg.edit_text("❌ В базе нет доступных видео-футажей для создания сниппета.")
            return
        shuffled_footages = random.sample(all_footages, k=len(all_footages))
        top_pool = [shuffled_footages[i % len(shuffled_footages)] for i in range(count)]
        
        shuffled_styles = random.sample(config.SUBTITLE_STYLES, k=len(config.SUBTITLE_STYLES))
        style_pool = [shuffled_styles[i % len(config.SUBTITLE_STYLES)] for i in range(count)]
        
        shuffled_filters = random.sample(config.VIDEO_FILTERS, k=len(config.VIDEO_FILTERS))
        filter_pool = [shuffled_filters[i % len(config.VIDEO_FILTERS)] for i in range(count)]

    generated_paths = []
    
    for idx in range(1, count + 1):
        try:
            curr_inf = inf_pool[idx - 1]
            await status_msg.edit_text(
                f"⏳ **Генерация уникального ролика {idx} из {count} ({int(duration)}с)...**\n"
                f"👤 Инфлюенсер: {curr_inf['name']}\n"
                f"▓▓▓▓▓▓▓▓░░ {int(idx/count*100)}%",
                parse_mode="Markdown"
            )
            
            clean_inf_name = curr_inf['name'].replace(" ", "_").replace("/", "").replace("\\", "")
            out_filename = f"{clean_inf_name}_reaction_{idx}_{uuid.uuid4().hex[:4]}.mp4"

            if mode == "live_snippet":
                curr_footage = top_pool[idx - 1]
                curr_style = style_pool[idx - 1]
                curr_filter = filter_pool[idx - 1]
                
                segments = db.get_all_audio_segments()
                tracks = db.get_all_tracks()
                
                if not tracks and not segments:
                    await status_msg.edit_text("❌ В базе нет треков или отрезков. Загрузите аудиофайл!")
                    return

                if segments:
                    seg = segments[(idx - 1) % len(segments)]
                    audio_file_path = seg['file_path']
                    duration = min(float(seg.get('duration') or 20.0), 20.0)
                else:
                    active_track = tracks[(idx - 1) % len(tracks)]
                    audio_file_path = active_track['file_path']
                
                temp_snip_name = f"temp_live_snip_{uuid.uuid4().hex[:6]}.mp4"
                loop = asyncio.get_running_loop()
                temp_snip_path = await loop.run_in_executor(
                    None,
                    render_snippet,
                    audio_file_path,
                    curr_footage['file_path'],
                    0.0,
                    duration,
                    [],
                    temp_snip_name,
                    True,
                    curr_style,
                    curr_filter,
                    True,
                    "word",
                    "bottom"
                )
                
                res_path = await loop.run_in_executor(
                    None,
                    render_split_screen_reaction,
                    temp_snip_path,
                    curr_inf["video_path"],
                    out_filename,
                    "split50",
                    duration
                )
                try:
                    Path(temp_snip_path).unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                top_source = random.sample(all_hook_paths, k=len(all_hook_paths)) if mode == "hooks" else top_pool[idx - 1]
                loop = asyncio.get_running_loop()
                res_path = await loop.run_in_executor(
                    None,
                    render_split_screen_reaction,
                    top_source,
                    curr_inf["video_path"],
                    out_filename,
                    "split50",
                    duration
                )
            generated_paths.append(res_path)
        except Exception as err:
            print(f"[!] Ошибка рендеринга ролика #{idx}: {err}")


            
    if not generated_paths:
        await status_msg.edit_text("❌ Не удалось сгенерировать видеоролики.")
        return
        
    await status_msg.edit_text(f"✅ **Успешно сгенерировано {len(generated_paths)} роликов! Отправляю...**", parse_mode="Markdown")

    
    back_to_main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Сгенерировать ещё ролики", callback_data="list_influencers")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

    if len(generated_paths) <= 3:
        for idx_p, p in enumerate(generated_paths):
            video = FSInputFile(p)
            kb = back_to_main_kb if idx_p == len(generated_paths) - 1 else None
            try:
                await callback.message.answer_video(
                    video=video,
                    caption="🎬 **Готовый Split-Screen ролик ИИ-Инфлюенсера**",
                    parse_mode="Markdown",
                    reply_markup=kb,
                    request_timeout=300
                )
            except Exception as e:
                print(f"[!] Ошибка отправки видео {p}: {e}")
    else:
        # Упаковываем в ZIP архив и возвращаем локальный путь на ПК без загрузки через Telegram API
        zip_filename = f"Influencer_Pack_{len(generated_paths)}_Videos.zip"
        zip_path = config.OUTPUT_DIR / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for p in generated_paths:
                zf.write(p, arcname=Path(p).name)
                
        zip_size_mb = round(zip_path.stat().st_size / (1024 * 1024), 1)
        await callback.message.answer(
            f"📦 **Пакетный ZIP-архив ИИ-Инфлюенсеров готов!**\n\n"
            f"⏱ **Количество роликов:** {len(generated_paths)} шт. ({int(duration)}с)\n"
            f"💾 **Размер архива:** `{zip_size_mb} MB`\n\n"
            f"📁 **Локальный путь к архиву на ПК:**\n"
            f"`{zip_path}`",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb
        )






@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    welcome_text = get_welcome_text() + f"\n\n🔑 **Ваш Telegram ID:** `{user_id}`"
    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

@router.message(Command("reload", "restart", "refresh"))
async def cmd_reload(message: Message):
    try:
        from main import sync_local_files
        sync_local_files()
    except Exception:
        pass
    user_id = message.from_user.id
    welcome_text = get_welcome_text() + f"\n\n🔑 **Ваш Telegram ID:** `{user_id}`"
    await message.answer(
        "🔄 **Бот и медиабаза обновлены!**\n\n" + welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback,
        get_welcome_text(),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )

@router.callback_query(F.data == "my_presets")
async def cb_my_presets(callback: CallbackQuery):
    await callback.answer()
    presets = db.get_user_presets(callback.from_user.id)
    
    if not presets:
        text = (
            "⭐ <b>Мои Пресеты (Сохраненные стили и связки):</b>\n\n"
            "<i>У вас пока нет сохраненных пресетов.</i>\n\n"
            "При сохранении генерации вы можете сохранить связку (Категория, Стиль субтитров, Сплит и Фильтр) для быстрого вызова в 1 клик!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
    else:
        text = "⭐ <b>Ваши сохраненные пресеты генерации:</b>\n\n"
        kb_rows = []
        for p in presets:
            text += f"• <b>{p['name']}</b> ({p['subtitle_style'].upper()} | {p['layout']} | {p['video_filter']})\n"
            kb_rows.append([
                InlineKeyboardButton(text=f"⚡️ {p['name']}", callback_data=f"use_preset:{p['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del_preset:{p['id']}")
            ])
        kb_rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        
    await safe_edit_text(callback, text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data.startswith("del_preset:"))
async def cb_del_preset(callback: CallbackQuery):
    await callback.answer("✅ Пресет удален", show_alert=True)
    preset_id = int(callback.data.split(":")[1])
    db.delete_user_preset(preset_id)
    await cb_my_presets(callback)


@router.callback_query(F.data == "reload_bot")
async def cb_reload_bot(callback: CallbackQuery):
    await callback.answer("🔄 Бот и медиабаза обновлены!", show_alert=True)
    try:
        from main import sync_local_files
        sync_local_files()
    except Exception:
        pass
    await safe_edit_text(
        callback,
        get_welcome_text(),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )




@router.callback_query(F.data == "upload_track_info")
async def cb_upload_track_info(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📥 **Как загрузить трек в бота:**\n\n"
        "1. **Аудиофайл:** Отправьте файл (`.mp3`, `.m4a`, `.wav`) с телефона или ПК прямо в этот чат.\n"
        "2. **Ссылка:** Или пришлите ссылку на песню из **Яндекс Музыки**, **Spotify** или **YouTube**.\n\n"
        "Бот автоматически скачает музыку, определит название и найдет караоке-субтитры!\n\n"
        "👇 Отправьте файл или ссылку прямо сейчас:"
    )
    await safe_edit_text(callback, text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@router.callback_query(F.data == "upload_footage_info")
async def cb_upload_footage_info(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📥 **Как загрузить видеофутаж в бота:**\n\n"
        "1. **Через чат:** Отправьте видеофайл (`.mp4`) в этот чат как документ или обычное видео.\n"
        "2. **Через папку на ПК:** Положите видеофайл в папку `downloads/footages/` и нажмите «🔄 Обновить бота».\n"
        "3. **Через ссылку:** Пришлите публичную ссылку на видеоролик.\n"
        "   └ *Поддерживаемые платформы:* **TikTok**, **YouTube Shorts**, **Instagram Reels**, **VK Клипы**, **Pinterest**.\n\n"
        "👇 Отправьте видеофайл или ссылку прямо сейчас:"
    )
    await safe_edit_text(callback, text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@router.callback_query(F.data == "help_info")
async def cb_help_info(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback,
        HELP_TEXT,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

# --- База треков с прослушиванием и удалением ---
@router.callback_query(F.data == "list_tracks")
async def cb_list_tracks(callback: CallbackQuery):
    await callback.answer()
    try:
        from main import sync_local_files
        sync_local_files()
    except Exception:
        pass
    tracks = db.get_all_tracks()
    if not tracks:
        await safe_edit_text(
            callback,
            "📭 В базе пока нет треков. Загрузите файлы или отправьте ссылки!",
            reply_markup=get_back_keyboard()
        )
        return

    text = "🎵 Список доступных треков:\n\n"
    inline_keyboard = []

    for i, track in enumerate(tracks[:15], 1):
        artist_val = (track.get('artist') or '').strip()
        title_val = (track.get('title') or '').strip()

        if artist_val.lower() in ["unknown artist", "unknown", "none", ""]:
            full_display = title_val
            button_label = title_val
        else:
            full_display = f"{artist_val} - {title_val}"
            button_label = f"{artist_val} - {title_val}"

        duration = f"({int(track['duration'])} сек)" if track['duration'] else ""
        lyrics_status = "📝 Субтитры есть" if track['lyrics_path'] else "❌ Без субтитров"
        text += f"{i}. {full_display} {duration}\n└ {lyrics_status} | Источник: {track['source']}\n\n"

        short_name = (button_label[:30] + '…') if len(button_label) > 33 else button_label

        inline_keyboard.append([
            InlineKeyboardButton(text=f"▶️ {short_name}", callback_data=f"play_track:{track['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_track:{track['id']}")
        ])



    inline_keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    await safe_edit_text(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("play_track:"))
async def cb_play_track(callback: CallbackQuery):
    await callback.answer("⏳ Отправляю аудиофайл в чат...")
    track_id = int(callback.data.split(":")[1])
    track = db.get_track(track_id)
    if not track or not Path(track['file_path']).exists():
        await callback.answer("❌ Файл трека не найден на сервере", show_alert=True)
        return
    audio = FSInputFile(track['file_path'])
    artist_str = f"{track['artist']} - " if track['artist'] else ""
    await callback.message.answer_audio(
        audio=audio,
        caption=f"🎵 {artist_str}{track['title']}",
        reply_markup=get_after_media_keyboard(callback.from_user.id, track_id=track_id)
    )

@router.callback_query(F.data.startswith("del_track:"))
async def cb_del_track(callback: CallbackQuery):
    await callback.answer("✅ Трек удален из базы и с диска", show_alert=True)
    track_id = int(callback.data.split(":")[1])
    db.delete_track(track_id)
    await cb_list_tracks(callback)

class TrackRenameStates(StatesGroup):
    waiting_for_name = State()

@router.callback_query(F.data.startswith("edit_track:"))
async def cb_edit_track(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    track_id = int(callback.data.split(":")[1])
    track = db.get_track(track_id)
    if not track:
        await callback.answer("❌ Трек не найден", show_alert=True)
        return
        
    await state.update_data(editing_track_id=track_id)
    await state.set_state(TrackRenameStates.waiting_for_name)
    
    current_artist = track.get('artist') or 'Unknown Artist'
    current_title = track.get('title') or 'Track'
    
    await callback.message.answer(
        f"✏️ **Изменение названия трека (ID: `{track_id}`)**\n\n"
        f"Текущее имя: `{current_artist} - {current_title}`\n\n"
        f"Пришлите новое название в ответном сообщении в формате:\n"
        f"`Исполнитель - Название`\n\n"
        f"_(Пример: Bhad Bhabie - Gucci Flip Flops)_"
    )

@router.message(TrackRenameStates.waiting_for_name)
async def process_track_rename(message: Message, state: FSMContext):
    data = await state.get_data()
    track_id = data.get("editing_track_id")
    await state.clear()
    
    if not track_id:
        await message.answer("❌ Ошибка контекста редактирования.")
        return
        
    text = message.text.strip()
    if " - " in text:
        parts = text.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    elif " — " in text:
        parts = text.split(" — ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    else:
        artist = "Unknown Artist"
        title = text
        
    db.update_track_metadata(track_id, title, artist)
    
    await message.answer(
        f"✅ **Метаданные трека успешно обновлены!**\n\n"
        f"🎵 **Название:** {artist} - {title}\n"
        f"🆔 ID трека: `{track_id}`",
        reply_markup=get_after_media_keyboard(message.from_user.id, track_id=track_id)
    )


# --- База футажей с просмотром и удалением ---
@router.callback_query(F.data == "list_footages")
async def cb_list_footages(callback: CallbackQuery):
    await callback.answer()
    try:
        from main import sync_local_files
        sync_local_files()
    except Exception:
        pass
    footages = db.get_all_footages()
    if not footages:
        await safe_edit_text(
            callback,
            "📭 В базе пока нет футажей. Загрузите видеофайлы (.mp4)!",
            reply_markup=get_back_keyboard()
        )
        return

    text = "📹 Список доступных видеофутажей:\n\n"
    inline_keyboard = []

    for i, foot in enumerate(footages[:15], 1):
        duration = f"({int(foot['duration'])} сек)" if foot['duration'] else ""
        resolution = f"[{foot['width']}x{foot['height']}]" if foot['width'] else ""
        text += f"{i}. {foot['filename']} {duration} {resolution}\n"

        short_name = (foot['filename'][:24] + '…') if len(foot['filename']) > 26 else foot['filename']
        inline_keyboard.append([
            InlineKeyboardButton(text=f"▶️ {short_name}", callback_data=f"play_footage:{foot['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_footage:{foot['id']}")
        ])

    inline_keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    await safe_edit_text(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("play_footage:"))
async def cb_play_footage(callback: CallbackQuery):
    await callback.answer("⏳ Отправляю видеофутаж...")
    footage_id = int(callback.data.split(":")[1])
    foot = db.get_footage(footage_id)
    if not foot or not Path(foot['file_path']).exists():
        await callback.answer("❌ Файл футажа не найден", show_alert=True)
        return
    video = FSInputFile(foot['file_path'])
    await callback.message.answer_video(
        video=video,
        caption=f"📹 {foot['filename']}",
        reply_markup=get_after_media_keyboard(callback.from_user.id)
    )

@router.callback_query(F.data.startswith("del_footage:"))
async def cb_del_footage(callback: CallbackQuery):
    await callback.answer("✅ Футаж удален из базы и с диска", show_alert=True)
    footage_id = int(callback.data.split(":")[1])
    db.delete_footage(footage_id)
    await cb_list_footages(callback)

# --- База сохраненных аудио-отрезков (музыкальные нарезки) ---
@router.callback_query(F.data == "list_snippets")
async def cb_list_snippets(callback: CallbackQuery):
    await callback.answer()
    segments = db.get_all_audio_segments()
    if not segments:
        await safe_edit_text(
            callback,
            "📭 У вас пока нет сохраненных аудио-отрезков.\nОни автоматически сохраняются при первой сборке любого сниппета!",
            reply_markup=get_back_keyboard()
        )
        return

    text = "✂️ Сохраненные аудио-отрезки (для многократной видео-генерации):\n\n"
    inline_keyboard = []

    for i, seg in enumerate(segments[:15], 1):
        text += f"{i}. {seg['name']} ({int(seg['duration'])} сек)\n"
        short_name = (seg['name'][:14] + '…') if len(seg['name']) > 16 else seg['name']
        inline_keyboard.append([
            InlineKeyboardButton(text=f"▶️ {short_name}", callback_data=f"play_segment:{seg['id']}"),
            InlineKeyboardButton(text="✏️ Текст", callback_data=f"edit_seg_lyrics:{seg['id']}"),
            InlineKeyboardButton(text="⚡️ Рендер", callback_data=f"fast_batch_menu:segment:{seg['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_segment:{seg['id']}")
        ])

    inline_keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    await safe_edit_text(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )

@router.callback_query(F.data.startswith("play_segment:"))
async def cb_play_segment(callback: CallbackQuery):
    await callback.answer("⏳ Отправляю аудио-отрезок...")
    segment_id = int(callback.data.split(":")[1])
    seg = db.get_audio_segment(segment_id)
    if not seg or not Path(seg['file_path']).exists():
        await callback.answer("❌ Аудиофайл отрезка не найден", show_alert=True)
        return
    audio = FSInputFile(seg['file_path'])
    
    seg_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать субтитры", callback_data=f"edit_seg_lyrics:{segment_id}"),
            InlineKeyboardButton(text="⚡️ Авторендеринг", callback_data=f"fast_batch_menu:segment:{segment_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 К списку отрезков", callback_data="list_snippets")
        ]
    ])
    
    await callback.message.answer_audio(
        audio=audio,
        caption=f"✂️ Аудио-отрезок: {seg['name']}",
        reply_markup=seg_kb
    )


@router.callback_query(F.data.startswith("del_segment:"))
async def cb_del_segment(callback: CallbackQuery):
    await callback.answer("✅ Аудио-отрезок удален", show_alert=True)
    segment_id = int(callback.data.split(":")[1])
    db.delete_audio_segment(segment_id)
    await cb_list_snippets(callback)

@router.callback_query(F.data == "generate_influencer_hooks")

async def cb_generate_influencer_hooks(callback: CallbackQuery):
    await callback.answer("⏳ Собираю доступные видео-хуки и рендерю Split-Screen ролики...")
    
    hooks_dir = config.DOWNLOADS_DIR / "footages" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    
    hook_files = list(hooks_dir.glob("*.mp4")) + list(hooks_dir.glob("*.mov"))
    db_hooks = [Path(f["file_path"]) for f in db.get_all_footages(category="hooks") if Path(f["file_path"]).exists()]
    all_hook_paths = list(set([str(p) for p in (hook_files + db_hooks)]))
    
    if not all_hook_paths:
        await callback.message.answer(
            "📭 В категории **«Хуки»** пока нет файлов.\n\n"
            "Положите короткие ролики-хуки (1-10 секунд) в папку:\n`downloads/footages/hooks`\n"
            "или пришлите их в чат бота с префиксом `hook_1.mp4`!",
            parse_mode="Markdown"
        )
        return
        
    influencers = db.get_all_influencers()
    if not influencers:
        await callback.message.answer("📭 В базе пока нет ИИ-Инфлюенсеров.")
        return
        
    inf = influencers[0]
    output_filename = f"influencer_hook_reaction_{inf['id']}.mp4"
    
    from services.video_engine import render_split_screen_reaction
    
    loop = asyncio.get_running_loop()
    result_path = await loop.run_in_executor(
        None,
        render_split_screen_reaction,
        all_hook_paths,
        inf["video_path"],
        output_filename,
        "split50"
    )
    
    video = FSInputFile(result_path)
    await callback.message.answer_video(
        video=video,
        caption=f"🎭 **Split-Screen Реакция на Хуки готова!**\n\n👤 ИИ-Инфлюенсер: {inf['name']}\n🪝 Хуки автоматически склеены под хронометраж реакции!",
        parse_mode="Markdown"
    )

