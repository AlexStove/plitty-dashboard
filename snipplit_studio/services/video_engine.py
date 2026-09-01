import os
import re
import math
import shutil
import random

from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip
from moviepy.video.fx import Crop, Loop, Resize, BlackAndWhite, MultiplyColor, LumContrast
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
import uuid

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from services.whisper_transcriber import transcribe_audio_segment, align_lyrics_with_whisper
from services.lrc_parser import split_line_into_words, chunk_words_into_phrases
from services.emoji_mapper import get_emoji_for_word


def apply_video_filter(clip, filter_name: str):
    """Применяет кинематографический видеоэффект к ролику."""
    filter_name = (filter_name or "none").lower().strip()
    if filter_name == "bw":
        return clip.with_effects([BlackAndWhite()])
    elif filter_name == "vhs":
        return clip.with_effects([LumContrast(lum=5, contrast=0.3), MultiplyColor(factor=1.1)])
    elif filter_name == "cyberpunk":
        return clip.with_effects([LumContrast(lum=10, contrast=0.4), MultiplyColor(factor=1.2)])
    elif filter_name == "warm_cinematic":
        return clip.with_effects([MultiplyColor(factor=1.15), LumContrast(lum=5, contrast=0.2)])
    return clip

def create_vignette_image(width: int, height: int, output_path: str) -> None:
    """Создает и кэширует прозрачное PNG-изображение с мягкой виньеткой по краям кадра."""
    if os.path.exists(output_path):
        return

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # Использование более быстрого формирования виньетки
    mask_w, mask_h = 180, 320
    mask = Image.new("RGBA", (mask_w, mask_h), (0, 0, 0, 0))
    mcx, mcy = mask_w / 2, mask_h / 2
    m_max_r = math.sqrt(mcx**2 + mcy**2)
    
    for y in range(mask_h):
        for x in range(mask_w):
            dist = math.sqrt((x - mcx)**2 + (y - mcy)**2)
            norm_dist = dist / m_max_r
            if norm_dist > 0.4:
                alpha = int(255 * math.pow((norm_dist - 0.4) / 0.6, 1.8) * 0.65)
                alpha = min(170, max(0, alpha))
                mask.putpixel((x, y), (0, 0, 0, alpha))
                
    mask = mask.resize((width, height), Image.Resampling.BILINEAR)
    mask.save(output_path, "PNG")


EMOJI_MAP = {
    'CAR': '🏎', 'AUTO': '🏎', 'DRIFT': '🏎', 'SPEED': '⚡️', 'RACE': '🏎',
    'GOAL': '⚽️', 'FOOTBALL': '⚽️', 'SOCCER': '⚽️', 'BALL': '⚽️', 'SPORT': '🏆',
    'MONEY': '💰', 'RICH': '💰', 'CASH': '💰', 'DOLLAR': '💵',
    'FIRE': '🔥', 'HOT': '🔥', 'BURN': '🔥', 'LIT': '🔥',
    'LOVE': '❤️', 'HEART': '💖', 'GIRL': '👠', 'BEAUTY': '💄', 'FASHION': '👠',
    'NIGHT': '🌆', 'CITY': '🌆', 'KING': '👑', 'CROWN': '👑', 'STAR': '🌟'
}

def get_word_emoji(word: str) -> str:
    clean = re.sub(r'[^\w]', '', word).upper()
    return EMOJI_MAP.get(clean, '')

