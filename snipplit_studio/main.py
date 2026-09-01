import asyncio
import logging
import os
import uuid
import sys
import json
from pathlib import Path

from typing import List, Dict, Any, Optional, Union

import uvicorn
import aiofiles
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import FSInputFile

# Добавляем корневой путь в sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

# Настройка логирования в файл и консоль
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "bot.log"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("tg_video_bot")

import config
from database.db import db
from services.lrc_parser import parse_lrc, parse_txt_fallback
from services.video_engine import render_snippet
from bot.handlers import start, media_upload, batch_render, cut_handler

# --- Инициализация Telegram бот с увеличенным таймаутом (300с) для загрузки видео ---
bot_session = AiohttpSession(timeout=300.0)
bot = Bot(token=config.BOT_TOKEN, session=bot_session)
dp = Dispatcher()
dp.include_router(start.router)
dp.include_router(media_upload.router)
dp.include_router(batch_render.router)
dp.include_router(cut_handler.router)

# --- Инициализация FastAPI ---
app = FastAPI(title="Snippet Maker Mini App API")

# Настройка CORS для локального тестирования
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модели Pydantic для API
class LyricItem(BaseModel):
    start: float
    end: float
    text: str

class TrackMetadataUpdate(BaseModel):
    title: str
    artist: str

class RenderRequest(BaseModel):
    track_id: int
    segment_id: Optional[int] = None
    footage_id: Union[int, str]
    start_time: float
    end_time: float
    lyrics: List[LyricItem]
    subtitle_style: str = "tiktok"
    video_filter: str = "none"
    remove_watermark: bool = True
    subtitle_mode: str = "phrase"
    subtitle_position: str = "bottom"
    user_id: Optional[int] = 0
class InfluencerPackRequest(BaseModel):
    influencer_ids: List[int]
    format: str = "hook"
    count_per_inf: int = 1
    duration: float = 20.0
    snippet_id: Optional[Union[int, str]] = None
    user_id: Optional[int] = 0


def sync_local_files():
    """Сканирует папки downloads/music и downloads/footages и автоматически добавляет новые файлы в БД."""
    from moviepy import AudioFileClip, VideoFileClip
    
    # Синхронизация музыки
    try:
        for file in config.MUSIC_DIR.glob("*"):
            if file.suffix.lower() in ['.mp3', '.m4a', '.wav']:
                # Проверяем, есть ли уже в базе по имени файла
                exists = False
                for track in db.get_all_tracks():
                    if Path(track["file_path"]).name == file.name:
                        exists = True
                        break
                if not exists:
                    duration = 0.0
                    try:
                        clip = AudioFileClip(str(file))
                        duration = clip.duration
                        clip.close()
                    except Exception:
                        pass
                    from services.metadata_extractor import clean_track_artist_title
                    artist, title = clean_track_artist_title("", file.stem, str(file))
                    db.add_track(title, artist, str(file), duration=duration, source="local")


        # Автоматический поиск субтитров для всех треков в БД, у которых ещё нет субтитров
        from services.downloader import fetch_auto_lyrics
        for track in db.get_all_tracks():
            if not track.get("lyrics_path") or not Path(track["lyrics_path"]).exists():
                lrc_text = fetch_auto_lyrics(track["artist"], track["title"])
                if lrc_text:
                    lrc_path = config.MUSIC_DIR / f"lyrics_{track['id']}.lrc"
                    with open(lrc_path, "w", encoding="utf-8") as f:
                        f.write(lrc_text)
                    db.update_track_lyrics(track["id"], str(lrc_path))
                    print(f"[+] Автоматически привязаны субтитры для трека #{track['id']} ({track['artist']} - {track['title']})")
    except Exception as e:
        print(f"Ошибка синхронизации музыки: {e}")

def detect_footage_category(filename: str) -> str:
    fn = filename.lower()
    hooks_kw = ['hook', 'meme', 'joke', 'funny', 'прикол', 'мем', 'хук']
    cars_kw = ['car', 'auto', 'porsche', 'bmw', 'audi', 'mercedes', 'ferrari', 'lamborghini', 'drift', 'drive', 'speed', 'supercar', 'race', 'vehicle', 'wheels', 'машин', 'авто']
def detect_footage_category(file_path: Path) -> str:
    if "hooks" in str(file_path).lower():
        return "hooks"
    fn = file_path.name.lower()
    cars_kw = ['car', 'bmw', 'mercedes', 'audi', 'porsche', 'ferrari', 'lamborghini', 'race', 'drift', 'drive', 'auto', 'авто', 'машин']
    football_kw = ['foot', 'soccer', 'ball', 'goal', 'stadium', 'match', 'football', 'messi', 'ronaldo', 'player', 'спорт', 'футбол']
    fashion_kw = ['fashion', 'style', 'model', 'dress', 'beauty', 'makeup', 'girl', 'hair', 'skin', 'aesthetic', 'lipstick', 'мода', 'стиль', 'бьюти', 'красота']
    city_kw = ['city', 'street', 'tokyo', 'night', 'light', 'neon', 'rain', 'sunset', 'nature', 'город']

    if any(k in fn for k in cars_kw):
        return 'cars'
    if any(k in fn for k in football_kw):
        return 'football'
    if any(k in fn for k in fashion_kw):
        return 'fashion'
    if any(k in fn for k in city_kw):
        return 'city'
    return 'general'

