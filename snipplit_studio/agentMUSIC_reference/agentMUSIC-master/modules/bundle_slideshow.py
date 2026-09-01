"""
Bundle Slideshow: Mood Slideshow.

Каждая строка припева отображается на своём фоне (разные футажи).
Длительность кадра подстраивается под реальный тайминг строки (обычно 2–3 сек).
Плавные xfade-переходы между кадрами, текст с fade in/out по центру.
"""

import os
import logging
import random
import subprocess
import uuid
from dataclasses import dataclass
from typing import Optional

from .types import LyricsLine
from .utils import get_media_duration, RESOLUTIONS

logger = logging.getLogger(__name__)


@dataclass
class SlideshowResult:
    output_path: str


# Ограничения длительности одного кадра (для защиты от слишком коротких/длинных строк)
MIN_SEG_DUR = 1.8
MAX_SEG_DUR = 4.5

# Длительность xfade-перехода между сегментами
XFADE_DUR = 0.55

# Длительность fade in/out у текста
TEXT_FADE = 0.35

# Лёгкая цветокоррекция для разнообразия фонов
COLOR_GRADES = [
    "colorbalance=rs=0.08:gs=0.05:bs=-0.06",   # warm/golden
    "colorbalance=rs=-0.06:gs=0.02:bs=0.10",   # cool
    "colorbalance=rs=0.05:gs=0.08:bs=-0.04",   # nature
    "colorbalance=rs=0.10:gs=0.03:bs=-0.08",   # sunset
    "colorbalance=rs=-0.04:gs=-0.02:bs=0.08",  # night
]


def _find_font(fonts_dir: str) -> Optional[str]:
    if os.path.isdir(fonts_dir):
        for fn in sorted(os.listdir(fonts_dir)):
            if fn.lower().endswith((".ttf", ".otf")):
                return os.path.join(fonts_dir, fn)
    for fb in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(fb):
            return fb
    return None


def _esc(path: str) -> str:
    """Экранирование пути для аргументов ffmpeg-фильтров."""
    return path.replace("\\", "/").replace("'", "'\\''").replace(":", "\\:")


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _compute_segments(lyrics: list[LyricsLine], total_dur: float) -> list[tuple[float, float]]:
    """
    Возвращает [(start, end), ...] для каждой строки, синхронизировано с audio.
    Диапазоны выравниваются: первый начинается с 0, последний заканчивается total_dur,
    границы между соседними совпадают (чтобы кадры шли без дыр).
    """
    if not lyrics:
        return []
    n = len(lyrics)
    raw = []
    for i, line in enumerate(lyrics):
        s = max(0.0, line.start)
        if i + 1 < n:
            e = lyrics[i + 1].start
        else:
            e = max(line.end, total_dur)
        raw.append([s, e])
    raw[0][0] = 0.0
    raw[-1][1] = max(raw[-1][1], total_dur)
    # не даём сегменту быть слишком длинным
    for i in range(n):
        s, e = raw[i]
        if e - s > MAX_SEG_DUR:
            raw[i][1] = s + MAX_SEG_DUR
            if i + 1 < n:
                raw[i + 1][0] = raw[i][1]
    return [(s, e) for s, e in raw]