def create_subtitle_image(text: str, width: int, height: int, font_path: str, 
                          font_size: int, output_path: str, style: str = "tiktok",
                          pos_y_ratio: float = 0.72, active_word_index: int = -1) -> None:

    """
    Создает высокое по качеству PNG-изображение субтитров с поддержкой вирусных стилей MrBeast и Hormozi,
    автоматической расстановкой эмодзи и гарантией невыхода за рамки кадра.
    """
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    words = text.strip().upper().split()
    if not words:
        image.save(output_path, "PNG")
        return

    style = (style or "tiktok").lower()
    max_text_width = width * 0.84

    # 1. Автоматический выбор размера шрифта и разбиение на строки
    curr_font_size = font_size
    if style in ["mrbeast", "hormozi"]:
        curr_font_size = int(font_size * 1.15)

    lines = []
    font = None

    while curr_font_size >= 16:
        try:
            font = ImageFont.truetype(str(font_path), curr_font_size)
        except Exception:
            font = ImageFont.load_default()

        full_str = " ".join(words)
        total_w = draw.textlength(full_str, font=font)
        
        if total_w <= max_text_width:
            lines = [words]
            break
        else:
            lines = []
            curr_line = []
            curr_w = 0
            space_w = draw.textlength(" ", font=font)

            for w in words:
                w_w = draw.textlength(w, font=font)
                if curr_line and (curr_w + space_w + w_w > max_text_width):
                    lines.append(curr_line)
                    curr_line = [w]
                    curr_w = w_w
                else:
                    curr_line.append(w)
                    curr_w += (space_w if curr_line else 0) + w_w
            if curr_line:
                lines.append(curr_line)

            max_line_w = max([sum(draw.textlength(w, font=font) for w in l) + max(0, len(l)-1)*space_w for l in lines] or [0])
            if max_line_w <= max_text_width:
                break
            else:
                curr_font_size -= 3

    if not font:
        try:
            font = ImageFont.truetype(str(font_path), curr_font_size)
        except Exception:
            font = ImageFont.load_default()

    # 2. Высота строк и плашки
    try:
        ascent, descent = font.getmetrics()
        line_height = (ascent + descent) * 1.15
    except Exception:
        line_height = curr_font_size * 1.15

    total_text_h = len(lines) * line_height
    center_x = width / 2
    center_y = height * pos_y_ratio

    space_w = draw.textlength(" ", font=font)
    line_widths = []
    for l in lines:
        w_sum = sum(draw.textlength(w, font=font) for w in l) + max(0, len(l) - 1) * space_w
        line_widths.append(w_sum)
        
    block_max_w = max(line_widths) if line_widths else 100

    padding_x = 24
    padding_y = 12

    # 3. Отрисовка плашки (фон)
    if style in ["tiktok", "instagram", "minimal"]:
        bg_color = (0, 0, 0, 190) if style == "minimal" else (0, 0, 0, 210)
        draw.rounded_rectangle(
            [center_x - (block_max_w / 2) - padding_x, 
             center_y - (total_text_h / 2) - padding_y, 
             center_x + (block_max_w / 2) + padding_x, 
             center_y + (total_text_h / 2) + padding_y],
            radius=16,
            fill=bg_color
        )
    elif style == "mrbeast":
        draw.rounded_rectangle(
            [center_x - (block_max_w / 2) - padding_x, 
             center_y - (total_text_h / 2) - padding_y, 
             center_x + (block_max_w / 2) + padding_x, 
             center_y + (total_text_h / 2) + padding_y],
            radius=18,
            fill=(0, 0, 0, 240),
            outline=(255, 230, 0, 255),
            width=4
        )

    # 4. Отрисовка текста по строкам
    start_y = center_y - (total_text_h / 2)
    global_word_idx = 0

    for line_i, line_words in enumerate(lines):
        line_w = line_widths[line_i]
        curr_x = center_x - (line_w / 2)
        curr_y = start_y + (line_i * line_height)

        for w_i, w in enumerate(line_words):
            word_w = draw.textlength(w, font=font)
            is_active = (global_word_idx == active_word_index)
            global_word_idx += 1

            emoji = get_emoji_for_word(w) if is_active else None

            if style == "mrbeast":
                if is_active:
                    fill_color = (255, 230, 0, 255)
                    stroke_fill = (0, 0, 0, 255)
                    stroke_w = 7
                else:
                    fill_color = (255, 255, 255, 255)
                    stroke_fill = (0, 0, 0, 240)
                    stroke_w = 5
            elif style == "hormozi":
                if is_active:
                    fill_color = (0, 255, 102, 255)
                    stroke_fill = (0, 0, 0, 255)
                    stroke_w = 6
                else:
                    fill_color = (255, 255, 255, 230)
                    stroke_fill = (0, 0, 0, 200)
                    stroke_w = 4
            elif style == "neon":
                fill_color = (217, 70, 239, 255) if is_active else (255, 255, 255, 220)
                stroke_fill = (6, 182, 212, 255)
                stroke_w = 5
            elif style == "stroke":
                fill_color = (255, 230, 0, 255) if is_active else (255, 255, 255, 255)
                stroke_fill = (0, 0, 0, 255)
                stroke_w = 5
            else:
                if is_active:
                    fill_color = (255, 230, 0, 255)
                    stroke_fill = (0, 0, 0, 255)
                    stroke_w = 5
                else:
                    fill_color = (220, 220, 220, 200)
                    stroke_fill = (0, 0, 0, 180)
                    stroke_w = 3

            word_y = curr_y - 6 if is_active else curr_y
            display_w = f"{w} {emoji}".strip() if emoji else w
            draw.text((curr_x, word_y), display_w, font=font, fill=fill_color, 
                      stroke_width=stroke_w, stroke_fill=stroke_fill)

            curr_x += word_w + space_w

    image.save(output_path, "PNG")