def sync_footages_from_folder():
    """Синхронизирует рекурсивно все футажи и хуки из downloads/footages в БД."""
    try:
        footage_dir = config.FOOTAGE_DIR
        footage_dir.mkdir(parents=True, exist_ok=True)
        
        all_db_paths = set(f["file_path"] for f in db.get_all_footages(category="all"))
        all_db_paths.update(f["file_path"] for f in db.get_all_footages(category="hooks"))
        
        for file in list(footage_dir.rglob("*.mp4")) + list(footage_dir.rglob("*.mov")):
            if str(file) not in all_db_paths:
                cat = detect_footage_category(file)
                db.add_footage(file.name, str(file), duration=5.0, width=720, height=1280, category=cat)
    except Exception as e:
        print(f"Ошибка синхронизации футажей: {e}")

def sync_local_files():
    """Быстрая синхронизация базы данных с файлами на диске."""
    sync_footages_from_folder()
    from services.thumbnail_generator import generate_all_thumbnails_async
    generate_all_thumbnails_async()


# --- API Эндпоинты ---

@app.get("/api/tracks")
async def get_tracks():
    """Получить список отрезков и треков."""
    return db.get_all_tracks()

@app.get("/api/audio_segments")
async def get_audio_segments():
    """Получить список всех сохраненных аудио-отрезков."""
    return db.get_all_audio_segments()

@app.delete("/api/audio_segments/{segment_id}")
async def delete_audio_segment_endpoint(segment_id: int):
    """Удалить сохраненный аудио-отрезок."""
    db.delete_audio_segment(segment_id)
    return {"status": "deleted"}

@app.get("/api/footages")
async def get_footages(category: Optional[str] = None):
    """Получить список всех видеофутажей мгновенно (<1мс)."""
    items = db.get_all_footages(category=category)
    from services.thumbnail_generator import get_footage_thumbnail_url
    valid_items = []
    for item in items:
        if Path(item["file_path"]).exists():
            item["thumb_url"] = get_footage_thumbnail_url(item["file_path"])
            item["file_url"] = get_footage_url(item["file_path"])
            valid_items.append(item)
        else:
            try:
                db.delete_footage(item["id"])
            except Exception:
                pass
    return valid_items





@app.post("/api/footages/{footage_id}/category")
async def update_footage_category_endpoint(footage_id: int, category: str = Query(...)):
    """Обновить категорию видеофутажа."""
    footage = db.get_footage(footage_id)
    if not footage:
        raise HTTPException(status_code=404, detail="Футаж не найден")
    db.update_footage_category(footage_id, category)
    return {"status": "success", "category": category}


@app.get("/api/tracks/{track_id}/lyrics")
async def get_lyrics(track_id: int):
    """Получить распарсенные субтитры для трека."""
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
        
    if not track["lyrics_path"]:
        return []
        
    lyrics_path = Path(track["lyrics_path"])
    if not lyrics_path.exists():
        return []
        
    try:
        async with aiofiles.open(lyrics_path, mode='r', encoding='utf-8') as f:
            content = await f.read()
            
        if lyrics_path.suffix.lower() == '.lrc':
            parsed = parse_lrc(content, track["duration"])
            if parsed:
                return parsed
            # Если в файле с расширением .lrc нет валидных временных меток, парсим как обычный текст
            return parse_txt_fallback(content, track["duration"] or 30.0)
        else:
            duration = track["duration"] or 30.0
            return parse_txt_fallback(content, duration)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка парсинга субтитров: {e}")

@app.post("/api/tracks/{track_id}/transcribe")
async def transcribe_track_endpoint(track_id: int, start_time: float = 0.0, end_time: Optional[float] = None, segment_id: Optional[int] = None):
    """Запустить точное нейросетевое распознавание речи по голосу (Whisper AI)."""
    file_path = None
    if segment_id:
        seg = db.get_audio_segment(segment_id)
        if seg:
            file_path = seg["file_path"]
            start_time = 0.0
            end_time = float(seg["duration"])
            
    if not file_path:
        track = db.get_track(track_id)
        if track:
            file_path = track["file_path"]
            if Path(file_path).name.startswith("segment_"):
                start_time = 0.0

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Аудиофайл не найден на сервере")
        
    loop = asyncio.get_running_loop()
    try:
        from services.whisper_transcriber import transcribe_audio_segment
        lyrics = await loop.run_in_executor(
            None,
            transcribe_audio_segment,
            file_path,
            start_time,
            end_time
        )
        return lyrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка распознавания речи: {e}")

