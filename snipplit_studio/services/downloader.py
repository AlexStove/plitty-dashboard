import os
import re
import json
import urllib.request
import urllib.parse
import yt_dlp
import imageio_ffmpeg
from pathlib import Path
from typing import Dict, Any, Optional
from yandex_music import Client

from services.metadata_extractor import clean_track_artist_title

import ssl

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def resolve_track_metadata_via_songlink(url: str) -> Optional[tuple]:
    """Универсальный бесплатный резолвер метаданных треков для Yandex Music, Spotify, Apple, Deezer."""
    try:
        songlink_url = f"https://api.song.link/v1-alpha.1/links?url={urllib.parse.quote(url)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        req = urllib.request.Request(songlink_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            entity_id = data.get("entityUniqueId")
            entities = data.get("entitiesByUniqueId", {})
            entity = entities.get(entity_id, {})
            title = entity.get("title")
            artist = entity.get("artistName")
            if title and artist:
                return title, artist
            elif title:
                return title, "Unknown Artist"
    except Exception as e:
        print(f"[!] SongLink API info: {e}")
    return None

def fetch_auto_lyrics(artist: str, title: str, yandex_track_id: Optional[str] = None, yandex_client: Optional[Client] = None) -> Optional[str]:


    """
    Автоматически ищет и скачивает LRC-субтитры с таймингами.
    1. Пробует Yandex Music API (если клиент доступен).
    2. Пробует бесплатную базу синхронизированных субтитров LRCLIB (по артисту и названию).
    3. Фолбек на открытый поиск LRCLIB.
    """
    if yandex_client and yandex_track_id:
        try:
            lyr = yandex_client.tracks_lyrics(yandex_track_id)
            if lyr:
                try:
                    lrc = lyr.fetch_lrc()
                    if lrc:
                        return lrc
                except Exception:
                    pass
                if getattr(lyr, 'full_lyrics', None):
                    return lyr.full_lyrics
        except Exception as e:
            print(f"[!] Yandex Music lyrics fetch info: {e}")

    clean_artist = re.sub(r'\(.*?\)', '', artist).strip()
    clean_title = re.sub(r'\(.*?\)', '', title).strip()
    if clean_artist.lower() in ["unknown artist", "unknown", ""]:
        clean_artist = ""

    def is_matching_track(target_title: str, target_artist: str, item_title: str, item_artist: str) -> bool:
        t_clean = re.sub(r'[^\w]', '', target_title).lower()
        i_clean = re.sub(r'[^\w]', '', item_title).lower()
        if not (t_clean in i_clean or i_clean in t_clean):
            return False
        if target_artist and target_artist.lower() != "unknown artist":
            a_clean = re.sub(r'[^\w]', '', target_artist).lower()
            ia_clean = re.sub(r'[^\w]', '', item_artist).lower()
            if not (a_clean in ia_clean or ia_clean in a_clean):
                return False
        return True

    # 1. Попытка точного вызова LRCLIB (если артист известен)
    if clean_artist:
        try:
            url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(clean_artist)}&track_name={urllib.parse.quote(clean_title)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                synced = data.get('syncedLyrics')
                if synced:
                    return synced
                plain = data.get('plainLyrics')
                if plain:
                    return plain
        except Exception:
            pass

    # 2. Поиск по названию трека в открытом API LRCLIB с проверкой точного совпадения
    try:
        search_query = f"{clean_artist} {clean_title}".strip() if clean_artist else clean_title
        url = f"https://lrclib.net/api/search?q={urllib.parse.quote(search_query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as resp:
            items = json.loads(resp.read().decode('utf-8'))
            if isinstance(items, list) and len(items) > 0:
                # Первым делом ищем только совпадающие по названию и артисту синхронизированные субтитры
                for item in items:
                    if item.get('syncedLyrics') and is_matching_track(clean_title, clean_artist, item.get('trackName', ''), item.get('artistName', '')):
                        return item.get('syncedLyrics')
                # Фолбек: совпадающий обычный текст
                for item in items:
                    if item.get('plainLyrics') and is_matching_track(clean_title, clean_artist, item.get('trackName', ''), item.get('artistName', '')):
                        return item.get('plainLyrics')
    except Exception as err:
        print(f"[!] LRCLIB search error: {err}")

    return None


class Downloader:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Получаем путь к FFmpeg, который был установлен вместе с moviepy/imageio-ffmpeg
        try:
            self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            self.ffmpeg_path = "ffmpeg"  # Фолбек на глобальный ffmpeg

    def _get_ydl_opts(self, output_template: str) -> Dict[str, Any]:
        return {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'ffmpeg_location': self.ffmpeg_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                }
            },
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            }
        }


    def _get_yandex_web_metadata(self, url: str) -> tuple:
        """Извлекает имя исполнителя и название трека из HTML страницы Яндекс Музыки."""
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html) or re.search(r'<title>([^<]+)</title>', html)
                if title_match:
                    raw_title = title_match.group(1)
                    # Очищаем лишний текст типа "слушать онлайн на Яндекс Музыке"
                    clean_title = re.sub(r'—\s*слушать онлайн.*', '', raw_title, flags=re.IGNORECASE).strip()
                    clean_title = re.sub(r'на Яндекс Музыке.*', '', clean_title, flags=re.IGNORECASE).strip()
                    if '—' in clean_title:
                        parts = clean_title.split('—')
                        return parts[1].strip(), parts[0].strip()
                    elif '-' in clean_title:
                        parts = clean_title.split('-')
                        return parts[1].strip(), parts[0].strip()
                    return clean_title, ""
        except Exception as e:
            print(f"[!] Ошибка получения веб-метаданных Яндекс Музыки: {e}")
        return "", ""


    def download_from_youtube(self, url: str) -> Dict[str, Any]:
        """Скачивает аудио с YouTube и конвертирует в MP3."""
        # Шаблон имени файла с уникальным ID во избежание конфликтов
        template = str(self.output_dir / "%(title)s_%(id)s.%(ext)s")
        ydl_opts = self._get_ydl_opts(template)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Так как мы конвертировали в mp3, меняем расширение в пути
            mp3_path = os.path.splitext(filename)[0] + '.mp3'
            
            return {
                "title": info.get("title", "Unknown Title"),
                "artist": info.get("uploader", "Unknown Artist"),
                "file_path": mp3_path,
                "duration": float(info.get("duration", 0)),
                "source": "youtube",
                "source_url": url
            }

    def download_from_spotify(self, url: str) -> Dict[str, Any]:
        """
        Парсит метаданные трека Spotify через SongLink/OEmbed API,
        ищет трек на YouTube и скачивает аудио.
        """
        songlink_res = resolve_track_metadata_via_songlink(url)
        if songlink_res:
            title, artist = songlink_res
        else:
            title, artist = self._get_spotify_metadata(url)
            
        search_query = f"ytsearch:{artist} - {title} audio" if artist and artist != "Unknown Artist" else f"ytsearch:{title} audio"
        
        safe_name = "".join([c for c in f"{artist} - {title}" if c.isalpha() or c.isdigit() or c in ' -_']).strip()
        template = str(self.output_dir / f"{safe_name}_spotify.%(ext)s")
        ydl_opts = self._get_ydl_opts(template)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=True)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                filename = ydl.prepare_filename(entry)
                mp3_path = os.path.splitext(filename)[0] + '.mp3'
                duration = float(entry.get("duration", 0))
            else:
                raise Exception("Не удалось найти трек на YouTube")
                
            return {
                "title": title,
                "artist": artist,
                "file_path": mp3_path,
                "duration": duration,
                "source": "spotify",
                "source_url": url
            }

    def _get_spotify_metadata(self, url: str) -> tuple:
        """Скачивает метаданные со страницы Spotify через OEmbed API."""
        oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(
            oembed_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        try:
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as response:
                data = json.loads(response.read().decode('utf-8'))
                title = data.get("title", "Unknown Track")
                artist = data.get("author_name", "Unknown Artist")
                return title, artist
        except Exception as e:
            print(f"[!] Spotify oEmbed info: {e}")
            return "Unknown Track", "Unknown Artist"

    def download_from_yandex(self, url: str, token: Optional[str] = None, user_text: Optional[str] = None) -> Dict[str, Any]:
        """Скачивает трек с Яндекс Музыки с авто-резолвингом через SongLink / Yandex API / Shazam AI."""
        import config
        token = token or getattr(config, 'YANDEX_MUSIC_TOKEN', None)
        
        track_id_match = re.search(r'track/(\d+)', url)
        track_id = track_id_match.group(1) if track_id_match else None

        title, artist = None, None

        # Попытка 1: Через открытый SongLink API (100% точность для любых сервисов)
        songlink_res = resolve_track_metadata_via_songlink(url)
        if songlink_res:
            title, artist = songlink_res

        # Попытка 2: Через токен Yandex Music API (если передан)
        if track_id and token and token != "YOUR_YANDEX_MUSIC_TOKEN_HERE":

            try:
                client = Client(token).init()
                tracks = client.tracks([track_id])
                if tracks:
                    track = tracks[0]
                    artist = ", ".join([a.name for a in track.artists]) if track.artists else "Unknown Artist"
                    title = track.title
                    
                    safe_title = "".join([c for c in f"{artist} - {title}" if c.isalpha() or c.isdigit() or c in ' -_']).strip()
                    dest_path = self.output_dir / f"{safe_title}_{track_id}.mp3"
                    track.download(str(dest_path), codec='mp3', bitrate_in_kbps=192)
                    duration = float(track.duration_ms) / 1000.0 if track.duration_ms else 0.0
                    return {
                        "title": title,
                        "artist": artist,
                        "file_path": str(dest_path),
                        "duration": duration,
                        "source": "yandex",
                        "source_url": url
                    }
            except Exception as ym_err:
                print(f"[!] Yandex API token info: {ym_err}")

        # Попытка 3: Метаданные из текста подписи пользователя в Telegram
        if not title and user_text:
            text_without_url = re.sub(r'https?://[^\s]+', '', user_text).strip()
            text_without_url = re.sub(r'(слушаю|на яндекс музыке|яндекс музыка|трек|слушать)', '', text_without_url, flags=re.IGNORECASE).strip()
            if len(text_without_url) > 2 and ("—" in text_without_url or "-" in text_without_url):
                parts = re.split(r'[—\-]', text_without_url, 1)
                artist, title = parts[0].strip(), parts[1].strip()

        # Попытка 4: Веб-метаданные из HTML страницы
        if not title:
            web_title, web_artist = self._get_yandex_web_metadata(url)
            if web_title:
                title, artist = web_title, web_artist

        if not title:
            raise Exception("Не удалось распознать метаданные трека с Яндекс.Музыки. Отправьте файл MP3 или введите название трека текстом!")

        search_query = f"ytsearch:{artist} - {title} audio" if artist and artist != "Unknown Artist" else f"ytsearch:{title} audio"
        safe_name = "".join([c for c in f"{artist} - {title}" if c.isalpha() or c.isdigit() or c in ' -_']).strip()
        template = str(self.output_dir / f"{safe_name}_yandex.%(ext)s")
        ydl_opts = self._get_ydl_opts(template)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=True)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                filename = ydl.prepare_filename(entry)
                mp3_path = os.path.splitext(filename)[0] + '.mp3'
                duration = float(entry.get("duration", 0))
                
                # Если названия ещё нет, узнаем его через Shazam AI из скачанного файла
                if not artist or artist == "Unknown Artist":
                    shazam_res = self.recognize_audio_sync(mp3_path)
                    if shazam_res:
                        artist, title = shazam_res
                
                artist, title = clean_track_artist_title(artist, title, mp3_path)
                return {
                    "title": title,
                    "artist": artist,
                    "file_path": mp3_path,
                    "duration": duration,
                    "source": "yandex",
                    "source_url": url
                }
            else:
                raise Exception("Не удалось найти аудиозапись по запросу.")


    def recognize_audio_sync(self, file_path: str) -> Optional[tuple]:
        """Распознает исполнителя и название песни через Shazam AI."""
        try:
            from shazamio import Shazam
            import asyncio
            
            async def _run():
                shazam = Shazam()
                out = await shazam.recognize(file_path)
                track = out.get('track', {})
                title = track.get('title')
                artist = track.get('subtitle')
                if title and artist:
                    return artist, title
                return None
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если уже находимся в событиной петле, создаем подпроцесс
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(lambda: asyncio.run(_run())).result()
                else:
                    return loop.run_until_complete(_run())
            except Exception:
                return asyncio.run(_run())
        except Exception as e:
            print(f"[!] Shazam recognition failed: {e}")
            return None


    def download_by_link(self, url: str, yandex_token: Optional[str] = None, user_text: Optional[str] = None) -> Dict[str, Any]:
        """Определяет тип ссылки и скачивает трек."""
        if "youtube.com" in url or "youtu.be" in url:
            res = self.download_from_youtube(url)
        elif "spotify.com" in url:
            res = self.download_from_spotify(url)
        elif "music.yandex.ru" in url:
            res = self.download_from_yandex(url, token=yandex_token, user_text=user_text)

        else:
            raise ValueError("Неподдерживаемый тип ссылки. Поддерживаются YouTube, Spotify и Yandex Music.")

        # Умная очистка артиста и названия
        artist, title = clean_track_artist_title(res.get("artist"), res.get("title"), res.get("file_path"))
        res["artist"] = artist
        res["title"] = title
        return res


    def download_footage_by_link(self, url: str) -> Dict[str, Any]:
        """
        Скачивает видеофутаж по ссылке (TikTok, YouTube Shorts, Instagram Reels, VK, Pinterest и т.д.).
        Сохраняет файл MP4 в папку config.FOOTAGE_DIR.
        """
        from moviepy import VideoFileClip
        out_dir = config.FOOTAGE_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        template = str(out_dir / "footage_%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': template,
            'ffmpeg_location': self.ffmpeg_path,
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                base_path = os.path.splitext(filename)[0]
                if os.path.exists(f"{base_path}.mp4"):
                    filename = f"{base_path}.mp4"

            width, height, duration = 0, 0, 0.0
            try:
                clip = VideoFileClip(filename)
                duration = clip.duration
                width, height = clip.size
                clip.close()
            except Exception:
                width = info.get("width", 720) or 720
                height = info.get("height", 1280) or 1280
                duration = float(info.get("duration", 0))

            display_name = info.get("title", f"footage_{info.get('id', 'video')}")
            if len(display_name) > 35:
                display_name = display_name[:35] + "..."
            if not display_name.endswith(".mp4"):
                display_name += ".mp4"

            return {
                "filename": display_name,
                "file_path": filename,
                "duration": duration,
                "width": width,
                "height": height,
                "source_url": url
            }
