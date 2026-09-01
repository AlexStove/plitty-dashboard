import asyncio
import random
import json
import html
import zipfile
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, Message

from database.db import db
import config
from bot.keyboards import get_main_keyboard, get_after_media_keyboard
from services.chorus_extractor import detect_chorus
from services.lrc_parser import parse_lrc
from services.video_engine import render_snippet

import uuid
import os

router = Router()
logger = logging.getLogger(__name__)

TEMP_SNIPPETS_CACHE = {}

async def safe_edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None) -> Message:
    """Безопасно редактирует сообщение или отправляет новое в чат."""
    try:
        msg = callback.message
        if msg and msg.text is not None and not msg.video and not msg.audio and not msg.document:
            return await msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            return await msg.answer(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        print(f"[!] safe_edit_or_answer fallback error: {e}")
        try:
            if callback.message:
                return await callback.message.answer(text, reply_markup=reply_markup)
        except Exception:
            pass

def get_snippet_action_keyboard(temp_id: str) -> InlineKeyboardMarkup:

    """Интерактивная клавиатура из 4 кнопок после создания сниппета."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_snip:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="🚀 Продолжить с сохранением", callback_data=f"save_and_inf:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="⏩ Продолжить без сохранения", callback_data=f"cont_inf:{temp_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_snip:{temp_id}")
        ]
    ])

@router.callback_query(F.data.startswith("fast_batch_menu:"))

async def cb_fast_batch_menu(callback: CallbackQuery):
    """Шаг 1 из 4: Выбор длительности сниппета (15, 20, 25, 30 сек)."""

    parts = callback.data.split(":")
    item_type = parts[1] # 'track' или 'segment'
    item_id = int(parts[2])

    if item_type == "track":
        header_text = (
            "🎯 <b>Генерация по авто-определению припева (librosa AI)</b>\n\n"
            "⏱ <b>Шаг 1 из 4:</b> Выберите длительность будущего сниппета:"
        )
    else:
        header_text = (
            "✂️ <b>Генерация по готовому аудио-отрезку</b>\n\n"
            "⏱ <b>Шаг 1 из 4:</b> Выберите длительность сниппета:"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏱ 10 сек", callback_data=f"batch_dur:{item_type}:{item_id}:10"),
            InlineKeyboardButton(text="⏱ 15 сек", callback_data=f"batch_dur:{item_type}:{item_id}:15"),
            InlineKeyboardButton(text="⏱ 20 сек", callback_data=f"batch_dur:{item_type}:{item_id}:20")
        ],
        [
            InlineKeyboardButton(text="⏱ 25 сек", callback_data=f"batch_dur:{item_type}:{item_id}:25"),
            InlineKeyboardButton(text="⏱ 30 сек", callback_data=f"batch_dur:{item_type}:{item_id}:30")
        ],
        [
            InlineKeyboardButton(text="🧪 А/Б Тест 4 вирусных концепта", callback_data=f"ab_test_pack:{item_type}:{item_id}")
        ],
        [
            InlineKeyboardButton(text="🤡 Мем-Фабрика (Meme Reaction)", callback_data=f"meme_factory_run:{item_type}:{item_id}")
        ],
        [
            InlineKeyboardButton(text="🚀 Пакет 30 роликов (Auto-Channel Pack)", callback_data=f"start_pack_30:{item_type}:{item_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
        ]
    ])



    await safe_edit_or_answer(callback, header_text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("batch_dur:"))
async def cb_batch_dur(callback: CallbackQuery):
    """Шаг 2 из 4: Выбор категории фоновых видеофутажей."""
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])
    duration = int(parts[3])

    header_text = (
        f"⏱ <b>Выбранная длительность:</b> <code>{duration} секунд</code>\n\n"
        f"📹 <b>Шаг 2 из 4:</b> Выберите тему/категорию фоновых видеофутажей:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏎 Машины / Авто", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:cars"),
            InlineKeyboardButton(text="⚽️ Футбол / Спорт", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:football")
        ],
        [
            InlineKeyboardButton(text="👠 Мода / Стиль", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:fashion"),
            InlineKeyboardButton(text="🌆 Город / Неон", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:city")
        ],
        [
            InlineKeyboardButton(text="🎭 ИИ-Инфлюенсеры (Split-Screen 50/50)", callback_data=f"inf_preset:{item_type}:{item_id}:{duration}")
        ],

        [
            InlineKeyboardButton(text="🎲 Все категории (Случайные)", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:all")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад к длительности", callback_data=f"fast_batch_menu:{item_type}:{item_id}")
        ]
    ])


    await safe_edit_or_answer(callback, header_text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("batch_cat:"))
async def cb_batch_cat(callback: CallbackQuery):
    """Шаг 3 из 4: Выбор количества роликов (1, 3, 5, 10 шт)."""
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])
    duration = int(parts[3])
    category = parts[4]

    cat_titles = {
        "cars": "🏎 Машины",
        "football": "⚽️ Футбол",
        "fashion": "👠 Мода",
        "beauty": "👠 Мода",
        "city": "🌆 Город",
        "all": "🎲 Все категории"
    }
    cat_str = cat_titles.get(category, category)

    header_text = (
        f"⏱ <b>Длительность:</b> <code>{duration}с</code> | 🎬 <b>Тематика:</b> {cat_str}\n\n"
        f"🎬 <b>Шаг 3 из 4:</b> Выберите количество роликов для генерации:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 1 сниппет", callback_data=f"batch_count:{item_type}:{item_id}:{duration}:{category}:1"),
            InlineKeyboardButton(text="🎬 3 сниппета", callback_data=f"batch_count:{item_type}:{item_id}:{duration}:{category}:3")
        ],
        [
            InlineKeyboardButton(text="🎬 5 сниппетов", callback_data=f"batch_count:{item_type}:{item_id}:{duration}:{category}:5"),
            InlineKeyboardButton(text="🎬 10 сниппетов", callback_data=f"batch_count:{item_type}:{item_id}:{duration}:{category}:10")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад к выбору категории", callback_data=f"batch_dur:{item_type}:{item_id}:{duration}")
        ]
    ])

    await safe_edit_or_answer(callback, header_text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("batch_count:"))
async def cb_batch_count(callback: CallbackQuery):
    """Шаг 4 из 4: Выбор способа получения файлов."""
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])
    duration = int(parts[3])
    category = parts[4]
    count = int(parts[5])

    cat_titles = {
        "cars": "🏎 Машины",
        "football": "⚽️ Футбол",
        "fashion": "👠 Мода",
        "beauty": "👠 Мода",
        "city": "🌆 Город",
        "all": "🎲 Все категории"
    }

    cat_str = cat_titles.get(category, category)

    header_text = (
        f"⏱ <b>Длительность:</b> <code>{duration}с</code> | 🎬 <b>Категория:</b> {cat_str} | 🔢 <b>Количество:</b> <code>{count} шт.</code>\n\n"
        f"📦 <b>Шаг 4 из 4:</b> Выберите способ получения файлов:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📹 Выслать по одному в чат", callback_data=f"start_batch:{item_type}:{item_id}:{duration}:{category}:{count}:chat")
        ],
        [
            InlineKeyboardButton(text="📦 Одним ZIP-архивом", callback_data=f"start_batch:{item_type}:{item_id}:{duration}:{category}:{count}:zip")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад к выбору количества", callback_data=f"batch_cat:{item_type}:{item_id}:{duration}:{category}")
        ]
    ])

    await safe_edit_or_answer(callback, header_text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("start_batch:"))
async def cb_start_batch(callback: CallbackQuery):
    """Запускает пакетную генерацию N сниппетов с фильтрацией по категории."""
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])
    duration = float(parts[3])
    
    # Совместимость со старыми/новыми форматами вызова
    if len(parts) >= 7:
        category = parts[4]
        count = int(parts[5])
        delivery_mode = parts[6]
    else:
        category = "all"
        count = int(parts[4])
        delivery_mode = parts[5] if len(parts) > 5 else "chat"

    footages = db.get_all_footages(category=category)
    if not footages:
        footages = db.get_all_footages()


    if not footages:
        await callback.answer("❌ В базе нет доступных видеофутажей!", show_alert=True)
        return


    # 1. Получаем базовые данные о треке / отрезке
    if item_type == "track":
        track = db.get_track(item_id)
        if not track:
            await callback.answer("❌ Трек не найден", show_alert=True)
            return
        artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']
        track_path = track['file_path']
        is_segment = False
    else:
        seg = db.get_audio_segment(item_id)
        if not seg:
            await callback.answer("❌ Отрезок не найден", show_alert=True)
            return
        artist_title = seg['name']
        track_path = seg['file_path']
        is_segment = True

    safe_title = html.escape(artist_title)

    mode_str = "🎯 Авто-поиск припева (librosa AI)" if not is_segment else "✂️ Сохраненный аудио-отрезок"
    delivery_str = "📦 ZIP-архив" if delivery_mode == "zip" else "📹 Сообщения в чат"

    status_msg = await safe_edit_or_answer(
        callback,
        f"🚀 <b>Запущена пакетная генерация ({count} сниппетов по {int(duration)}с)</b>\n\n"
        f"🎵 <b>Трек:</b> {safe_title}\n"
        f"⏱ <b>Длительность:</b> <code>{int(duration)} сек</code>\n"
        f"⚙️ <b>Режим:</b> {mode_str}\n"
        f"🚚 <b>Доставка:</b> {delivery_str}\n"
        f"⏳ <b>Статус:</b> Подготовка файлов и распознавание речи (Whisper AI)...\n"
        f"📊 <b>Прогресс:</b> 0/{count} готов(о)"
    )
    await callback.answer(f"⏳ Анализ трека {int(duration)}с...")

    loop = asyncio.get_running_loop()

    # 3. Поиск припева
    if not is_segment:
        lyrics = []
        if track.get('lyrics_path') and Path(track['lyrics_path']).exists():
            try:
                with open(track['lyrics_path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    lyrics = parse_lrc(content)
            except Exception as e:
                logger.error(f"Ошибка чтения LRC: {e}")

        # Поиск припева
        chorus = await loop.run_in_executor(None, detect_chorus, track['file_path'], duration)
        start_time = chorus.start
        end_time = chorus.end
        chorus_info_str = f"{int(start_time // 60):02d}:{int(start_time % 60):02d} – {int(end_time // 60):02d}:{int(end_time % 60):02d} ({chorus.duration:.0f}с)"
    else:
        start_time = 0.0
        end_time = min(duration, seg['duration'])
        chorus_info_str = f"00:00 – {int(end_time)}с"
        try:
            lyrics = json.loads(seg['lyrics_json']) if seg.get('lyrics_json') else []
        except Exception:
            lyrics = []

    # 4. Выбор N случайных футажей со строго равным шансом выпадения любого видео из базы
    selected_footages = db.get_random_footages(count, category=category)


    # Списки случайных стилей, режимов и фильтров для полной уникальности каждого сниппета
    SUBTITLE_STYLES = ['tiktok', 'neon', 'minimal', 'stroke']
    SUBTITLE_MODES = ['phrase', 'word', 'karaoke']
    VIDEO_FILTERS = ['none', 'vhs', 'cyberpunk', 'bw', 'warm_cinematic']

    rendered_paths = []

    # 5. Рендеринг роликов
    for idx, foot in enumerate(selected_footages, 1):
        safe_foot = html.escape(foot['filename'])
        rand_style = random.choice(SUBTITLE_STYLES)
        rand_mode = random.choice(SUBTITLE_MODES)
        rand_filter = random.choice(VIDEO_FILTERS)

        try:
            await status_msg.edit_text(
                f"🚀 <b>Рендеринг сниппета ({idx}/{count})</b>\n\n"
                f"🎵 <b>Трек:</b> {safe_title}\n"
                f"⏱ <b>Длительность:</b> <code>{int(end_time - start_time)} сек</code>\n"
                f"🎨 <b>Стиль субтитров:</b> <code>{rand_style.upper()} ({rand_mode})</code>\n"
                f"🎬 <b>Видеоэффект:</b> <code>{rand_filter.upper()}</code>\n"
                f"📹 <b>Футаж:</b> <code>{safe_foot}</code>\n"
                f"⏳ <b>Статус:</b> Генерация видео 9:16 и караоке по вокалу...\n"
                f"📊 <b>Прогресс:</b> {idx - 1}/{count} готов(о)",
                parse_mode="HTML"
            )

            out_filename = f"snippet_{callback.from_user.id}_{idx}_{int(loop.time())}.mp4"

            result_path = await loop.run_in_executor(
                None,
                render_snippet,
                track_path,
                foot['file_path'],
                start_time,
                end_time,
                lyrics,
                out_filename,
                True, # Vertical 9:16
                rand_style, # Рандомный стиль субтитров
                rand_filter, # Рандомный видеофильтр
                True, # Smart Crop 6% Zoom Watermark Removal
                rand_mode, # Рандомный режим субтитров (phrase / word / karaoke)
                "bottom" # Safe Zone Reels
            )

            rendered_paths.append((result_path, foot['filename'], rand_style, rand_filter))

            temp_id = f"snp_{uuid.uuid4().hex[:8]}"
            TEMP_SNIPPETS_CACHE[temp_id] = {
                "title": f"{artist_title}",
                "file_path": result_path,
                "duration": float(end_time - start_time)
            }

            # Если выбрана отправка по одному ролику в чат
            if delivery_mode == "chat":
                video = FSInputFile(result_path)
                await callback.message.answer_video(
                    video=video,
                    caption=(
                        f"🎬 <b>Сниппет {idx}/{count} готов! ({int(end_time - start_time)}с)</b>\n"
                        f"🎯 <b>Припев:</b> {chorus_info_str}\n"
                        f"📹 <b>Футаж:</b> {safe_foot}\n"
                        f"🎨 <b>Стиль:</b> {rand_style.upper()} | 🎬 <b>Фильтр:</b> {rand_filter.upper()}\n"
                        f"🎵 {safe_title}"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_snippet_action_keyboard(temp_id)
                )


        except Exception as err:
            logger.error(f"Ошибка рендеринга сниппета {idx}: {err}")
            safe_err = html.escape(str(err))
            await callback.message.answer(f"❌ Ошибка рендеринга сниппета {idx}: {safe_err}")

    # 6. Если выбрана выгрузка одним ZIP-архивом
    if delivery_mode == "zip" and rendered_paths:
        await status_msg.edit_text(
            f"📦 <b>Упаковка {len(rendered_paths)} сниппетов в ZIP-архив...</b>",
            parse_mode="HTML"
        )
        zip_filename = f"snippets_batch_{callback.from_user.id}_{int(loop.time())}.zip"
        zip_path = config.OUTPUT_DIR / zip_filename

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for idx, (f_path, f_name, style, filter_name) in enumerate(rendered_paths, 1):
                archive_name = f"snippet_{idx}_{int(end_time-start_time)}s_{filter_name}.mp4"
                zip_file.write(f_path, arcname=archive_name)

        zip_size_mb = round(zip_path.stat().st_size / (1024 * 1024), 1)
        await callback.message.answer(
            f"📦 <b>Пакетный ZIP-архив успешно сгенерирован и сохранен!</b>\n\n"
            f"🎵 <b>Трек:</b> {safe_title}\n"
            f"⏱ <b>Количество сниппетов:</b> {len(rendered_paths)} шт. ({int(end_time - start_time)}с)\n"
            f"💾 <b>Размер архива:</b> <code>{zip_size_mb} MB</code>\n\n"
            f"📁 <b>Локальный путь к архиву на ПК:</b>\n"
            f"<code>{zip_path}</code>",
            parse_mode="HTML",
            reply_markup=get_after_media_keyboard(callback.from_user.id)
        )




    # 7. Завершение пакетного рендеринга
    await status_msg.edit_text(
        f"🎉 <b>Пакетная генерация завершена!</b>\n\n"
        f"🎵 <b>Трек:</b> {safe_title}\n"
        f"⏱ <b>Длительность сниппетов:</b> <code>{int(end_time - start_time)} сек</code>\n"
        f"🎯 <b>Припев:</b> <code>{chorus_info_str}</code>\n"
        f"✅ Успешно создано роликов: <b>{len(rendered_paths)} шт.</b>\n\n"
        f"Готовый материал выслан выше!",
        parse_mode="HTML",
        reply_markup=get_after_media_keyboard(callback.from_user.id)
    )

@router.callback_query(F.data.startswith("start_pack_30:"))
async def cb_start_pack_30(callback: CallbackQuery):
    """Автоматическая сборка 30 роликов на неделю (Auto-Channel Content Pack)."""
    await callback.answer("🚀 Запуск контент-пака из 30 роликов...")
    footages = db.get_all_footages()
    tracks = db.get_all_tracks()
    
    if not footages or not tracks:
        await callback.answer("❌ Недостаточно треков или видеофутажей в базе!", show_alert=True)
        return

    status_msg = await safe_edit_or_answer(
        callback,
        f"🚀 <b>Запущена авто-сборка контент-пака на 30 роликов!</b>\n\n"
        f"🎵 <b>База треков:</b> {len(tracks)} шт.\n"
        f"📹 <b>База футажей:</b> {len(footages)} шт.\n"
        f"⏱ <b>Статус:</b> Нейросетевой анализ припевов и генерация субтитров (MrBeast / Hormozi)...\n"
        f"📊 <b>Прогресс:</b> 0/30 готов(о)"
    )

    loop = asyncio.get_running_loop()
    SUBTITLE_STYLES = ['mrbeast', 'hormozi', 'tiktok', 'neon', 'minimal', 'stroke']
    VIDEO_FILTERS = ['none', 'vhs', 'cyberpunk', 'bw', 'warm_cinematic']
    
    rendered_paths = []
    
    for idx in range(1, 31):
        track = random.choice(tracks)
        foot = random.choice(footages)
        style = random.choice(SUBTITLE_STYLES)
        fil = random.choice(VIDEO_FILTERS)
        dur = random.choice([15.0, 20.0, 25.0])
        
        await status_msg.edit_text(
            f"🚀 <b>Генерация контент-пака ({idx}/30 роликов)</b>\n\n"
            f"🎵 <b>Трек:</b> {track['title']}\n"
            f"🎨 <b>Стиль:</b> <code>{style.upper()}</code> | 🎬 <b>Фильтр:</b> <code>{fil.upper()}</code>\n"
            f"⏳ <b>Статус:</b> Рендеринг видео 9:16...\n"
            f"📊 <b>Прогресс:</b> {idx - 1}/30 готов(о)",
            parse_mode="HTML"
        )
        
        chorus = await loop.run_in_executor(None, detect_chorus, track['file_path'], dur)
        out_name = f"pack30_{callback.from_user.id}_{idx}.mp4"
        
        try:
            res_path = await loop.run_in_executor(
                None,
                render_snippet,
                track['file_path'],
                foot['file_path'],
                chorus.start,
                chorus.end,
                [], # Auto whisper alignment
                out_name,
                True, # 9:16
                style,
                fil,
                True, # Smart crop
                "karaoke",
                "bottom"
            )
            rendered_paths.append((res_path, foot['filename'], style, fil))
        except Exception as err:
            logger.error(f"Ошибка рендеринга ролика #{idx} в паке: {err}")

    # Создаем единый ZIP-архив
    zip_path = config.OUTPUT_DIR / f"AutoChannel_30_Pack_{callback.from_user.id}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for r_path, r_name, _, _ in rendered_paths:
            if Path(r_path).exists():
                zipf.write(r_path, arcname=Path(r_path).name)

    await status_msg.edit_text("📦 <b>Отправка готового архива на 30 роликов в чат...</b>", parse_mode="HTML")
    
    try:
        doc = FSInputFile(str(zip_path))
        await callback.message.answer_document(
            document=doc,
            caption=f"🎉 <b>Ваш готовый контент-пак на 30 роликов готов!</b>\nВсе 30 видео запакованы в ZIP-архив.",
            parse_mode="HTML",
            reply_markup=get_after_media_keyboard(callback.from_user.id)
        )
    except Exception as e:
        await callback.message.answer(
            f"🎉 <b>Контент-пак на 30 роликов успешно создан!</b>\nАрхив сохранен на диске: <code>{zip_path}</code>",
            parse_mode="HTML",
            reply_markup=get_after_media_keyboard(callback.from_user.id)
        )

# --- Обработчики 4 кнопок после создания сниппета ---

@router.callback_query(F.data.startswith("save_snip:"))
async def cb_save_snip(callback: CallbackQuery):
    temp_id = callback.data.split(":")[1]
    data = TEMP_SNIPPETS_CACHE.get(temp_id)
    if not data or not Path(data["file_path"]).exists():
        await callback.answer("❌ Файл сниппета не найден.", show_alert=True)
        return
        
    db.add_saved_video_snippet(title=data["title"], file_path=data["file_path"], duration=data["duration"])
    await callback.answer("✅ Сниппет успешно сохранен в общую базу для ИИ-Инфлюенсеров!", show_alert=True)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Сгенерировать ИИ-Инфлюенсер + Сниппет", callback_data="inf_step1:snippets")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass

@router.callback_query(F.data.startswith("save_and_inf:"))
async def cb_save_and_inf(callback: CallbackQuery):
    await callback.answer("💾 Сохраняю и открываю выбор инфлюенсера...")
    temp_id = callback.data.split(":")[1]
    data = TEMP_SNIPPETS_CACHE.get(temp_id)
    if data and Path(data["file_path"]).exists():
        db.add_saved_video_snippet(title=data["title"], file_path=data["file_path"], duration=data["duration"])
    
    from bot.handlers.start import start_influencer_wizard_with_snippet
    await start_influencer_wizard_with_snippet(callback, data["file_path"] if data else None)

@router.callback_query(F.data.startswith("cont_inf:"))
async def cb_cont_inf(callback: CallbackQuery):
    await callback.answer("⏩ Открываю выбор инфлюенсера без сохранения...")
    temp_id = callback.data.split(":")[1]
    data = TEMP_SNIPPETS_CACHE.get(temp_id)
    
    from bot.handlers.start import start_influencer_wizard_with_snippet
    await start_influencer_wizard_with_snippet(callback, data["file_path"] if data else None)

@router.callback_query(F.data.startswith("del_snip:"))
async def cb_del_snip(callback: CallbackQuery):
    await callback.answer("🗑 Сниппет удален", show_alert=True)
    temp_id = callback.data.split(":")[1]
    data = TEMP_SNIPPETS_CACHE.get(temp_id)
    if data and Path(data["file_path"]).exists():
        try:
            os.remove(data["file_path"])
        except Exception:
            pass
    try:
        await callback.message.delete()
    except Exception:
        pass

# --- Обработчик А/Б Теста и Мем-Фабрики ---

@router.callback_query(F.data.startswith("ab_test_pack:"))
async def cb_ab_test_pack(callback: CallbackQuery):
    await callback.answer("🧪 Запуск А/Б тестирования 4 вирусных концептов...")
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])

    status_msg = await safe_edit_or_answer(
        callback,
        f"🧪 <b>Генерация 4 вирусных концептов для А/Б теста...</b>\n\n"
        f"1. Концепт А (Драйв / Авто / MrBeast 50/50)\n"
        f"2. Концепт Б (Вирус / Город / Hormozi 70/30)\n"
        f"3. Концепт В (Кино Ч/Б / Неон 30/70)\n"
        f"4. Концепт Г (Аватар / Circle Overlay)\n\n"
        f"⏳ Рендеринг роликов..."
    )

    footages = db.get_all_footages()
    influencers = db.get_all_influencers()

    if not footages or not influencers:
        await status_msg.edit_text("❌ Недостаточно футажей или ИИ-инфлюенсеров в базе!")
        return

    if item_type == "segment":
        seg = db.get_audio_segment(item_id)
        if not seg:
            await status_msg.edit_text("❌ Отрезок не найден.")
            return
        track_id = db.add_track(title=seg['name'], artist="Segment", file_path=seg['file_path'], duration=seg['duration'])
        audio_dur = seg['duration']
        audio_file_path = seg['file_path']
    else:
        tr = db.get_track(item_id)
        if not tr:
            await status_msg.edit_text("❌ Трек не найден.")
            return
        track_id = tr['id']
        audio_dur = tr.get('duration') or 20.0
        audio_file_path = tr['file_path']

    target_dur = min(audio_dur, 20.0)

    configs = [
        {"name": "Версия_А_Драйв_50x50", "cat": "cars", "style": "mrbeast", "filter": "none", "layout": "split50"},
        {"name": "Версия_Б_Вирус_70x30", "cat": "city", "style": "hormozi", "filter": "none", "layout": "split70_top"},
        {"name": "Версия_В_Кино_30x70", "cat": "all", "style": "neon", "filter": "bw", "layout": "split30_top"},
        {"name": "Версия_Г_Аватар_Circle", "cat": "all", "style": "tiktok", "filter": "none", "layout": "circle_overlay"}
    ]

    from services.video_engine import render_snippet, render_split_screen_reaction
    from services.whisper_transcriber import transcribe_audio_segment
    from services.ai_post_generator import generate_social_post_caption
    
    loop = asyncio.get_running_loop()

    # Предварительная однократная транскрипция для экономии времени рендеринга
    await status_msg.edit_text("🧪 <b>А/Б Тест: ИИ-анализ вокала и слов песни...</b>", parse_mode="HTML")
    cached_lyrics = await loop.run_in_executor(
        None,
        transcribe_audio_segment,
        audio_file_path,
        0.0,
        target_dur
    )

    tr_info = db.get_track(track_id)
    caption_post = generate_social_post_caption(tr_info['title'] if tr_info else "Snippet", tr_info.get('artist', '') if tr_info else '')

    for idx, cfg in enumerate(configs, 1):
        clean_name = cfg['name'].replace('_', ' ')
        await status_msg.edit_text(
            f"🧪 <b>Генерация 4 вирусных концептов для А/Б теста...</b>\n\n"
            f"⏳ <b>Рендеринг [{idx}/4]:</b> {clean_name}\n"
            f"📊 Прогресс: {idx - 1}/4 готово",
            parse_mode="HTML"
        )

        inf = random.choice(influencers)
        cat_foots = db.get_all_footages(category=cfg["cat"]) or footages
        foot = random.choice(cat_foots)
        
        out_name = f"AB_{cfg['name']}_{uuid.uuid4().hex[:4]}.mp4"
        temp_snip = f"temp_snip_ab_{idx}_{uuid.uuid4().hex[:4]}.mp4"
        
        snip_p = await loop.run_in_executor(
            None,
            render_snippet,
            audio_file_path,
            foot['file_path'],
            0.0,
            target_dur,
            cached_lyrics,
            temp_snip,
            True,
            cfg['style'],
            cfg['filter'],
            True,
            "word",
            "bottom"
        )

        res_p = await loop.run_in_executor(
            None,
            render_split_screen_reaction,
            snip_p,
            inf['video_path'],
            out_name,
            cfg['layout'],
            target_dur
        )

        try:
            Path(snip_p).unlink(missing_ok=True)
        except Exception:
            pass

        # Отправляем готовый ролик в чат сразу, не заставляя ждать остальные
        try:
            video = FSInputFile(res_p)
            await callback.message.answer_video(
                video=video,
                caption=f"🧪 <b>А/Б Концепт [{idx}/4]: {clean_name}</b>\n\n{caption_post}",
                parse_mode="HTML",
                request_timeout=300
            )
        except Exception as send_err:
            logger.warning(f"Ошибка отправки video #{idx} ({send_err}), пробую через document...")
            try:
                doc = FSInputFile(res_p)
                await callback.message.answer_document(
                    document=doc,
                    caption=f"🧪 <b>А/Б Концепт [{idx}/4]: {clean_name}</b>\n\n{caption_post}",
                    parse_mode="HTML",
                    request_timeout=300
                )
            except Exception as doc_err:
                logger.error(f"Не удалось отправить файл концепта #{idx}: {doc_err}")

    await status_msg.edit_text("🎉 <b>Все 4 концепта для А/Б теста успешно сгенерированы и отправлены в чат!</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("meme_factory_run:"))
async def cb_meme_factory_run(callback: CallbackQuery):
    await callback.answer("🤡 Запуск Мем-Фабрики...")
    parts = callback.data.split(":")
    item_type = parts[1]
    item_id = int(parts[2])

    status_msg = await safe_edit_or_answer(
        callback,
        f"🤡 <b>Мем-Фабрика: Сборка вирусной реакции...</b>\n⏳ Идет генерация роликов..."
    )

    meme_foots = db.get_all_footages(category="memes")
    if not meme_foots:
        meme_foots = db.get_all_footages(category="hooks") or db.get_all_footages()

    influencers = db.get_all_influencers()
    if not meme_foots or not influencers:
        await status_msg.edit_text("❌ Недостаточно мемов или ИИ-инфлюенсеров.")
        return

    if item_type == "segment":
        seg = db.get_audio_segment(item_id)
        track_id = db.add_track(title=seg['name'], artist="Meme Segment", file_path=seg['file_path'], duration=seg['duration'])
        audio_dur = seg['duration']
        audio_file_path = seg['file_path']
    else:
        tr = db.get_track(item_id)
        track_id = tr['id']
        audio_dur = tr.get('duration') or 15.0
        audio_file_path = tr['file_path']

    target_dur = min(audio_dur, 15.0)

    from services.video_engine import render_snippet, render_split_screen_reaction
    inf = random.choice(influencers)
    foot = random.choice(meme_foots)

    out_name = f"meme_reaction_{uuid.uuid4().hex[:6]}.mp4"
    temp_snip = f"temp_snip_meme_{uuid.uuid4().hex[:4]}.mp4"

    loop = asyncio.get_running_loop()
    snip_p = await loop.run_in_executor(
        None,
        render_snippet,
        audio_file_path,
        foot['file_path'],
        0.0,
        target_dur,
        [],
        temp_snip,
        True,
        "mrbeast",
        "none",
        True,
        "word",
        "bottom"
    )

    res_p = await loop.run_in_executor(
        None,
        render_split_screen_reaction,
        snip_p,
        inf['video_path'],
        out_name,
        "split50",
        target_dur
    )

    from services.ai_post_generator import generate_social_post_caption
    tr_info = db.get_track(track_id)
    caption_post = generate_social_post_caption(tr_info['title'] if tr_info else "Meme", tr_info.get('artist', '') if tr_info else '')

    video = FSInputFile(res_p)
    await callback.message.answer_video(
        video=video,
        caption=f"🤡 <b>Мем-Сниппет Реакция готова!</b>\n\n{caption_post}",
        parse_mode="HTML"
    )

    await callback.message.answer("👋 **Вы вернулись в главное меню.**", parse_mode="Markdown", reply_markup=get_main_keyboard(callback.from_user.id))

