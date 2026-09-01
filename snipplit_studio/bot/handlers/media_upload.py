import os
import sys
import re
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, Document, Audio, Video, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from moviepy import AudioFileClip, VideoFileClip



sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database.db import db
import config
from services.downloader import Downloader, fetch_auto_lyrics
from services.metadata_extractor import clean_track_artist_title
from bot.keyboards import get_after_upload_keyboard, get_after_media_keyboard

router = Router()
downloader = Downloader(config.MUSIC_DIR)

# Регулярные выражения для ссылок
LINK_REGEX = r'(https?://[^\s]+)'

def clean_filename(filename: str) -> str:
    """Удаляет недопустимые символы из имени файла."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

@router.message(F.audio)
async def handle_audio_upload(message: Message):
    """Обработка прямой загрузки аудио-файлов."""
    audio: Audio = message.audio
    raw_title = audio.title or audio.file_name or "Unknown Title"
    raw_artist = audio.performer or "Unknown Artist"
    
    status_msg = await message.answer("📥 Скачиваю и обрабатываю аудиофайл...")
    
    try:
        # Предварительное имя файла
        temp_filename = f"audio_{audio.file_unique_id}.mp3"
        dest_path = config.MUSIC_DIR / temp_filename

        # Скачиваем файл из Telegram
        file_info = await message.bot.get_file(audio.file_id)
        await message.bot.download_file(file_info.file_path, str(dest_path))

        # Извлекаем и очищаем реального артиста и название из ID3/имени
        artist, title = clean_track_artist_title(raw_artist, raw_title, str(dest_path))
        
        # Получаем длительность через MoviePy
        duration = 0.0
        try:
            clip = AudioFileClip(str(dest_path))
            duration = clip.duration
            clip.close()
        except Exception as e:
            print(f"Ошибка при чтении метаданных аудио: {e}")
            duration = float(audio.duration or 0)
            
        # Добавляем временную запись трека для резки
        track_id = db.add_track(
            title=title,
            artist=artist,
            file_path=str(dest_path),
            duration=duration,
            source="upload"
        )
        
        display_name = f"{artist} - {title}" if artist != "Unknown Artist" else title
        
        # Автоматически вызываем интерфейс резки отрезка
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🤖 Авто-припев (Librosa AI)", callback_data=f"fast_batch_menu:track:{track_id}"),
                InlineKeyboardButton(text="✂️ Вырезать вручную", callback_data=f"cut_track:{track_id}")
            ],
            [
                InlineKeyboardButton(text="📝 Добавить текст песни", callback_data=f"add_lyrics:{track_id}")
            ]
        ])

        await status_msg.edit_text(
            f"🎵 <b>Аудио загружено:</b> {display_name} (<code>{int(duration)} сек</code>)\n\n"
            f"✂️ <b>Согласно вашим настройкам, полные треки не сохраняются напрямую в базу.</b>\n"
            f"Выберите 15–30 секунд для сохранения отрезка в базу:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при загрузке аудио: {e}")


@router.message(F.video)
async def handle_video_upload(message: Message):
    """Обработка прямой загрузки видео-футажей."""
    video: Video = message.video
    
    # Очищаем имя файла
    filename = f"footage_{video.file_unique_id}.mp4"
    dest_path = config.FOOTAGE_DIR / filename
    
    status_msg = await message.answer("📥 Сохраняю видеофутаж...")
    
    try:
        file_info = await message.bot.get_file(video.file_id)
        await message.bot.download_file(file_info.file_path, str(dest_path))
        
        # Получаем параметры через MoviePy
        width, height, duration = 0, 0, 0.0
        try:
            clip = VideoFileClip(str(dest_path))
            duration = clip.duration
            width, height = clip.size
            clip.close()
        except Exception as e:
            print(f"Ошибка при чтении метаданных видео: {e}")
            width = video.width
            height = video.height
            duration = float(video.duration)
            
        from main import detect_footage_category
        category = detect_footage_category(filename)

        # Добавляем в БД
        footage_id = db.add_footage(
            filename=filename,
            file_path=str(dest_path),
            duration=duration,
            width=width,
            height=height,
            category=category
        )

        
        await status_msg.edit_text(
            f"✅ **Видеофутаж добавлен в базу!**\n\n"
            f"📹 **Имя:** {filename}\n"
            f"⏱ **Длительность:** {int(duration)} сек\n"
            f"📐 **Разрешение:** {width}x{height}\n"
            f"🆔 ID футажа: `{footage_id}`",
            reply_markup=get_after_upload_keyboard(message.from_user.id)
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при загрузке видео: {e}")

@router.message(F.document)
async def handle_document_upload(message: Message):
    """Обработка файлов документов (видео без сжатия, аудио, .lrc)."""
    doc: Document = message.document
    filename = doc.file_name.lower()
    
    # 1. Если это файл субтитров LRC
    if filename.endswith('.lrc') or filename.endswith('.txt'):
        status_msg = await message.answer("📥 Обрабатываю файл субтитров...")
        try:
            # Получаем последний добавленный трек
            tracks = db.get_all_tracks()
            if not tracks:
                await status_msg.edit_text("❌ В базе нет треков. Сначала загрузите аудиофайл или отправьте ссылку на трек!")
                return
                
            last_track = tracks[0]
            
            # Сохраняем файл субтитров с исходным расширением (.lrc или .txt)
            ext = '.txt' if filename.endswith('.txt') else '.lrc'
            lrc_filename = f"lyrics_{last_track['id']}{ext}"
            dest_path = config.DOWNLOADS_DIR / "music" / lrc_filename
            
            file_info = await message.bot.get_file(doc.file_id)
            await message.bot.download_file(file_info.file_path, str(dest_path))
            
            # Обновляем инфо в БД
            db.update_track_lyrics(last_track['id'], str(dest_path))
            
            artist_str = f"{last_track['artist']} - " if last_track['artist'] else ""
            await status_msg.edit_text(
                f"✅ **Субтитры успешно привязаны!**\n\n"
                f"🎵 **Трек:** {artist_str}{last_track['title']}\n"
                f"📝 **Файл:** {doc.file_name}",
                reply_markup=get_after_upload_keyboard(message.from_user.id)
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка при привязке субтитров: {e}")
            
    # 2. Если это видеофайл как документ
    elif filename.endswith(('.mp4', '.mov', '.avi', '.mkv')):
        status_msg = await message.answer("📥 Сохраняю видеофутаж из документа...")
        try:
            safe_name = clean_filename(doc.file_name)
            dest_path = config.FOOTAGE_DIR / f"footage_{doc.file_unique_id}_{safe_name}"
            
            file_info = await message.bot.get_file(doc.file_id)
            await message.bot.download_file(file_info.file_path, str(dest_path))
            
            # Получаем параметры видео
            width, height, duration = 0, 0, 0.0
            try:
                clip = VideoFileClip(str(dest_path))
                duration = clip.duration
                width, height = clip.size
                clip.close()
            except Exception as e:
                print(f"Ошибка чтения метаданных: {e}")
                
            from main import detect_footage_category
            category = detect_footage_category(doc.file_name)

            footage_id = db.add_footage(
                filename=doc.file_name,
                file_path=str(dest_path),
                duration=duration,
                width=width,
                height=height,
                category=category
            )

            
            await status_msg.edit_text(
                f"✅ **Видеофутаж добавлен в базу!**\n\n"
                f"📹 **Имя:** {doc.file_name}\n"
                f"⏱ **Длительность:** {int(duration)} сек\n"
                f"🆔 ID футажа: `{footage_id}`",
                reply_markup=get_after_upload_keyboard(message.from_user.id)
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка при сохранении видео-документа: {e}")
            
    # 3. Если это аудиофайл как документ
    elif filename.endswith(('.mp3', '.m4a', '.wav')):
        status_msg = await message.answer("📥 Сохраняю аудиофайл из документа...")
        try:
            safe_name = clean_filename(doc.file_name)
            dest_path = config.MUSIC_DIR / f"music_{doc.file_unique_id}_{safe_name}"
            
            file_info = await message.bot.get_file(doc.file_id)
            await message.bot.download_file(file_info.file_path, str(dest_path))
            
            # Читаем метаданные
            duration = 0.0
            try:
                clip = AudioFileClip(str(dest_path))
                duration = clip.duration
                clip.close()
            except Exception as e:
                print(f"Ошибка чтения метаданных: {e}")
                
            artist, title = clean_track_artist_title("", os.path.splitext(doc.file_name)[0], str(dest_path))
            
            track_id = db.add_track(
                title=title,
                artist=artist,
                file_path=str(dest_path),
                duration=duration,
                source="upload"
            )

            
            await status_msg.edit_text(
                f"✅ **Трек успешно добавлен в базу!**\n\n"
                f"🎵 **Название:** {artist} - {title}\n"
                f"⏱ **Длительность:** {int(duration)} сек\n"
                f"🆔 ID трека: `{track_id}`",
                reply_markup=get_after_upload_keyboard(message.from_user.id)
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка при сохранении аудио-документа: {e}")
    else:
        await message.answer("❓ Неподдерживаемый формат документа. Пришлите MP3, MP4 или LRC файл.")

@router.message(F.text & F.text.regexp(LINK_REGEX))
async def handle_link_download(message: Message):
    """Обработка текстовых сообщений со ссылками на музыку или видеофутажи."""
    urls = re.findall(LINK_REGEX, message.text)
    if not urls:
        return
        
    url = urls[0]
    
    # 1. Проверяем, является ли ссылка видеоссылкой (TikTok, Shorts, Reels, VK, Pinterest)
    is_video_link = any(domain in url.lower() for domain in [
        'tiktok.com', 'vt.tiktok.com', '/shorts/', 'instagram.com/reel', 
        'instagram.com/p', 'vk.com/video', 'vk.com/clip', 'pinterest.com', 'pin.it'
    ])
    
    if is_video_link:
        status_msg = await message.answer("🔗 Обнаружена видеоссылка (TikTok/Shorts/Reels). Скачиваю видеофутаж...")
        try:
            foot_info = downloader.download_footage_by_link(url)
            from main import detect_footage_category
            category = detect_footage_category(foot_info["filename"])

            footage_id = db.add_footage(
                filename=foot_info["filename"],
                file_path=foot_info["file_path"],
                duration=foot_info["duration"],
                width=foot_info["width"],
                height=foot_info["height"],
                category=category
            )

            await status_msg.edit_text(
                f"✅ **Видеофутаж успешно скачан и добавлен в базу!**\n\n"
                f"📹 **Название:** {foot_info['filename']}\n"
                f"⏱ **Длительность:** {int(foot_info['duration'])} сек\n"
                f"📐 **Разрешение:** {foot_info['width']}x{foot_info['height']}\n"
                f"🆔 ID футажа: `{footage_id}`",
                reply_markup=get_after_upload_keyboard(message.from_user.id)
            )
            return
        except Exception as err:
            await status_msg.edit_text(f"❌ Ошибка скачивания видеофутажа по ссылке:\n{err}")
            return

    # 2. Скачивание аудиофайла
    status_msg = await message.answer("🔗 Обнаружена музыкальная ссылка. Начинаю скачивание трека в базу...")
    
    try:
        yandex_token = os.getenv("YANDEX_MUSIC_TOKEN", None)
        info = downloader.download_by_link(url, yandex_token=yandex_token, user_text=message.text)

        
        track_id = db.add_track(
            title=info["title"],
            artist=info["artist"],
            file_path=info["file_path"],
            duration=info["duration"],
            source=info["source"],
            source_url=info["source_url"]
        )
        
        lyrics_note = ""
        lrc_text = fetch_auto_lyrics(info["artist"], info["title"])
        if lrc_text:
            lrc_path = config.MUSIC_DIR / f"lyrics_{track_id}.lrc"
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lrc_text)
            db.update_track_lyrics(track_id, str(lrc_path))
            lyrics_note = "\n📝 **Субтитры:** найдены и привязаны с таймингами! ✨"
        
        display_name = f"{info['artist']} - {info['title']}" if info['artist'] != "Unknown Artist" else info['title']
        
        await status_msg.edit_text(
            f"✅ **Трек успешно скачан и добавлен в базу!**\n\n"
            f"🎵 **Название:** {display_name}\n"
            f"⏱ **Длительность:** {int(info['duration'])} сек\n"
            f"🌍 **Источник:** {info['source'].upper()}\n"
            f"🆔 ID трека: `{track_id}`"
            f"{lyrics_note}",
            reply_markup=get_after_media_keyboard(message.from_user.id, track_id=track_id)
        )

        # Отправляем прослушиваемый MP3-аудиофайл прямо в чат Telegram
        if Path(info["file_path"]).exists():
            try:
                audio_file = FSInputFile(info["file_path"])
                await message.answer_audio(
                    audio=audio_file,
                    caption=f"🎵 {display_name}",
                    reply_markup=get_after_media_keyboard(message.from_user.id, track_id=track_id)
                )
            except Exception as send_err:
                print(f"[!] Не удалось отправку аудиофайла в чат: {send_err}")

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при скачивании по ссылке:\n{e}")

class AddLyricsState(StatesGroup):
    waiting_for_text = State()

@router.callback_query(F.data.startswith("add_lyrics:"))
async def cb_add_lyrics(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    track_id = int(callback.data.split(":")[1])
    track = db.get_track(track_id)
    if not track:
        await callback.answer("❌ Трек не найден", show_alert=True)
        return
        
    await state.set_state(AddLyricsState.waiting_for_text)
    await state.update_data(track_id=track_id)
    
    artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']
    
    await callback.message.answer(
        f"📝 <b>Добавление текста песни:</b>\n"
        f"🎵 <b>{artist_title}</b>\n\n"
        f"Отправьте текст песни прямо в этот чат!\n"
        f"Вы можете прислать обычный текст (куплетами/строками) или файл <code>.lrc</code> с готовыми таймингами.\n\n"
        f"<i>Нейросеть Whisper AI автоматически проанализирует вокал и выровняет слова по звуку!</i> 👇",
        parse_mode="HTML"
    )

@router.message(AddLyricsState.waiting_for_text)
async def process_custom_lyrics_text(message: Message, state: FSMContext):
    data = await state.get_data()
    track_id = data.get("track_id")
    track = db.get_track(track_id) if track_id else None
    
    if not track or not message.text:
        await message.answer("❌ Ошибка: трек не найден или текст пуст.")
        await state.clear()
        return
        
    status_msg = await message.answer("⏳ <b>Сохраняем текст песни и выравниваем субтитры по вокалу (Whisper AI)...</b>", parse_mode="HTML")
    
    lyrics_text = message.text.strip()
    lrc_path = config.MUSIC_DIR / f"lyrics_{track_id}.lrc"
    
    with open(lrc_path, "w", encoding="utf-8") as f:
        f.write(lyrics_text)
        
    db.update_track_lyrics(track_id, str(lrc_path))
    await state.clear()
    
    artist_title = f"{track['artist']} - {track['title']}" if track.get('artist') else track['title']
    await status_msg.edit_text(
        f"✅ <b>Текст песни успешно привязан!</b>\n\n"
        f"🎵 <b>Трек:</b> {artist_title}\n"
        f"📝 <b>Статус:</b> Субтитры сохранены. При автогенерации сниппетов нейросеть Whisper AI проведет точное выравнивание караоке!",
        parse_mode="HTML",
        reply_markup=get_after_media_keyboard(message.from_user.id, track_id=track_id)
    )