class SaveLyricsRequest(BaseModel):
    lyrics: List[LyricItem]
    segment_id: Optional[int] = None

@app.post("/api/tracks/{track_id}/save_lyrics")
async def save_track_lyrics_endpoint(track_id: int, req: SaveLyricsRequest):
    """Явное сохранение ручного текста субтитров трека или отрезка в БД."""
    lyrics_json = json.dumps([{"start": item.start, "end": item.end, "text": item.text} for item in req.lyrics], ensure_ascii=False)
    if req.segment_id:
        db.update_audio_segment_lyrics(req.segment_id, lyrics_json)
    else:
        lrc_path = config.MUSIC_DIR / f"lyrics_{track_id}.json"
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lyrics_json)
        db.update_track_lyrics(track_id, str(lrc_path))
    return {"status": "ok", "message": "Субтитры успешно сохранены в базе"}

@app.post("/api/tracks/{track_id}/update")
async def update_track(track_id: int, req: TrackMetadataUpdate):
    """Обновить метаданные трека (название и исполнитель)."""
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    db.update_track_metadata(track_id, req.title, req.artist)
    return {"status": "success"}

@app.delete("/api/tracks/{track_id}")
async def delete_track_api(track_id: int):
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    db.delete_track(track_id)
    return {"status": "deleted"}

@app.delete("/api/footages/{footage_id}")
async def delete_footage_api(footage_id: int):
    footage = db.get_footage(footage_id)
    if not footage:
        raise HTTPException(status_code=404, detail="Футаж не найден")
    db.delete_footage(footage_id)
    return {"status": "deleted"}

@app.get("/api/saved_snippets")
@app.get("/api/v1/saved_snippets")
async def get_saved_snippets():
    """Получить список всех сохраненных готовых видео-сниппетов."""
    items = db.get_all_saved_video_snippets()
    valid_items = []
    for item in items:
        if Path(item["file_path"]).exists():
            item["file_url"] = get_footage_url(item["file_path"])
            valid_items.append(item)
        else:
            try:
                db.delete_saved_video_snippet(item["id"])
            except Exception:
                pass
    return valid_items

@app.delete("/api/saved_snippets/{snippet_id}")
@app.delete("/api/v1/saved_snippets/{snippet_id}")
async def delete_saved_snippet_endpoint(snippet_id: int):
    """Удалить сохраненный готовый видео-сниппет."""
    db.delete_saved_video_snippet(snippet_id)
    return {"status": "deleted"}

