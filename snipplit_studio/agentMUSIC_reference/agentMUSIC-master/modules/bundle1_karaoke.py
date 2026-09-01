"""
Bundle 1: Караоке в стиле Apple Music.

Непрерывный скроллинг — все строки видны одновременно:
  - ВСЕ строки присутствуют на экране как лента текста
  - Активная строка: яркая белая, чуть выше центра
  - Пропетые строки тускнеют и уезжают вверх
  - Будущие строки тускло видны снизу
  - Плавный scroll + плавное изменение яркости
"""

import os
import logging
import random
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional

from .types import LyricsLine, WordTiming
from .utils import get_media_duration, RESOLUTIONS

logger = logging.getLogger(__name__)


@dataclass
class KaraokeResult:
    output_path: str


@dataclass
class DisplayLine:
    text: str
    start: float
    end: float
    index: int
    words: list[WordTiming] = None

    def __post_init__(self):
        if self.words is None:
            self.words = []


# Приблизительное соотношение ширины символа к fontsize (для латиницы/кириллицы)
CHAR_WIDTH_RATIO = 0.55


COLOR_GRADES = {
    "nature": "colorbalance=rs=0.05:gs=0.08:bs=-0.06:rm=0.03:gm=0.05:bm=-0.04",
    "warm":   "colorbalance=rs=0.12:gs=0.04:bs=-0.10:rm=0.08:gm=0.02:bm=-0.06",
    "cool":   "colorbalance=rs=-0.08:gs=0.02:bs=0.12:rm=-0.05:gm=0.01:bm=0.08",
    "golden": "colorbalance=rs=0.08:gs=0.05:bs=-0.06:rm=0.06:gm=0.03:bm=-0.04",
    "night":  "colorbalance=rs=0.02:gs=-0.04:bs=0.10:rm=0.04:gm=-0.02:bm=0.08",
}