def _render_segment(
    bg_path: str,
    text: str,
    duration: float,
    out_path: str,
    tw: int,
    th: int,
    font_path: Optional[str],
    style: dict,
    seg_index: int,
) -> bool:
    """
    Рендерит один сегмент слайдшоу:
      - масштабирует bg под tw × th (fill + crop)
      - применяет цветокоррекцию + лёгкую виньетку
      - медленно дрейфует кадр (псевдо Ken Burns) через crop со сдвигом по времени
      - выводит текст строки по центру с fade in/out
    """
    color_text = style.get("color_active", "0xFFFFFF")
    border_color = style.get("border_color", "black@0.55")
    shadow_color = style.get("shadow_color", "black@0.45")

    tw_e = tw & ~1
    th_e = th & ~1

    # Определяем, видео это или картинка
    is_image = bg_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp"))

    if is_image:
        bg_input = ["-loop", "1", "-t", f"{duration:.3f}", "-i", bg_path]
    else:
        try:
            vd = get_media_duration(bg_path)
        except RuntimeError:
            return False
        loops = int(duration / vd) + 1 if vd < duration else 0
        bg_input = (["-stream_loop", str(loops)] if loops else []) + ["-i", bg_path]

    # Лёгкий pan: сдвиг кадра по синусу/косинусу за время сегмента
    # Работаем в увеличенном холсте (1.08x) и кропаем с плавающим центром
    scale_factor = 1.08
    sw = int(tw_e * scale_factor) & ~1
    sh = int(th_e * scale_factor) & ~1
    dx = (sw - tw_e) // 2
    dy = (sh - th_e) // 2
    # Амплитуда дрейфа ~40% от запаса
    amp_x = max(6, int(dx * 0.8))
    amp_y = max(6, int(dy * 0.8))
    # Разные направления для соседних кадров (семя — seg_index)
    phase = (seg_index % 4)
    if phase == 0:
        x_expr = f"{dx}+{amp_x}*sin(t*0.7)"
        y_expr = f"{dy}-{amp_y}*cos(t*0.5)"
    elif phase == 1:
        x_expr = f"{dx}-{amp_x}*cos(t*0.6)"
        y_expr = f"{dy}+{amp_y}*sin(t*0.8)"
    elif phase == 2:
        x_expr = f"{dx}+{amp_x}*sin(t*0.9+0.5)"
        y_expr = f"{dy}+{amp_y}*sin(t*0.4+1.2)"
    else:
        x_expr = f"{dx}-{amp_x}*sin(t*0.55)"
        y_expr = f"{dy}-{amp_y}*cos(t*0.7+0.3)"

    grade = COLOR_GRADES[seg_index % len(COLOR_GRADES)]

    # Перенос длинных строк: ~ширина экрана / символ
    max_chars = max(10, int(tw_e / 46))
    wrapped = _wrap_text(text, max_chars)
    lines_count = len(wrapped)
    # Адаптивный размер шрифта
    if lines_count <= 1:
        fontsize = 78
    elif lines_count == 2:
        fontsize = 66
    else:
        fontsize = 56

    # Сохраняем текст в файл (обходит экранирование спецсимволов)
    txt_file = out_path + ".txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("\n".join(wrapped))

    fp = f":fontfile='{_esc(font_path)}'" if font_path else ""

    # Alpha для текста: fade in в начале, fade out в конце сегмента
    fin_end = TEXT_FADE
    fout_start = max(fin_end, duration - TEXT_FADE)
    alpha_expr = (
        f"if(lt(t,{fin_end:.3f}),"
        f"t/{fin_end:.3f},"
        f"if(gt(t,{fout_start:.3f}),"
        f"max(0,1-(t-{fout_start:.3f})/{TEXT_FADE:.3f}),"
        f"1))"
    )

    vf = (
        f"[0:v]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={sw}:{sh},setsar=1,"
        f"{grade},"
        f"eq=brightness=-0.08:saturation=1.08:contrast=1.06,"
        f"crop={tw_e}:{th_e}:x='{x_expr}':y='{y_expr}',"
        f"vignette=angle=PI/5,"
        f"format=yuv420p,"
        f"drawtext=textfile='{_esc(txt_file)}'"
        f":fontsize={fontsize}:fontcolor={color_text}"
        f":borderw=3:bordercolor={border_color}"
        f":shadowcolor={shadow_color}:shadowx=2:shadowy=3"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":alpha='{alpha_expr}'"
        f":line_spacing=14"
        f"{fp}"
        f"[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        *bg_input,
        "-filter_complex", vf,
        "-map", "[v]",
        "-t", f"{duration:.3f}",
        "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        out_path,
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            logger.error(f"Slideshow segment {seg_index} fail: {r.stderr[-400:]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Slideshow segment {seg_index} error: {e}")
        return False


def build_slideshow(
    lyrics_lines: list[LyricsLine],
    background_videos: list[str],
    chorus_audio_path: str,
    output_dir: str,
    fonts_dir: str,
    orientation: str = "portrait",
    style: Optional[dict] = None,
    palette_seed: int = 0,
) -> Optional[SlideshowResult]:
    """
    Mood Slideshow — каждая строка припева на своём фоновом кадре.
    Плавные xfade-переходы, текст появляется и исчезает мягко.
    """
    os.makedirs(output_dir, exist_ok=True)
    tw, th = RESOLUTIONS.get(orientation, (1080, 1920))

    if not lyrics_lines:
        logger.warning("Slideshow: нет текста")
        return None
    if not background_videos:
        logger.warning("Slideshow: нет фоновых видео")
        return None

    style = style or {}
    font = _find_font(fonts_dir)
    try:
        chorus_dur = get_media_duration(chorus_audio_path)
    except RuntimeError as e:
        logger.error(f"Slideshow: не могу прочитать chorus audio: {e}")
        return None

    segments = _compute_segments(lyrics_lines, chorus_dur)
    if not segments:
        return None

    # Тасуем фоны с seed для детерминированной «вариативности» между video_count итерациями
    bgs = list(background_videos)
    rng = random.Random(palette_seed)
    rng.shuffle(bgs)

    sid = uuid.uuid4().hex[:8]
    tmp_dir = os.path.join(output_dir, f"_slides_{sid}")
    os.makedirs(tmp_dir, exist_ok=True)

    seg_paths: list[str] = []
    seg_visible_durs: list[float] = []

    for i, ((s, e), line) in enumerate(zip(segments, lyrics_lines)):
        visible = max(MIN_SEG_DUR, min(MAX_SEG_DUR, e - s))
        # к длительности файла прибавляем запас под xfade-перекрытие
        file_dur = visible + (XFADE_DUR if i < len(segments) - 1 else 0.0)
        bg = bgs[i % len(bgs)]
        seg_out = os.path.join(tmp_dir, f"seg_{i:02d}.mp4")
        ok = _render_segment(
            bg_path=bg,
            text=line.text,
            duration=file_dur,
            out_path=seg_out,
            tw=tw,
            th=th,
            font_path=font,
            style=style,
            seg_index=i + palette_seed,
        )
        if not ok:
            logger.warning(f"Slideshow: сегмент {i} не сгенерился, пропускаю")
            continue
        seg_paths.append(seg_out)
        seg_visible_durs.append(visible)

    if not seg_paths:
        logger.error("Slideshow: ни один сегмент не сгенерировался")
        return None

    out_path = os.path.join(output_dir, "slideshow.mp4")

    # Склеивание: один сегмент → просто mux с audio; иначе xfade-цепочка
    if len(seg_paths) == 1:
        cmd = [
            "ffmpeg", "-y",
            "-i", seg_paths[0],
            "-i", chorus_audio_path,
            "-map", "0:v", "-map", "1:a",
            "-t", f"{chorus_dur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            out_path,
        ]
    else:
        inputs: list[str] = []
        for p in seg_paths:
            inputs.extend(["-i", p])
        inputs.extend(["-i", chorus_audio_path])

        filter_parts: list[str] = []
        prev_label = "0:v"
        offset = seg_visible_durs[0]
        for i in range(1, len(seg_paths)):
            out_label = f"v{i}"
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:"
                f"duration={XFADE_DUR}:offset={offset:.3f}[{out_label}]"
            )
            prev_label = out_label
            offset += seg_visible_durs[i]

        filter_complex = ";".join(filter_parts)
        audio_idx = len(seg_paths)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[{prev_label}]",
            "-map", f"{audio_idx}:a",
            "-t", f"{chorus_dur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            out_path,
        ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=400)
        if r.returncode == 0:
            logger.info(f"Slideshow готов: {out_path} ({len(seg_paths)} кадров)")
            return SlideshowResult(output_path=out_path)
        logger.error(f"Slideshow concat fail: {r.stderr[-600:]}")
        return None
    except Exception as e:
        logger.error(f"Slideshow concat error: {e}")
        return None