INFLUENCERS_DATA = [
    {"id": 1, "number": 1, "name": "Karla Jensen", "handle": "@karlajensen", "category": "general", "avatar": "/static/avatars/Karla.png"},
    {"id": 2, "number": 2, "name": "Rosalind Hawthorne", "handle": "@rosalindhawthorne", "category": "general", "avatar": "/static/avatars/Rosalind.png"},
    {"id": 3, "number": 3, "name": "Chloe Mitchell", "handle": "@chloemitchell", "category": "general", "avatar": "/static/avatars/Chloe.png"},
    {"id": 4, "number": 4, "name": "Rafael Nunes", "handle": "@rafaelnunes", "category": "general", "avatar": "/static/avatars/Rafael.png"},
    {"id": 5, "number": 5, "name": "Olivia Finch", "handle": "@oliviafinch", "category": "general", "avatar": "/static/avatars/Olivia.png"},
    {"id": 6, "number": 6, "name": "Hunter Mercer", "handle": "@huntermercer", "category": "general", "avatar": "/static/avatars/Hunter.png"},
    {"id": 7, "number": 7, "name": "Brooklyn Vaughn", "handle": "@brooklynvaughn", "category": "general", "avatar": "/static/avatars/Brooklyn.png"},
    {"id": 8, "number": 8, "name": "Teodor Bratanov", "handle": "@teodorbratanov", "category": "general", "avatar": "/static/avatars/Teodor.png"},
    {"id": 9, "number": 9, "name": "Savannah Prescott", "handle": "@savannahprescott", "category": "general", "avatar": "/static/avatars/file.png"},
    {"id": 10, "number": 10, "name": "Mason Fletcher", "handle": "@masonfletcher", "category": "general", "avatar": "/static/avatars/mason.png"},
    {"id": 11, "number": 11, "name": "Alistair Fraser", "handle": "@alistairfraser", "category": "general", "avatar": "/static/avatars/Alistair.png"},
    {"id": 12, "number": 12, "name": "Bastian Nowak", "handle": "@bastiannowak", "category": "general", "avatar": "/static/avatars/Bastian.png"},
    {"id": 13, "number": 13, "name": "Bram Kowalski", "handle": "@bramkowalski", "category": "general", "avatar": "/static/avatars/Bram.png"},
    {"id": 14, "number": 14, "name": "Callum Hughes", "handle": "@callumhughes", "category": "general", "avatar": "/static/avatars/Callum.png"},
    {"id": 15, "number": 15, "name": "Camille Dubois", "handle": "@camilledubois", "category": "general", "avatar": "/static/avatars/Camille.png"},
    {"id": 16, "number": 16, "name": "Chloe Bennet", "handle": "@chloebennet", "category": "general", "avatar": "/static/avatars/Chloe Bennet.png"},
    {"id": 17, "number": 17, "name": "Cillian Doyle", "handle": "@cilliandoyle", "category": "general", "avatar": "/static/avatars/Cillian.png"},
    {"id": 18, "number": 18, "name": "Jasper Croft", "handle": "@jaspercroft", "category": "general", "avatar": "/static/avatars/Jasper.png"},
    {"id": 19, "number": 19, "name": "Barnaby Finch", "handle": "@barnabyfinch", "category": "general", "avatar": "/static/avatars/Barnaby.png"},
    {"id": 20, "number": 20, "name": "Dalton Pruitt", "handle": "@daltonpruitt", "category": "general", "avatar": "/static/avatars/Dalton.png"},
    {"id": 21, "number": 21, "name": "Delphine Moreau", "handle": "@delphinemoreau", "category": "general", "avatar": "/static/avatars/Delphine.png"},
    {"id": 22, "number": 22, "name": "Desmond Okonkwo-Reyes", "handle": "@desmondreyes", "category": "general", "avatar": "/static/avatars/Desmond.png"},
    {"id": 23, "number": 23, "name": "Dimitri Voss", "handle": "@dimitrivoss", "category": "general", "avatar": "/static/avatars/Dimitri.png"},
    {"id": 24, "number": 24, "name": "Eleanor Croft", "handle": "@eleanorcroft", "category": "general", "avatar": "/static/avatars/Eleanor.png"},
    {"id": 25, "number": 25, "name": "Florence Whitaker", "handle": "@florencewhitaker", "category": "general", "avatar": "/static/avatars/Florence.png"},
    {"id": 26, "number": 26, "name": "Maisie Clarke", "handle": "@maisieclarke", "category": "general", "avatar": "/static/avatars/Maisie.png"},
    {"id": 27, "number": 27, "name": "George Ainsworth", "handle": "@georgeainsworth", "category": "general", "avatar": "/static/avatars/George.png"},
    {"id": 28, "number": 28, "name": "Maia Lin", "handle": "@maialin", "category": "general", "avatar": "/static/avatars/Maia.png"},
    {"id": 29, "number": 29, "name": "Alexis Rivera", "handle": "@alexisrivera", "category": "general", "avatar": "/static/avatars/Alexis.png"},
    {"id": 30, "number": 30, "name": "Priscilla Okafor-Vance", "handle": "@priscillaokafor", "category": "general", "avatar": "/static/avatars/Priscilla.png"}
]

@app.get("/api/influencers")
@app.get("/api/v1/influencers")
async def get_influencers_endpoint():
    """Получить список всех ИИ-Инфлюенсеров с аватарками."""
    return INFLUENCERS_DATA