def _detect_footage_tone(video_path: str) -> str:
    try:
        cmd = [
            "ffmpeg", "-i", video_path, "-vframes", "30",
            "-vf", "signalstats,metadata=print:key=lavfi.signalstats.HUEAVG",
            "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        hues = []
        for ln in r.stderr.split("\n"):
            if "HUEAVG" in ln:
                try:
                    hues.append(float(ln.split("=")[-1].strip()))
                except (ValueError, IndexError):
                    pass
        if not hues:
            return "golden"
        h = sum(hues) / len(hues)
        if 70 <= h <= 170:
            return "nature"
        if 200 <= h <= 270:
            return "warm"
        if h < 40 or h > 340:
            return "cool"
        if 40 <= h < 70:
            return "night"
        return "golden"
    except Exception:
        return "golden"


def _find_font(fonts_dir: str) -> Optional[str]:
    if os.path.isdir(fonts_dir):
        for fn in sorted(os.listdir(fonts_dir)):
            if fn.lower().endswith((".ttf", ".otf")):
                return os.path.join(fonts_dir, fn)
    for fb in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.exists(fb):
            return fb
    return None


def _esc(path: str) -> str:
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


def _prepare_display_lines(
    lyrics: list[LyricsLine], max_chars: int,
) -> list[DisplayLine]:
    """Разбивает длинные строки, возвращает плоский список DisplayLine с word timings."""
    display = []
    idx = 0
    for line in lyrics:
        sub_lines = _wrap_text(line.text, max_chars)
        dur = line.end - line.start
        sub_dur = dur / len(sub_lines) if sub_lines else dur

        # Распределяем слова по sub-lines
        all_words = list(line.words) if line.words else []
        word_cursor = 0

        for j, text in enumerate(sub_lines):
            sub_start = line.start + j * sub_dur
            sub_end = line.start + (j + 1) * sub_dur
            sub_word_count = len(text.split())

            # Забираем нужное кол-во слов из общего списка
            sub_words = all_words[word_cursor:word_cursor + sub_word_count]
            word_cursor += sub_word_count

            display.append(DisplayLine(
                text=text,
                start=sub_start,
                end=sub_end,
                index=idx,
                words=sub_words,
            ))
            idx += 1
    return display


# ---------------------------------------------------------------------------
#  ffmpeg expression builders
# ---------------------------------------------------------------------------

def _build_piecewise_expr(keyframes: list[tuple[float, float]]) -> str:
    """
    Строит кусочно-линейное ffmpeg-выражение из keyframes [(time, value), ...].
    Результат — строка для использования ВНУТРИ '...' (без экранирования запятых).
    """
    if not keyframes:
        return "0"
    if len(keyframes) == 1:
        return f"{keyframes[0][1]:.1f}"

    # Строим справа налево: самый вложенный else — последнее значение
    expr = f"{keyframes[-1][1]:.2f}"
    for k in range(len(keyframes) - 2, -1, -1):
        t0, v0 = keyframes[k]
        t1, v1 = keyframes[k + 1]
        dt = t1 - t0
        if dt < 0.001:
            lerp = f"{v1:.2f}"
        else:
            dv = v1 - v0
            if abs(dv) < 0.001:
                # Постоянное значение — не нужна интерполяция
                lerp = f"{v0:.2f}"
            else:
                lerp = f"({v0:.2f}+{dv:.4f}*(t-{t0:.3f})/{dt:.4f})"
        expr = f"if(lt(t,{t1:.3f}),{lerp},{expr})"
    return expr


def _smooth_keyframes(
    keyframes: list[tuple[float, float]], trans: float,
) -> list[tuple[float, float]]:
    """
    Добавляет точки «hold before transition» для плавного перехода.
    Вместо мгновенного скачка значение держится, потом плавно меняется за trans секунд.
    """
    if len(keyframes) <= 1:
        return list(keyframes)

    result = [keyframes[0]]
    for k in range(1, len(keyframes)):
        t_prev, v_prev = result[-1]
        t_cur, v_cur = keyframes[k]

        if abs(v_cur - v_prev) > 0.001:
            t_hold = max(t_prev + 0.01, t_cur - trans)
            if t_hold > result[-1][0] + 0.01:
                result.append((t_hold, v_prev))

        result.append((t_cur, v_cur))

    return result


# ---------------------------------------------------------------------------
#  Основной построитель фильтров
# ---------------------------------------------------------------------------

def _alpha_for_dist(d: int) -> float:
    """Alpha по расстоянию от активной строки — плавный градиент."""
    if d == 0:
        return 1.0
    if d == 1:
        return 0.50
    if d == 2:
        return 0.32
    if d == 3:
        return 0.20
    if d == 4:
        return 0.12
    return 0.07


def _word_x_positions(line_text: str, words: list[WordTiming], fontsize: int, tw: int) -> list[tuple[str, float]]:
    """
    Возвращает [(word_text, x_pixel), ...] для каждого слова в строке.
    Расчёт: центрируем строку, затем раскладываем слова последовательно.
    """
    char_w = fontsize * CHAR_WIDTH_RATIO
    line_w = len(line_text) * char_w
    x_start = max(0, (tw - line_w) / 2)

    result = []
    pos = 0
    line_words = line_text.split()
    for i, word_text in enumerate(line_words):
        # Находим позицию слова в строке (с учётом пробелов)
        word_idx = line_text.find(word_text, pos)
        if word_idx < 0:
            word_idx = pos
        x = x_start + word_idx * char_w
        result.append((word_text, x))
        pos = word_idx + len(word_text)
    return result


def _build_filters(
    lyrics: list[LyricsLine],
    font_path: Optional[str],
    tw: int, th: int,
    session_id: str,
    style: Optional[dict] = None,
) -> str:
    """
    Apple Music стиль — непрерывный скролл.

    Эталон: все строки видны, активная крупная и яркая по центру,
    контекстные строки мельче и тусклее, плавный непрерывный скролл вверх.

    Два слоя на строку:
      1) Тусклый контекстный слой (мелкий шрифт, приглушённый цвет)
      2) Яркий активный слой поверх (крупный шрифт, яркий цвет)
         с alpha, которая пиково = 1 когда строка активна, и 0 когда нет
    """
    if not lyrics:
        return ""

    tmp = os.path.join(tempfile.gettempdir(), f"am_{session_id}")
    os.makedirs(tmp, exist_ok=True)

    mx = int(tw * 0.05)
    safe_top = int(th * 0.04)
    safe_bottom = th - int(th * 0.10)

    # Размеры шрифта: активный крупный, контекст мельче
    fs_active = 56
    fs_context = 46

    max_chars = max(8, int((tw - 2 * mx) / (fs_active * 0.65)))
    gap = int(fs_active * 2.0)

    # Активная строка — по центру экрана
    y_center = safe_top + int((safe_bottom - safe_top) * 0.50)

    display = _prepare_display_lines(lyrics, max_chars)
    if not display:
        return ""

    N = len(display)
    TRANS = 0.45      # секунды на плавный переход
    LEAD = 0.8        # lead-in/out

    fp = ""
    if font_path:
        fp = f":fontfile='{_esc(font_path)}'"

    x_expr = f"max(0\\,(w-text_w)/2)"

    # Цвета из стиля или дефолтные
    color_active = (style or {}).get("color_active", "0xF5E6D0")
    color_context = (style or {}).get("color_context", "0x9B8B7A")
    border_color = (style or {}).get("border_color", "black@0.3")
    shadow_color = (style or {}).get("shadow_color", "black@0.3")

    t_first = display[0].start
    t_last_end = display[-1].end

    filters = []
    fi = 0

    for i in range(N):
        # === Y keyframes (общие для обоих слоёв) ===
        y_kf = []
        y_kf.append((max(0.0, t_first - LEAD), float(y_center + i * gap)))
        for j in range(N):
            y_kf.append((display[j].start, float(y_center + (i - j) * gap)))
        y_kf.append((t_last_end + LEAD, float(y_center + (i - (N - 1)) * gap)))

        smooth_y = _smooth_keyframes(y_kf, TRANS)
        y_expr_line = _build_piecewise_expr(smooth_y)

        vis_start = max(0.0, t_first - LEAD - 0.1)
        vis_end = t_last_end + LEAD + 0.1

        # Текст в файлы (один для каждого слоя)
        p1 = os.path.join(tmp, f"w_{fi:04d}.txt")
        with open(p1, "w", encoding="utf-8") as f:
            f.write(display[i].text)
        fi += 1
        ep1 = _esc(p1)

        p2 = os.path.join(tmp, f"w_{fi:04d}.txt")
        with open(p2, "w", encoding="utf-8") as f:
            f.write(display[i].text)
        fi += 1
        ep2 = _esc(p2)

        # === СЛОЙ 1: Контекстный (всегда видимый, мелкий, тусклый) ===
        # Alpha: плавный градиент, НО = 0 когда строка активна (чтобы не двоилось)
        a_kf_ctx = []
        initial_alpha = _alpha_for_dist(i) if i != 0 else 0.0
        a_kf_ctx.append((max(0.0, t_first - LEAD), 0.0))
        a_kf_ctx.append((max(0.01, t_first - LEAD * 0.3), initial_alpha))
        for j in range(N):
            dist = abs(i - j)
            # Когда строка активна (dist=0) — контекст скрываем, показываем только яркий слой
            ctx_alpha = 0.0 if dist == 0 else _alpha_for_dist(dist)
            a_kf_ctx.append((display[j].start, ctx_alpha))
        final_alpha = _alpha_for_dist(abs(i - (N - 1))) if i != N - 1 else 0.0
        a_kf_ctx.append((t_last_end, final_alpha))
        a_kf_ctx.append((t_last_end + LEAD, 0.0))
        smooth_a_ctx = _smooth_keyframes(a_kf_ctx, TRANS * 0.7)
        a_expr_ctx = _build_piecewise_expr(smooth_a_ctx)

        filters.append(
            f"drawtext=textfile='{ep1}'"
            f":fontsize={fs_context}:fontcolor={color_context}"
            f":borderw=0"
            f":x={x_expr}"
            f":y='{y_expr_line}'"
            f":alpha='{a_expr_ctx}'"
            f"{fp}"
            f":enable='between(t,{vis_start:.3f},{vis_end:.3f})'"
        )

        # === СЛОЙ 2: Активный (яркий, крупный, поверх контекстного) ===
        a_kf_act = []
        a_kf_act.append((max(0.0, t_first - LEAD), 0.0))
        for j in range(N):
            if j == i:
                a_kf_act.append((display[j].start, 1.0))
            else:
                a_kf_act.append((display[j].start, 0.0))
        a_kf_act.append((t_last_end, 0.0))
        a_kf_act.append((t_last_end + LEAD, 0.0))
        smooth_a_act = _smooth_keyframes(a_kf_act, TRANS * 0.7)
        a_expr_act = _build_piecewise_expr(smooth_a_act)

        y_offset = int((fs_active - fs_context) * 0.4)
        y_expr_active = f"({y_expr_line}-{y_offset})"

        filters.append(
            f"drawtext=textfile='{ep2}'"
            f":fontsize={fs_active}:fontcolor={color_active}"
            f":borderw=3:bordercolor={border_color}"
            f":shadowcolor={shadow_color}:shadowx=1:shadowy=2"
            f":x={x_expr}"
            f":y='{y_expr_active}'"
            f":alpha='{a_expr_act}'"
            f"{fp}"
            f":enable='between(t,{vis_start:.3f},{vis_end:.3f})'"
        )

    return ",".join(filters)


# ---------------------------------------------------------------------------
#  Сборка видео
# ---------------------------------------------------------------------------

def build_karaoke(
    lyrics_lines: list[LyricsLine],
    background_videos: Optional[list[str]],
    chorus_audio_path: str,
    output_dir: str,
    fonts_dir: str,
    orientation: str = "portrait",
    highlight_color: str = "0xFFD700",
    style: Optional[dict] = None,
    use_animated_bg: bool = False,
    palette_seed: int = 0,
) -> Optional[KaraokeResult]:
    """
    Если use_animated_bg=True или background_videos=None/пустой —
    генерирует анимированный фон через modules.animated_bg.
    """
    os.makedirs(output_dir, exist_ok=True)
    tw, th = RESOLUTIONS.get(orientation, (1080, 1920))

    if not lyrics_lines:
        logger.warning("Нет текста")
        return None

    sid = uuid.uuid4().hex[:8]
    out = os.path.join(output_dir, "karaoke.mp4")
    dur = get_media_duration(chorus_audio_path)
    font = _find_font(fonts_dir)

    # --- Выбор/генерация фона ---
    need_animated = use_animated_bg or not background_videos
    if need_animated:
        from .animated_bg import generate_animated_background
        bg = os.path.join(output_dir, f"animated_bg_{sid}.mp4")
        result = generate_animated_background(
            audio_path=chorus_audio_path,
            duration=dur,
            output_path=bg,
            width=tw, height=th, fps=30,
            palette_seed=palette_seed,
        )
        if not result:
            logger.error("Не удалось сгенерировать анимированный фон")
            return None
        bg, pal = result
        # Без цветокоррекции — фон уже стилизован
        grade = "null"
        # Palette-aware text glow: подкрашиваем обводку/тень под палитру фона
        if style is None:
            style = {}
        wave_hex = pal["wave"]  # e.g. "0xCFF5FF"
        if "border_color" not in style:
            style["border_color"] = f"{wave_hex}@0.35"
        if "shadow_color" not in style:
            style["shadow_color"] = f"{wave_hex}@0.50"
        logger.info(f"Караоке: использую анимированный фон (palette_seed={palette_seed})")
    else:
        bg = random.choice(background_videos)
        tone = _detect_footage_tone(bg)
        grade = COLOR_GRADES.get(tone, COLOR_GRADES["golden"])
        logger.info(f"Караоке: тон={tone}")

    try:
        vd = get_media_duration(bg)
    except RuntimeError:
        return None

    loop = ["-stream_loop", str(int(dur / vd) + 1)] if vd < dur else []

    vf = (
        f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},setsar=1,"
        f"{grade},"
        f"eq=brightness=-0.15:saturation=0.95:contrast=1.05,"
        f"unsharp=3:3:0.3"
    )

    dt = _build_filters(lyrics_lines, font, tw, th, sid, style=style)
    if dt:
        vf += f",{dt}"
    vf += "[v]"

    # Пишем filter_complex в файл (избегаем Argument list too long)
    fc_path = os.path.join(output_dir, "filter_complex.txt")
    with open(fc_path, "w", encoding="utf-8") as f:
        f.write(vf)

    cmd = [
        "ffmpeg", "-y", *loop,
        "-i", bg, "-i", chorus_audio_path,
        "-filter_complex_script", fc_path,
        "-map", "[v]", "-map", "1:a",
        "-t", str(dur),
        "-threads", "0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        out,
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            logger.info(f"Караоке готово: {out}")
            return KaraokeResult(output_path=out)
        else:
            logger.error(f"ffmpeg fail: {r.stderr[-500:]}")
            return None
    except Exception as e:
        logger.error(f"Караоке error: {e}")
        return None