def create_single_word_image(word: str, width: int, height: int, font_path: str, 
                             font_size: int, output_path: str, style: str = "tiktok") -> None:
    """Для обратной совместимости."""
    create_subtitle_image(word, width, height, font_path, font_size, output_path, style=style, pos_y_ratio=0.65)


def render_snippet(audio_path: str, video_path: str, start_time: float, end_time: float,
                   lyrics: List[Dict[str, Any]], output_filename: str, 
                   vertical_crop: bool = True, subtitle_style: str = "tiktok",
                   video_filter: str = "none", remove_watermark: bool = True,
                   subtitle_mode: str = "phrase", subtitle_position: str = "bottom") -> str:
    """
    Генерирует динамичный сниппет 9:16 с точной синхронизацией субтитров по вокалу (Whisper AI),
    поддержкой режимов (phrase, word, karaoke), настраиваемой позицией и фильтрами.
    """
    output_path = config.OUTPUT_DIR / output_filename
    temp_dir = config.OUTPUT_DIR / f"temp_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    audio_clip = None
    video_clip = None
    final_clip = None
    vignette_clip = None
    subtitle_clips = []
    
    try:
        # 1. Загружаем и обрезаем аудио с плавными фейдами
        audio_clip = AudioFileClip(audio_path)
        audio_clip = audio_clip.subclipped(start_time, end_time)
        duration = audio_clip.duration
        audio_clip = audio_clip.with_effects([AudioFadeIn(0.5), AudioFadeOut(1.0)])
        
        # 2. Загружаем видеофутаж и сразу масштабируем гигантские 4K/2K видео для скорости
        video_clip = VideoFileClip(video_path)
        w_orig, h_orig = video_clip.size
        if max(w_orig, h_orig) > 1280:
            scale_factor = 1280.0 / max(w_orig, h_orig)
            video_clip = video_clip.with_effects([Resize(new_size=(int(w_orig * scale_factor), int(h_orig * scale_factor)))])

        if video_clip.duration < duration:
            video_clip = video_clip.with_effects([Loop(duration=duration)])
        else:
            video_clip = video_clip.subclipped(0, duration)
            
        video_clip = video_clip.without_audio()


        # Применяем выбранный видеоэффект
        if video_filter and video_filter != "none":
            video_clip = apply_video_filter(video_clip, video_filter)
        
        # 3. Вертикальное кадрирование 9:16 (720x1280)
        target_w, target_h = 720, 1280
        w, h = video_clip.size
        
        if vertical_crop:
            aspect_ratio_target = target_w / target_h
            aspect_ratio_video = w / h
            
            if aspect_ratio_video > aspect_ratio_target:
                crop_w = h * aspect_ratio_target
                x1 = (w - crop_w) / 2
                x2 = x1 + crop_w
                video_clip = video_clip.with_effects([Crop(x1=x1, x2=x2, y1=0, y2=h)])
            elif aspect_ratio_video < aspect_ratio_target:
                crop_h = w / aspect_ratio_target
                y1 = (h - crop_h) / 2
                y2 = y1 + crop_h
                video_clip = video_clip.with_effects([Crop(x1=0, x2=w, y1=y1, y2=y2)])
                
            video_clip = video_clip.with_effects([Resize(new_size=(target_w, target_h))])
            w, h = target_w, target_h

            # 3.1. Умная очистка чужих ватермарок (Smart Crop 6% Zoom)
            if remove_watermark:
                zoom_factor = 1.06
                crop_w = target_w / zoom_factor
                crop_h = target_h / zoom_factor
                cx1 = (target_w - crop_w) / 2
                cx2 = cx1 + crop_w
                cy1 = (target_h - crop_h) / 2
                cy2 = cy1 + crop_h
                video_clip = video_clip.with_effects([
                    Crop(x1=cx1, x2=cx2, y1=cy1, y2=cy2),
                    Resize(new_size=(target_w, target_h))
                ])
        
        # 4. Кинематографичная виньетка
        vignette_path = temp_dir / "vignette.png"
        create_vignette_image(w, h, str(vignette_path))
        vignette_clip = ImageClip(str(vignette_path)).with_duration(duration).with_position(("center", "center"))

        # 5. Генерируем субтитры
        font_size = int(h * 0.048) if (subtitle_mode or "").lower() == "phrase" else int(h * 0.052)
        clip_counter = 0
        style_clean = (subtitle_style or "tiktok").lower().strip()

        # Расчет вертикальной позиции y_ratio
        pos_clean = (subtitle_position or "bottom").lower().strip()
        if pos_clean == "top":
            pos_y_ratio = 0.35
        elif pos_clean == "center":
            pos_y_ratio = 0.55
        else: # bottom
            pos_y_ratio = 0.72

        if style_clean not in ["none", "off", "disabled"]:
            # Шаг 5.1. Получение пословного тайминга с выравниванием по звуку
            word_items = []
            if lyrics:
                # Пробуем Whisper Forced Alignment для выравнивания текста по реальному вокалу
                aligned = align_lyrics_with_whisper(lyrics, audio_path, start_time, end_time)
                if aligned:
                    word_items = aligned
                else:
                    # Фолбек: если выравнивание не удалось — нарезаем ручной текст по расчетной длительности
                    for item in lyrics:
                        raw_s = float(item["start"])
                        raw_e = float(item.get("end", raw_s + 3.0))
                        if start_time > 0 and raw_s >= start_time - 0.5:
                            line_s = raw_s - start_time
                            line_e = raw_e - start_time
                        else:
                            line_s = raw_s
                            line_e = raw_e
                        line_words = split_line_into_words(line_s, line_e, item["text"])
                        word_items.extend(line_words)
                    if not word_items:
                        word_items = transcribe_audio_segment(audio_path, start_time, end_time)
            else:
                # Если текста нет — авто-распознавание с помощью Whisper AI на слух
                word_items = transcribe_audio_segment(audio_path, start_time, end_time)



            # Сдвиг таймингов относительно start_time и фильтрация границ
            shifted_words = []
            for item in word_items:
                ws = float(item["start"])
                we = float(item["end"])
                # Если тайминги в lyrics еще в абсолютных секундах полного трека — сдвигаем к 0.0
                if start_time > 0 and ws >= start_time - 0.5:
                    ws -= start_time
                    we -= start_time

                txt = item["text"].strip()
                if not txt:
                    continue
                if we <= 0 or ws >= duration:
                    continue
                ws = max(0.0, ws)
                we = min(duration, we)
                if we - ws >= 0.12:
                    shifted_words.append({"start": round(ws, 2), "end": round(we, 2), "text": txt})


            shifted_words.sort(key=lambda x: x["start"])

            # Шаг 5.2. Рендеринг в зависимости от режима (phrase / word / karaoke)
            mode_clean = (subtitle_mode or "phrase").lower().strip()

            if mode_clean == "word":
                # Режим 1 слово за раз (Pop Single Word)
                for item in shifted_words:
                    png_path = temp_dir / f"sub_{clip_counter}.png"
                    clip_counter += 1
                    create_subtitle_image(item["text"], w, h, config.FONT_PATH, font_size, str(png_path), 
                                          style=style_clean, pos_y_ratio=pos_y_ratio)
                    
                    w_clip = (ImageClip(str(png_path))
                              .with_start(item["start"])
                              .with_end(item["end"])
                              .with_position(("center", "center")))
                    subtitle_clips.append(w_clip)

            elif mode_clean == "karaoke":
                # Режим полного караоке: подсвечивает текущее звучащее слово внутри строки
                phrases = chunk_words_into_phrases(shifted_words, max_words=3)
                for chunk in phrases:
                    chunk_text = chunk["text"]
                    c_words = chunk["words"]
                    for idx, w_item in enumerate(c_words):
                        png_path = temp_dir / f"sub_{clip_counter}.png"
                        clip_counter += 1
                        create_subtitle_image(chunk_text, w, h, config.FONT_PATH, font_size, str(png_path), 
                                              style=style_clean, pos_y_ratio=pos_y_ratio, active_word_index=idx)
                        
                        w_clip = (ImageClip(str(png_path))
                                  .with_start(w_item["start"])
                                  .with_end(w_item["end"])
                                  .with_position(("center", "center")))
                        subtitle_clips.append(w_clip)

            else:  # phrase (По умолчанию: Чанки по 2–3 слова)
                phrases = chunk_words_into_phrases(shifted_words, max_words=3)
                for chunk in phrases:
                    png_path = temp_dir / f"sub_{clip_counter}.png"
                    clip_counter += 1
                    create_subtitle_image(chunk["text"], w, h, config.FONT_PATH, font_size, str(png_path), 
                                          style=style_clean, pos_y_ratio=pos_y_ratio)
                    
                    w_clip = (ImageClip(str(png_path))
                              .with_start(chunk["start"])
                              .with_end(chunk["end"])
                              .with_position(("center", "center")))
                    subtitle_clips.append(w_clip)

            
        # 6. Сборка видео
        layers = [video_clip, vignette_clip] + subtitle_clips
        final_clip = CompositeVideoClip(layers).with_audio(audio_clip)
        
        # 7. Ультрабыстрый многопоточный рендеринг MP4 (ultrafast + 8 threads)
        final_clip.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            preset="ultrafast",
            threads=8,
            audio_codec="aac",
            ffmpeg_params=["-crf", "23", "-preset", "ultrafast"],
            temp_audiofile=str(temp_dir / "temp_audio.m4a"),
            remove_temp=True,
            logger=None
        )

        return str(output_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def build_hooks_concatenated_clip(hooks_paths: list, target_duration: float):
    """
    Склеивает короткие хуки (1-10 сек) в один бесшовный ролик нужной длины target_duration.
    """
    if not hooks_paths:
        raise ValueError("Нет видео-хуков в списке")
        
    accumulated_clips = []
    current_duration = 0.0
    
    available_paths = list(hooks_paths)
    random.shuffle(available_paths)
    
    idx = 0
    while current_duration < target_duration:
        path = available_paths[idx % len(available_paths)]
        clip = VideoFileClip(str(path))
        
        needed = target_duration - current_duration
        if clip.duration > needed + 0.1:
            clip = clip.subclipped(0, needed)
            
        accumulated_clips.append(clip)
        current_duration += clip.duration
        idx += 1
        
        if current_duration >= target_duration - 0.05:
            break
            
    if len(accumulated_clips) == 1:
        return accumulated_clips[0]
        
    from moviepy import concatenate_videoclips
    final_hooks_clip = concatenate_videoclips(accumulated_clips, method="compose")
    return final_hooks_clip.subclipped(0, target_duration)

def build_boomerang_influencer_clip(influencer_path: str, target_dur: float) -> VideoFileClip:
    """
    Если видео инфлюенсера короче target_dur (например 10с при требуемых 20с),
    создает видео с эффектом бумеранга (прямой ход -> реверс -> прямой ход)
    ровно до нужного хронометража target_dur без рывков.
    """
    clip = VideoFileClip(influencer_path)
    if clip.duration >= target_dur - 0.1:
        return clip.subclipped(0, target_dur)

    from moviepy import concatenate_videoclips, vfx
    
    # Реверсный вариант ролика (обратный эффект бумеранга)
    reversed_clip = clip.with_effects([vfx.TimeMirror()])
    
    accumulated = []
    curr_dur = 0.0
    idx = 0

    while curr_dur < target_dur - 0.05:
        c = clip if (idx % 2 == 0) else reversed_clip
        needed = target_dur - curr_dur
        if c.duration > needed + 0.05:
            accumulated.append(c.subclipped(0, needed))
            curr_dur += needed
        else:
            accumulated.append(c)
            curr_dur += c.duration
        idx += 1

    if len(accumulated) == 1:
        return accumulated[0]

    final_inf_clip = concatenate_videoclips(accumulated, method="compose")
    return final_inf_clip.subclipped(0, target_dur)

def render_split_screen_reaction(
    top_video_path: Any,
    bottom_influencer_path: str,
    output_filename: str,
    layout: str = "split50",
    target_dur: float = 20.0
) -> str:
    """
    Создает вертикальное 9:16 видео реакции ИИ-Инфлюенсера (Split-Screen).
    Поддерживает одиночный футаж или список видео-хуков (с авто-склейкой и бумерангом до заданной длины, например 20с).
    """
    output_dir = config.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename
    
    target_w, target_h = 720, 1280
    target_dur = float(target_dur)

    influencer_clip = build_boomerang_influencer_clip(bottom_influencer_path, target_dur)

    # Если передан список путей (например, несколько хуков по 1-5 сек)
    if isinstance(top_video_path, list):
        top_clip = build_hooks_concatenated_clip(top_video_path, target_dur)
    else:
        top_clip = VideoFileClip(str(top_video_path))
        if top_clip.duration < target_dur:
            # Если 1 хук/сниппет короче target_dur, дублируем/зацикливаем до нужной длины
            top_clip = build_hooks_concatenated_clip([top_video_path], target_dur)
        else:
            top_clip = top_clip.subclipped(0, target_dur)


    influencer_clip = influencer_clip.subclipped(0, target_dur)

    if layout in ["split50", "split70_top", "split30_top"]:
        if layout == "split70_top":
            top_h = int(target_h * 0.70) # 896
            bottom_h = target_h - top_h   # 384
        elif layout == "split30_top":
            top_h = int(target_h * 0.30) # 384
            bottom_h = target_h - top_h   # 896
        else:
            top_h = target_h // 2        # 640
            bottom_h = target_h // 2     # 640

        aspect_target_top = target_w / top_h
        aspect_target_bottom = target_w / bottom_h
        
        # 1. Верхнее видео (Сниппет / Футаж / Набор хуков)
        w, h = top_clip.size
        aspect_top = w / h
        if aspect_top > aspect_target_top:
            crop_w = h * aspect_target_top
            x1 = (w - crop_w) / 2
            top_crop = top_clip.with_effects([Crop(x1=x1, x2=x1+crop_w, y1=0, y2=h), Resize(new_size=(target_w, top_h))])
        else:
            crop_h = w / aspect_target_top
            y1 = max(0, (h - crop_h) * 0.70)
            top_crop = top_clip.with_effects([Crop(x1=0, x2=w, y1=y1, y2=y1+crop_h), Resize(new_size=(target_w, top_h))])
        top_crop = top_crop.with_position((0, 0))

        # 2. Нижнее видео (ИИ-Инфлюенсер)
        w_i, h_i = influencer_clip.size
        aspect_inf = w_i / h_i
        if aspect_inf > aspect_target_bottom:
            crop_wi = h_i * aspect_target_bottom
            x1_i = (w_i - crop_wi) / 2
            inf_crop = influencer_clip.with_effects([Crop(x1=x1_i, x2=x1_i+crop_wi, y1=0, y2=h_i), Resize(new_size=(target_w, bottom_h))])
        else:
            crop_hi = w_i / aspect_target_bottom
            y1_i = max(0, (h_i - crop_hi) * 0.35)
            inf_crop = influencer_clip.with_effects([Crop(x1=0, x2=w_i, y1=y1_i, y2=y1_i+crop_hi), Resize(new_size=(target_w, bottom_h))])
        inf_crop = inf_crop.with_position((0, top_h))

        final_clip = CompositeVideoClip([top_crop, inf_crop], size=(target_w, target_h))
        if top_clip.audio:
            final_clip = final_clip.with_audio(top_clip.audio)

    else:
        # Fullscreen 9:16 background footage + floating Avatar reaction box/circle
        w, h = top_clip.size
        crop_w = h * (target_w / target_h)
        x1 = max(0, (w - crop_w) / 2)
        bg = top_clip.with_effects([Crop(x1=x1, x2=min(w, x1+crop_w), y1=0, y2=h), Resize(new_size=(target_w, target_h))])
        
        inf_w, inf_h = 260, 340
        w_i, h_i = influencer_clip.size
        crop_wi = h_i * (inf_w / inf_h)
        x1_i = max(0, (w_i - crop_wi) / 2)
        inf_box = influencer_clip.with_effects([Crop(x1=x1_i, x2=min(w_i, x1_i+crop_wi), y1=0, y2=h_i), Resize(new_size=(inf_w, inf_h))])
        inf_box = inf_box.with_position((target_w - inf_w - 30, target_h - inf_h - 60))

        final_clip = CompositeVideoClip([bg, inf_box], size=(target_w, target_h))
        if top_clip.audio:
            final_clip = final_clip.with_audio(top_clip.audio)


    final_clip.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        preset="ultrafast",
        threads=8,
        audio_codec="aac",
        logger=None
    )
    top_clip.close()
    influencer_clip.close()
    return str(output_path)