async def render_task_worker(task_id: str, req: RenderRequest):
    """Фоновая задача для рендеринга видео в отдельном потоке (не блокирует event loop)."""
    db.update_task_status(task_id, "processing")
    
    try:
        track = db.get_track(req.track_id) if req.track_id else None
        if not track:
            all_tracks = db.get_all_tracks()
            if all_tracks:
                import random
                track = random.choice(all_tracks)
        
        if str(req.footage_id).lower() in ["0", "random", "none"]:
            all_footages = db.get_all_footages()
            valid_footages = [f for f in all_footages if Path(f["file_path"]).exists()]
            if not valid_footages:
                raise Exception("В базе данных нет доступных видеофутажей для случайного выбора")
            import random
            footage = random.choice(valid_footages)
        else:
            footage = db.get_footage(int(req.footage_id))
            if not footage:
                all_footages = db.get_all_footages()
                if all_footages:
                    import random
                    footage = random.choice(all_footages)
        
        audio_file_path = track["file_path"] if track else None
        render_start = req.start_time
        render_end = req.end_time

        if req.segment_id:
            seg = db.get_audio_segment(req.segment_id)
            if seg and Path(seg["file_path"]).exists():
                audio_file_path = seg["file_path"]
                render_start = 0.0
                render_end = float(seg["duration"])
        elif audio_file_path and (Path(audio_file_path).name.startswith("segment_") or "segment_" in Path(audio_file_path).name):
            render_start = 0.0
            if req.end_time > req.start_time:
                render_end = req.end_time - req.start_time

        if not audio_file_path or not Path(audio_file_path).exists():
            raise Exception("Файл аудиофайла не найден на сервере")
            
        output_filename = f"snippet_{task_id}.mp4"
        
        # Конвертируем Pydantic-модели субтитров в обычный список словарей
        lyrics_dict = [{"start": item.start, "end": item.end, "text": item.text} for item in req.lyrics]
        
        # Запускаем тяжелый рендеринг в пуле потоков
        loop = asyncio.get_running_loop()
        result_path = await loop.run_in_executor(
            None,
            render_snippet,
            audio_file_path,
            footage["file_path"],
            render_start,
            render_end,
            lyrics_dict,
            output_filename,
            True,  # Вертикальное кадрирование (9:16)
            req.subtitle_style,
            req.video_filter,
            req.remove_watermark,
            req.subtitle_mode,
            req.subtitle_position
        )

        
        # Обновляем статус задачи в БД как завершенный
        db.update_task_status(task_id, "completed", result_path)

        # Автоматически сохраняем готовый сниппет в БД
        try:
            artist_str = f"{track['artist']} - " if track.get('artist') else ""
            snip_title = f"{artist_str}{track['title']} ({int(req.start_time)}-{int(req.end_time)}s)"
            db.add_saved_video_snippet(title=snip_title, file_path=result_path, duration=req.end_time - req.start_time)
        except Exception as save_err:
            print(f"[!] Ошибка сохранения в saved_video_snippets: {save_err}")
        
        # Сохраняем готовый аудио-отрезок для будущей многократной генерации сниппетов
        try:
            snippets_dir = config.MUSIC_DIR / "snippets"
            snippets_dir.mkdir(parents=True, exist_ok=True)
            segment_filename = f"segment_{track['id']}_{int(req.start_time)}_{int(req.end_time)}.mp3"
            segment_path = snippets_dir / segment_filename
            
            if not segment_path.exists():
                from moviepy import AudioFileClip
                ac = AudioFileClip(track["file_path"]).subclipped(req.start_time, req.end_time)
                ac.write_audiofile(str(segment_path), logger=None)
                ac.close()
                
            artist_str = f"{track['artist']} - " if track.get('artist') else ""
            segment_name = f"{artist_str}{track['title']} [{int(req.start_time)}-{int(req.end_time)}s]"
            lyrics_json = json.dumps(lyrics_dict)
            
            db.add_audio_segment(
                track_id=track["id"],
                name=segment_name,
                file_path=str(segment_path),
                start_time=req.start_time,
                end_time=req.end_time,
                lyrics_json=lyrics_json
            )
        except Exception as seg_err:
            print(f"[!] Ошибка сохранения аудио-отрезка: {seg_err}")
        
        # Отправляем видео пользователю в Telegram (если чат доступен)
        try:
            video = FSInputFile(result_path)
            artist_str = f"{track['artist']} - " if track['artist'] else ""
            caption = (
                f"🎬 **Ваш музыкальный сниппет готов!**\n\n"
                f"🎵 Трек: {artist_str}{track['title']}\n"
                f"⏱ Отрезок: {int(req.start_time)} - {int(req.end_time)} сек\n"
                f"🎨 Стиль: {req.subtitle_style.upper()}"
            )
            await bot.send_video(
                chat_id=req.user_id,
                video=video,
                caption=caption,
                parse_mode="Markdown"
            )
        except Exception as tg_err:
            print(f"[!] Не удалось отправить видео в Telegram чат {req.user_id}: {tg_err}")
    except Exception as e:
        db.update_task_status(task_id, "failed", error_message=str(e))
        try:
            await bot.send_message(
                chat_id=req.user_id,
                text=f"❌ **Произошла ошибка при рендеринге сниппета:**\n\n`{str(e)}`",
                parse_mode="Markdown"
            )
        except Exception as telegram_error:
            print(f"Не удалось отправить сообщение об ошибке пользователю: {telegram_error}")

