import os
import re
from typing import Tuple
from tinytag import TinyTag

def clean_track_artist_title(raw_artist: str = "", raw_title: str = "", file_path: str = None) -> Tuple[str, str]:
    """
    Умное определение и очистка исполнителя (artist) и названия трека (title).
    1. Читает ID3-теги из файла с помощью tinytag (если есть).
    2. Очищает названия от технических префиксов 'Unknown Artist'.
    3. Разбивает названия типа 'Исполнитель - Название песни'.
    4. Удаляет кликбейтные/технические приписки YouTube ((Official Video), [Audio] и т.д.).
    """
    artist = (raw_artist or "").strip()
    title = (raw_title or "").strip()

    # Сбрасываем шаблоны неизвестного исполнителя/названия
    if artist.lower() in ["unknown artist", "unknown", "none", "null", "неизвестен", ""]:
        artist = ""
    if title.lower() in ["unknown title", "unknown", "none", "null", "track", ""]:
        title = ""

    # 1. Считываем реальные ID3-теги из MP3 файла (если файл существует)
    if file_path and os.path.exists(file_path):
        try:
            tag = TinyTag.get(file_path)
            if tag.artist and not artist:
                artist = tag.artist.strip()
            if tag.title and not title:
                title = tag.title.strip()
        except Exception:
            pass

    # 2. Если title все еще пуст, пробуем имя файла без расширения
    if file_path and not title:
        base_filename = os.path.splitext(os.path.basename(file_path))[0]
        # Очищаем суффиксы источников (_yandex, _spotify, etc.)
        base_filename = re.sub(r'_(yandex|spotify|youtube)$', '', base_filename, flags=re.IGNORECASE)
        title = base_filename.strip()

    # 3. Очищаем название от водяных знаков и приписок YouTube/VK
    junk_patterns = [
        r'[\(\[\{].*?(official|video|audio|lyric|lyrics|remastered|hd|4k|clip|клип|премьера).*?[\)\]\}]',
        r'(official video|official audio|lyric video|official music video|audio|remastered|hd|4k)',
    ]
    for pattern in junk_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()

    # 4. Если исполнитель не определен, но title содержит ' - '
    if not artist and " - " in title:
        parts = title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()

    # 5. Если и в пути к файлу имя содержит ' - '
    if file_path and not artist:
        base_filename = os.path.splitext(os.path.basename(file_path))[0]
        if " - " in base_filename:
            parts = base_filename.split(" - ", 1)
            artist = parts[0].strip()
            if not title or title == base_filename:
                title = parts[1].strip()

    # Убираем дефисы в начале слов
    artist = re.sub(r'^\s*-\s*', '', artist).strip()
    title = re.sub(r'^\s*-\s*', '', title).strip()

    # Если совсем ничего не удалось определить
    if not artist:
        artist = "Unknown Artist"
    if not title:
        title = "Unknown Title"

    return artist, title
