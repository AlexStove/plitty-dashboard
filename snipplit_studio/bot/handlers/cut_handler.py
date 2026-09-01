import os
import re
import json
import asyncio
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from moviepy import AudioFileClip

from database.db import db
import config
from bot.handlers.start import safe_edit_text, cb_list_tracks, cb_list_snippets
from services.lrc_parser import parse_lrc, slice_lyrics

router = Router()
logger = logging.getLogger(__name__)

class CutState(StatesGroup):
    waiting_for_range = State()
    waiting_for_custom_name = State()

def parse_time_to_seconds(val_str: str) -> float:
    val_str = val_str.strip()
    if ":" in val_str:
        parts = val_str.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(val_str)

def parse_time_range(text: str):
    cleaned = re.sub(r'[—–\-,\s]+', ' ', text).strip()
    parts = cleaned.split()
    if len(parts) >= 2:
        try:
            start = parse_time_to_seconds(parts[0])
            end = parse_time_to_seconds(parts[1])
            if 0 <= start < end:
                return start, end
        except Exception:
            pass
    return None, None

@router.callback_query(F.data.startswith("cut_track:"))
async def cb_cut_track(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    track_id = int(callback.data.split(":")[1])
    track = db.get_track(track_id)
    if not track or not Path(track['file_path']).exists():
        await callback.answer("❌ Файл трека не найден", show_alert=True)
        return

    await state.set_state(CutState.waiting_for_range)
    await state.update_data(track_id=track_id)

    duration_str = f"({int(track['duration'])} сек)" if track.get('duration') else ""
    artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']

    text = (
        f"✂️ <b>Ручная обрезка трека:</b>\n"
        f"🎵 <b>{artist_title}</b> <code>{duration_str}</code>\n\n"
        f"Напишите в чат, с какой секунды и по какую секунду вырезать отрезок.\n\n"
        f"📝 <b>Примеры формата:</b>\n"
        f"• <code>15 45</code> — вырезать с 15 по 45 секунду\n"
        f"• <code>00:15 - 00:45</code> — формат минут:секунд\n\n"
        f"Отправьте тайминг прямо в этот чат 👇"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_cut_action")]
    ])

    await safe_edit_text(callback, text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "cancel_cut_action")
async def cb_cancel_cut_action(callback: CallbackQuery, state: FSMContext):
    await callback.answer("❌ Обрезка отменена", show_alert=True)
    await state.clear()
    await cb_list_tracks(callback)