async def render_influencer_pack_worker(task_id: str, req: InfluencerPackRequest):
    import zipfile
    import random
    from services.video_engine import render_split_screen_reaction
    
    db.update_task_status(task_id, "processing")
    
    try:
        all_influencers = db.get_all_influencers()
        if not all_influencers:
            raise Exception("В базе нет доступных ИИ-инфлюенсеров")
            
        target_influencers = []
        if req.influencer_ids and len(req.influencer_ids) > 0:
            for inf_id in req.influencer_ids:
                inf = db.get_influencer(inf_id)
                if inf:
                    target_influencers.append(inf)
            if not target_influencers:
                raise Exception(f"Указанные инфлюенсеры (IDs: {req.influencer_ids}) не найдены в базе данных")
        else:
            target_influencers = all_influencers

        total_runs = len(target_influencers) * max(1, req.count_per_inf)
        db.update_task_progress(task_id, 5, f"Подготовка к генерации {total_runs} роликов...")
        
        all_hook_paths = []
        if req.format == "hook":
            hooks_dir = config.DOWNLOADS_DIR / "footages" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            hook_files = list(hooks_dir.glob("*.mp4")) + list(hooks_dir.glob("*.mov"))
            db_hooks = [Path(f["file_path"]) for f in db.get_all_footages(category="hooks") if Path(f["file_path"]).exists()]
            all_hook_paths = list(set([str(p) for p in (hook_files + db_hooks)]))
            
            if not all_hook_paths:
                all_footages = db.get_all_footages()
                all_hook_paths = [f["file_path"] for f in all_footages if Path(f["file_path"]).exists()]
                
            if not all_hook_paths:
                raise Exception("В базе нет доступных видеофутажей или хуков для генерации")
            
        else: # snippet
            top_pool = []
            is_specific = False
            
            # Проверяем, выбрал ли пользователь один конкретный сниппет
            if req.snippet_id and str(req.snippet_id).lower() not in ["random", "none", "", "null"]:
                try:
                    snip_id_clean = int(str(req.snippet_id).replace("saved_", ""))
                    snip = db.get_saved_video_snippet(snip_id_clean)
                    if snip and Path(snip["file_path"]).exists():
                        top_pool = [snip["file_path"]] * total_runs
                        is_specific = True
                except Exception:
                    pass
                    
            # Если режим "Рандомные сниппеты" — гарантируем уникальный сниппет каждому инфлюенсеру без повторов
            if not is_specific or not top_pool:
                saved_snips = [s["file_path"] for s in db.get_all_saved_video_snippets() if Path(s["file_path"]).exists()]
                all_footages = [f["file_path"] for f in db.get_all_footages() if Path(f["file_path"]).exists()]
                
                # Объединяем уникальные исходники
                unique_pool = list(dict.fromkeys(saved_snips + all_footages))
                if not unique_pool:
                    raise Exception("В базе нет видеофутажей или сохраненных сниппетов для генерации")
                
                # Перемешиваем весь пул без повторов
                shuffled_pool = random.sample(unique_pool, k=len(unique_pool))
                
                # Формируем пул точно под нужное количество роликов без повторений
                top_pool = [shuffled_pool[i % len(shuffled_pool)] for i in range(total_runs)]

        generated_paths = []
        loop = asyncio.get_running_loop()
        
        run_idx = 0
        for inf in target_influencers:
            for c in range(max(1, req.count_per_inf)):
                inf_display_name = inf.get('name', 'Инфлюенсер')
                current_pct = int(5 + (run_idx / total_runs) * 85)
                db.update_task_progress(
                    task_id,
                    current_pct,
                    f"🎬 Генерируем ролик {run_idx + 1} из {total_runs} ({inf_display_name})..."
                )

                if req.format == "hook":
                    top_video = random.sample(all_hook_paths, k=len(all_hook_paths))
                else:
                    top_video = top_pool[run_idx % len(top_pool)]
                clean_inf_name = inf_display_name.replace(" ", "_").replace("/", "").replace("\\", "")
                out_filename = f"{clean_inf_name}_split_{run_idx+1}_{uuid.uuid4().hex[:4]}.mp4"
                
                res_path = await loop.run_in_executor(
                    None,
                    render_split_screen_reaction,
                    top_video,
                    inf["video_path"],
                    out_filename,
                    "split50",
                    float(req.duration)
                )
                generated_paths.append(res_path)
                run_idx += 1

                done_pct = int(5 + (run_idx / total_runs) * 85)
                db.update_task_progress(
                    task_id,
                    done_pct,
                    f"✅ Сгенерирован ролик {run_idx} из {total_runs} ({inf_display_name})"
                )
                
        if not generated_paths:
            raise Exception("Не удалось сгенерировать ни одного видеоролика")
            
        if len(generated_paths) == 1:
            final_result = generated_paths[0]
        else:
            db.update_task_progress(
                task_id,
                94,
                f"📦 Все {len(generated_paths)} роликов сгенерированы! Упаковываем в ZIP-архив..."
            )
            zip_filename = f"Influencers_Pack_{len(generated_paths)}_Videos_{uuid.uuid4().hex[:4]}.zip"
            zip_path = config.OUTPUT_DIR / zip_filename
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for p in generated_paths:
                    zf.write(p, arcname=Path(p).name)
            final_result = str(zip_path)
            
        db.update_task_progress(task_id, 100, "Готово!")
            
        db.update_task_status(task_id, "completed", result_path=final_result)
        
        if req.user_id:
            try:
                if len(generated_paths) == 1:
                    video = FSInputFile(final_result)
                    await bot.send_video(
                        chat_id=req.user_id,
                        video=video,
                        caption=f"🎬 **Ваш Split-Screen ролик с ИИ-Инфлюенсером готов!**",
                        parse_mode="Markdown"
                    )
                else:
                    zip_size_mb = round(Path(final_result).stat().st_size / (1024 * 1024), 1)
                    if zip_size_mb > 48:
                        download_url = f"{config.MINI_APP_URL}/downloads/outputs/{Path(final_result).name}"
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text=f"⬇️ Скачать архив ({zip_size_mb} MB)", url=download_url)]
                        ])
                        await bot.send_message(
                            chat_id=req.user_id,
                            text=f"📦 **Пакет из {len(generated_paths)} уникальных роликов готов!**\n\n"
                                 f"📁 Размер архива: `{zip_size_mb} MB`\n"
                                 f"Ссылка на прямое скачивание:",
                            reply_markup=kb,
                            parse_mode="Markdown"
                        )
                    else:
                        doc = FSInputFile(final_result)
                        await bot.send_document(
                            chat_id=req.user_id,
                            document=doc,
                            caption=f"📦 **Пакетный ZIP-архив роликов готов!**\nСгенерировано: `{len(generated_paths)}` шт. ({zip_size_mb} MB)",
                            parse_mode="Markdown"
                        )
            except Exception as tg_err:
                print(f"[!] Ошибка отправки пакета в Telegram: {tg_err}")
                
    except Exception as e:
        print(f"[!] Ошибка пакета инфлюенсеров: {e}")
        db.update_task_status(task_id, "failed", error_message=str(e))
        if req.user_id:
            try:
                await bot.send_message(
                    chat_id=req.user_id,
                    text=f"❌ Ошибка генерации пака роликов: `{str(e)}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

@app.post("/api/influencer_pack")
async def start_influencer_pack(req: InfluencerPackRequest, background_tasks: BackgroundTasks):
    """Запуск массового рендеринга Split-Screen видеореакций ИИ-Инфлюенсеров."""
    task_id = str(uuid.uuid4())
    db.add_render_task(
        task_id=task_id,
        user_id=req.user_id or 0,
        track_id=0,
        footage_id=0,
        start_time=0.0,
        end_time=req.duration
    )
    background_tasks.add_task(render_influencer_pack_worker, task_id, req)
    return {"task_id": task_id, "status": "pending"}

@app.post("/api/render")
async def start_render(req: RenderRequest, background_tasks: BackgroundTasks):
    """Запуск процесса создания видео."""
    task_id = str(uuid.uuid4())
    
    # Сохраняем задачу в бд
    db.add_render_task(
        task_id=task_id,
        user_id=req.user_id,
        track_id=req.track_id,
        footage_id=req.footage_id,
        start_time=req.start_time,
        end_time=req.end_time
    )
    
    # Добавляем рендеринг в фоновые задачи FastAPI
    background_tasks.add_task(render_task_worker, task_id, req)
    
    return {"task_id": task_id, "status": "pending"}

@app.get("/api/tasks/{task_id}")
async def get_task_status_endpoint(task_id: str):
    """Получить текущий статус задачи рендеринга."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена в базе данных")
    return task

@app.post("/api/tasks/{task_id}/save_snippet")
async def save_task_snippet_endpoint(task_id: str):
    """Явное сохранение видеоролика в коллекцию сохраненных сниппетов."""
    task = db.get_task(task_id)
    if not task or not task.get("result_path"):
        raise HTTPException(status_code=400, detail="Готовое видео не найдено")
    
    result_path = task["result_path"]
    if not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Файл видео не найден на диске")
    
    track = db.get_track(task["track_id"]) if task.get("track_id") else None
    artist_str = f"{track['artist']} - " if (track and track.get('artist')) else ""
    title_str = track['title'] if (track and track.get('title')) else "Видео-сниппет"
    snip_title = f"{artist_str}{title_str} [{int(task.get('start_time', 0))}-{int(task.get('end_time', 15))}s]"
    
    dur = float(task.get('end_time', 15) - task.get('start_time', 0))
    snip_id = db.add_saved_video_snippet(title=snip_title, file_path=result_path, duration=dur)
    return {"status": "ok", "snippet_id": snip_id, "message": "Сниппет сохранен в коллекцию"}

@app.post("/api/tasks/{task_id}/delete")
async def delete_task_endpoint(task_id: str):
    """Удаление созданного видеоролика с диска и базы."""
    task = db.get_task(task_id)
    if task and task.get("result_path"):
        p = Path(task["result_path"])
        if p.exists():
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
    return {"status": "ok", "message": "Видео удалено"}

def sync_influencers_from_folder():
    """Автоматическое добавление инфлюенсеров из папки downloads/influencers."""
    import re
    inf_dir = config.DOWNLOADS_DIR / "influencers"
    inf_dir.mkdir(parents=True, exist_ok=True)
    
    for file in list(inf_dir.glob("*.mp4")) + list(inf_dir.glob("*.mov")):
        raw_stem = file.stem.replace("inf_", "").replace("_", " ")
        name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', raw_stem).strip().title()
        exists = any(i["video_path"] == str(file) for i in db.get_all_influencers())
        if not exists:
            db.add_influencer(
                name=name,
                category="general",
                video_path=str(file),
                handle=f"@{file.stem.lower()}"
            )
            print(f"[+] Добавлен ИИ-инфлюенсер: {name}")


    for sub in inf_dir.iterdir():
        if sub.is_dir():
            v_files = list(sub.glob("*.mp4"))
            if v_files:
                v_file = v_files[0]
                img_files = list(sub.glob("*.jpg")) + list(sub.glob("*.png"))
                avatar_path = str(img_files[0]) if img_files else None
                name = sub.name.replace("_", " ").title()
                exists = any(i["video_path"] == str(v_file) for i in db.get_all_influencers())
                if not exists:
                    db.add_influencer(
                        name=name,
                        category="general",
                        video_path=str(v_file),
                        avatar_path=avatar_path,
                        handle=f"@{sub.name.lower()}"
                    )
                    print(f"[+] Добавлен ИИ-инфлюенсер из подпапки: {name}")

@app.get("/api/influencers")
async def get_influencers(category: Optional[str] = None):
    """Получить список всех ИИ-Инфлюенсеров с авто-синхронизацией папки."""
    sync_influencers_from_folder()
    return db.get_all_influencers(category=category)


class InfluencerCreate(BaseModel):
    name: str
    category: str = "general"
    video_path: str
    avatar_path: Optional[str] = None
    handle: Optional[str] = None

@app.post("/api/influencers")
async def create_influencer(inf: InfluencerCreate):
    """Создать новый профиль ИИ-Инфлюенсера."""
    inf_id = db.add_influencer(
        name=inf.name,
        category=inf.category,
        video_path=inf.video_path,
        avatar_path=inf.avatar_path,
        handle=inf.handle
    )
    return {"id": inf_id, "status": "success"}

@app.delete("/api/influencers/{influencer_id}")
async def delete_influencer(influencer_id: int):
    """Удалить профиль ИИ-Инфлюенсера."""
    db.delete_influencer(influencer_id)
    return {"status": "deleted"}

class SplitScreenRequest(BaseModel):
    top_video_path: str
    bottom_influencer_path: str
    layout: str = "split50"

@app.post("/api/render-split-screen")
async def render_split_screen(req: SplitScreenRequest):
    """Рендеринг Split-Screen видео реакции ИИ-Инфлюенсера."""
    from services.video_engine import render_split_screen_reaction
    out_name = f"split_{uuid.uuid4().hex[:8]}.mp4"
    res_path = render_split_screen_reaction(
        top_video_path=req.top_video_path,
        bottom_influencer_path=req.bottom_influencer_path,
        output_filename=out_name,
        layout=req.layout
    )
    rel_path = f"/downloads/outputs/{out_name}"
    return {"status": "completed", "result_url": rel_path, "file_path": res_path}

# --- REST API v1 Endpoints (Public OpenAPI Service) ---

@app.get("/api/v1/stats")
async def get_system_stats():
    """Возвращает общую статистику базы данных медиаконтента."""
    tracks = db.get_all_tracks()
    footages = db.get_all_footages()
    influencers = db.get_all_influencers()
    segments = db.get_all_audio_segments()
    return {
        "status": "success",
        "counts": {
            "tracks": len(tracks),
            "footages": len(footages),
            "influencers": len(influencers),
            "audio_segments": len(segments)
        }
    }

@app.get("/api/v1/tracks")
async def api_get_tracks():
    """Возвращает список всех доступных треков."""
    return {"status": "success", "tracks": db.get_all_tracks()}

@app.get("/api/v1/influencers")
async def api_get_influencers():
    """Возвращает список всех ИИ-Инфлюенсеров."""
    return {"status": "success", "influencers": db.get_all_influencers()}

def get_footage_url(file_path: str) -> str:
    norm = str(file_path).replace("\\", "/")
    if "downloads/" in norm.lower():
        parts = norm.split("downloads/", 1)
        return "/downloads/" + parts[1]
    return "/downloads/" + Path(file_path).name

@app.get("/api/footages")
async def get_footages(category: Optional[str] = Query(None)):
    """Возвращает список сохраненных видео-футажей."""
    foots = db.get_all_footages(category=category)
    for f in foots:
        f["file_url"] = get_footage_url(f["file_path"])
    return foots

@app.get("/api/v1/footages")
async def api_get_footages(category: Optional[str] = None):
    """Возвращает список фоновых футажей."""
    foots = db.get_all_footages(category=category)
    for f in foots:
        f["file_url"] = get_footage_url(f["file_path"])
    return {"status": "success", "footages": foots}


@app.get("/api/v1/audio_segments")
async def api_get_audio_segments():
    """Возвращает список всех вырезанных отрезков."""
    return {"status": "success", "audio_segments": db.get_all_audio_segments()}

# Монтируем статические файлы для фронтенда Mini App
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.mount("/downloads", StaticFiles(directory=str(config.DOWNLOADS_DIR)), name="downloads")

@app.get("/")
async def root():
    """Перенаправляем на интерфейс Mini App."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


# --- Запуск приложений ---

async def main():
    try:
        from audit_bot_system import run_system_audit
        run_system_audit()
    except Exception as audit_err:
        logger.error(f"Не удалось выполнить автоматический аудит при старте: {audit_err}")

    db.reset_stale_render_tasks()
    logger.info("Запуск сервера SnipPlitAiStudio FastAPI...")

    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=config.WEB_PORT,
        log_level="info"
    )
    server = uvicorn.Server(uvicorn_config)
    print(f"\n[+] Запуск сервера на http://localhost:{config.WEB_PORT}")
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