@router.message(CutState.waiting_for_range)
async def process_cut_range(message: Message, state: FSMContext):
    data = await state.get_data()
    track_id = data.get("track_id")
    track = db.get_track(track_id) if track_id else None

    if not track or not Path(track['file_path']).exists():
        await message.answer("❌ Ошибка: исходный трек не найден.")
        await state.clear()
        return

    start_sec, end_sec = parse_time_range(message.text)
    if start_sec is None or end_sec is None:
        await message.answer(
            "⚠️ <b>Неверный формат времени!</b>\n\n"
            "Пожалуйста, отправьте две цифры через пробел или тире.\n"
            "Пример: <code>15 45</code> или <code>00:15 - 00:45</code>",
            parse_mode="HTML"
        )
        return

    track_duration = track.get('duration') or 9999.0
    if end_sec > track_duration:
        end_sec = track_duration

    if start_sec >= end_sec:
        await message.answer("⚠️ Начальная секунда должна быть меньше конечной!")
        return

    status_msg = await message.answer("⏳ <b>Вырезаем указанный отрезок трека...</b>", parse_mode="HTML")

    loop = asyncio.get_running_loop()
    temp_cut_name = f"temp_cut_{message.from_user.id}_{int(loop.time())}.mp3"
    temp_cut_path = config.OUTPUT_DIR / temp_cut_name

    def trim_audio():
        clip = AudioFileClip(track['file_path']).subclipped(start_sec, end_sec)
        clip.write_audiofile(str(temp_cut_path), logger=None)
        clip.close()

    try:
        await loop.run_in_executor(None, trim_audio)
    except Exception as err:
        logger.error(f"Ошибка обрезки аудио: {err}")
        await status_msg.edit_text(f"❌ Ошибка при обрезке аудиофайла: {err}")
        return

    await status_msg.delete()

    cut_duration = int(end_sec - start_sec)
    start_fmt = f"{int(start_sec//60):02d}:{int(start_sec%60):02d}"
    end_fmt = f"{int(end_sec//60):02d}:{int(end_sec%60):02d}"

    artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']
    default_name = f"{artist_title} ({int(start_sec)}s-{int(end_sec)}s)"

    await state.update_data(
        temp_cut_name=temp_cut_name,
        track_id=track_id,
        start_sec=start_sec,
        end_sec=end_sec,
        custom_name=default_name
    )

    audio = FSInputFile(str(temp_cut_path))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_cut:{track_id}:{start_sec}:{end_sec}:{temp_cut_name}"),
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"rename_cut:{temp_cut_name}")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_cut_preview:{temp_cut_name}")
        ]
    ])

    await message.answer_audio(
        audio=audio,
        caption=(
            f"✂️ <b>Вырезанный отрезок ({cut_duration}с):</b>\n"
            f"⏱ Тайминг: <code>{start_fmt} – {end_fmt}</code>\n"
            f"🏷 <b>Название:</b> {default_name}\n\n"
            f"Сохранить этот отрезок или изменить название?"
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("rename_cut:"))
async def cb_rename_cut(callback: CallbackQuery, state: FSMContext):
    """Запрашивает кастомное имя отрезка перед сохранением."""
    await callback.answer()
    temp_cut_name = callback.data.split(":")[1]
    await state.set_state(CutState.waiting_for_custom_name)
    await state.update_data(temp_cut_name=temp_cut_name)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к сохранению", callback_data=f"back_to_preview:{temp_cut_name}")]
    ])
    await safe_edit_text(
        callback,
        "✏️ <b>Введите новое название для сохраненного отрезка:</b>\n\n"
        "Напишите желаемое название прямо в этот чат (например, <code>Крутой припев</code> или <code>Припев #1</code>) 👇",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.message(CutState.waiting_for_custom_name)
async def process_custom_name(message: Message, state: FSMContext):
    """Принимает введенное пользователем название отрезка."""
    new_name = message.text.strip()
    if not new_name:
        await message.answer("⚠️ Название не может быть пустым. Попробуйте еще раз.")
        return

    data = await state.get_data()
    temp_cut_name = data.get("temp_cut_name")
    track_id = data.get("track_id")
    start_sec = data.get("start_sec")
    end_sec = data.get("end_sec")

    await state.update_data(custom_name=new_name)

    temp_cut_path = config.OUTPUT_DIR / temp_cut_name
    if not temp_cut_path.exists():
        await message.answer("❌ Временный файл не найден.")
        await state.clear()
        return

    cut_duration = int(end_sec - start_sec)
    start_fmt = f"{int(start_sec//60):02d}:{int(start_sec%60):02d}"
    end_fmt = f"{int(end_sec//60):02d}:{int(end_sec%60):02d}"

    audio = FSInputFile(str(temp_cut_path))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_cut:{track_id}:{start_sec}:{end_sec}:{temp_cut_name}"),
            InlineKeyboardButton(text="✏️ Изменить еще раз", callback_data=f"rename_cut:{temp_cut_name}")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_cut_preview:{temp_cut_name}")
        ]
    ])

    await message.answer_audio(
        audio=audio,
        caption=(
            f"✂️ <b>Вырезанный отрезок ({cut_duration}с):</b>\n"
            f"⏱ Тайминг: <code>{start_fmt} – {end_fmt}</code>\n"
            f"🏷 <b>Название:</b> {new_name}\n\n"
            f"Сохранить этот отрезок в «Готовые отрезки»?"
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("save_cut:"))
async def cb_save_cut(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    track_id = int(parts[1])
    start_sec = float(parts[2])
    end_sec = float(parts[3])
    temp_cut_name = parts[4]

    data = await state.get_data()
    custom_name = data.get("custom_name")

    temp_cut_path = config.OUTPUT_DIR / temp_cut_name
    track = db.get_track(track_id)
    if not track:
        await callback.answer("❌ Ошибка: трек не найден", show_alert=True)
        return

    if not custom_name:
        artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']
        custom_name = f"{artist_title} ({int(start_sec)}s-{int(end_sec)}s)"

    perm_path = config.MUSIC_DIR / f"segment_{track_id}_{int(start_sec)}_{int(end_sec)}.mp3"

    if temp_cut_path.exists():
        if perm_path.exists():
            perm_path.unlink()
        temp_cut_path.rename(perm_path)

    lyrics_json_str = None
    if track.get('lyrics_path') and Path(track['lyrics_path']).exists():
        try:
            with open(track['lyrics_path'], 'r', encoding='utf-8', errors='ignore') as f:
                parsed_lyrics = parse_lrc(f.read())
                if parsed_lyrics:
                    sliced = slice_lyrics(parsed_lyrics, start_sec, end_sec)
                    lyrics_json_str = json.dumps(sliced, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка нарезки субтитров: {e}")

    db.add_audio_segment(
        track_id=track_id,
        name=custom_name,
        file_path=str(perm_path),
        start_time=start_sec,
        end_time=end_sec,
        lyrics_json=lyrics_json_str
    )

    await state.clear()
    await callback.answer(f"✅ Отрезок «{custom_name}» сохранен!", show_alert=True)
    await cb_list_snippets(callback)

@router.callback_query(F.data.startswith("cancel_cut_preview:"))
async def cb_cancel_cut_preview(callback: CallbackQuery, state: FSMContext):
    await callback.answer("❌ Отрезок удален", show_alert=True)
    await state.clear()
    temp_cut_name = callback.data.split(":")[1]
    temp_cut_path = config.OUTPUT_DIR / temp_cut_name
    if temp_cut_path.exists():
        try:
            temp_cut_path.unlink()
        except Exception:
            pass
    await cb_list_tracks(callback)

class EditSegmentLyricsState(StatesGroup):
    waiting_for_segment_lyrics = State()

@router.callback_query(F.data.startswith("edit_seg_lyrics:"))
async def cb_edit_seg_lyrics(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    segment_id = int(callback.data.split(":")[1])
    seg = db.get_audio_segment(segment_id)
    if not seg:
        await callback.answer("❌ Отрезок не найден", show_alert=True)
        return

    await state.set_state(EditSegmentLyricsState.waiting_for_segment_lyrics)
    await state.update_data(editing_segment_id=segment_id)

    current_lines = []
    if seg.get('lyrics_json'):
        try:
            parsed = json.loads(seg['lyrics_json'])
            current_lines = [item['text'] for item in parsed if 'text' in item]
        except Exception:
            pass

    preview_str = ""
    if current_lines:
        preview_str = "<b>Текущие субтитры отрезка:</b>\n" + "\n".join([f"{idx}. {l}" for idx, l in enumerate(current_lines, 1)]) + "\n\n"
    else:
        preview_str = "<i>Субтитры для этого отрезка пока отсутствуют.</i>\n\n"

    text = (
        f"✏️ <b>Редактирование субтитров отрезка:</b>\n"
        f"🎵 <b>{seg['name']}</b> (<code>{seg['duration']:.1f} сек</code>)\n\n"
        f"{preview_str}"
        f"Отправьте новый текст субтитров строками прямо в этот чат!\n"
        f"<i>Строки будут автоматически синхронизированы по вокалу!</i> 👇"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="list_snippets")]
    ])

    await safe_edit_text(callback, text, parse_mode="HTML", reply_markup=kb)

@router.message(EditSegmentLyricsState.waiting_for_segment_lyrics)
async def process_segment_lyrics_text(message: Message, state: FSMContext):
    data = await state.get_data()
    segment_id = data.get("editing_segment_id")
    seg = db.get_audio_segment(segment_id) if segment_id else None

    if not seg or not message.text:
        await message.answer("❌ Ошибка: отрезок не найден или текст пуст.")
        await state.clear()
        return

    lyrics_text = message.text.strip()
    from services.lrc_parser import parse_lrc, parse_txt_fallback

    parsed_lyrics = parse_lrc(lyrics_text, seg['duration'])
    if not parsed_lyrics:
        parsed_lyrics = parse_txt_fallback(lyrics_text, seg['duration'])

    lyrics_json_str = json.dumps(parsed_lyrics, ensure_ascii=False)
    db.update_audio_segment_lyrics(segment_id, lyrics_json_str)

    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Авторендеринг сниппетов", callback_data=f"fast_batch_menu:segment:{segment_id}")],
        [InlineKeyboardButton(text="🎭 ИИ-Инфлюенсер + Сниппет", callback_data="inf_step1:live_snippet")],
        [InlineKeyboardButton(text="🔙 К списку отрезков", callback_data="list_snippets")]
    ])

    await message.answer(
        f"✅ <b>Субтитры отрезка успешно сохранены!</b>\n\n"
        f"🎵 <b>Отрезок:</b> {seg['name']}\n"
        f"📝 <b>Количество строк:</b> {len(parsed_lyrics)} шт.\n\n"
        f"Все новые видеоролики и сниппеты с этим отрезком будут использовать ваши отредактированные субтитры! 🚀",
        parse_mode="HTML",
        reply_markup=kb
    )

