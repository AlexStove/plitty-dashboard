"""
Bundle POV Spotify — mockup Spotify single-track screen как фон для промо-трека.

Виральный формат TikTok 2024-2026: зритель видит "скриншот" Spotify с обложкой,
названием трека, прогрессом и плеером → визуально убеждает "это реальный трек
на Spotify" → клик в bio-ссылку.

Layout (portrait 1080×1920) — ближе к референсу реального Spotify single-track:
  [top bar: ← back ...             ♡ heart]           y=90-140
  [COVER art 86% ширины, центр]                        y=230-1158
  [TRACK TITLE (большое, bold white)]                  y=1208
  [Singer (меньше, серое @0.6)]                        y=1308
  [прогресс-бар: зелёный fill + белый playhead]        y=1386
  [0:XX                                 -M:SS]         y=1408
  [♥  ⏮    ●PLAY(большой green)    ⏭  ★]               y=1548
  [mini-player footer: ●▶ Singer — Song Title]         y=1810

Fonts:
  - Montserrat-Bold — текст (Artist / Track / hook / timestamps)
  - DejaVu Sans Bold — unicode-иконки (← ♡ ♥ ▶ ★ ⏮ ⏭ ●)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from .types import LyricsLine
from .cta_overlay import _safe_text

logger = logging.getLogger(__name__)


# Fallback символьных шрифтов — DejaVu на Linux/Debian, Arial Unicode на macOS.
SYMBOL_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/seguisym.ttf",
]


def _find_symbol_font(fallback: str) -> str:
    for p in SYMBOL_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return fallback


@dataclass
class POVSpotifyConfig:
    audio_path: str
    lyrics: list[LyricsLine]
    output_path: str
    font_path: str
    duration: float = 21.0
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    track_name: str = ""
    artist_name: str = ""
    cover_path: Optional[str] = None
    palette_name: str = "default"
    hook_phrase: str = "found this on spotify"
    crf: int = 21
    preset: str = "veryfast"
    apply_loudnorm: bool = True
    loudnorm_target: float = -14.0
    loop_stitch: bool = True
    loop_stitch_duration: float = 0.5


# Фон — плоский Spotify-dark градиент (верх темнее низа).
POV_PALETTE_BG = {
    "sad-girl":   ("0x1B0A2E", "0x0B0416"),
    "trap":       ("0x251208", "0x0A0503"),
    "dark":       ("0x141421", "0x07070F"),
    "dream-pop":  ("0x10182E", "0x060A17"),
    "default":    ("0x151515", "0x070707"),
}

SPOTIFY_GREEN = "0x1DB954"


def _autofit(text: str, base: int, max_w: int) -> int:
    if not text:
        return base
    return max(32, min(base, int(max_w / max(1, len(text)) / 0.55)))


def _format_mmss(seconds: float) -> str:
    """Возвращает M:SS с экранированным двоеточием — FFmpeg drawtext
    иначе трактует ':' как разделитель параметров фильтра."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}\\:{s:02d}"


# ---------------------------------------------------------------------------
#  UI элементы
# ---------------------------------------------------------------------------


def _hook(cfg: POVSpotifyConfig) -> str:
    """Hook-фраза pattern interrupt 0-2.5с."""
    w, _h = cfg.resolution
    text = cfg.hook_phrase or "found this on spotify"
    fs = _autofit(text, 60, int(w * 0.86))
    return (
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(text)}'"
        f":fontsize={fs}:fontcolor=white"
        f":box=1:boxcolor=black@0.80:boxborderw=18"
        f":borderw=2:bordercolor={SPOTIFY_GREEN}"
        f":x=(w-text_w)/2:y=180"
        f":enable='between(t,0,2.5)'"
    )


def _track_labels_dynamic(
    cfg: POVSpotifyConfig, track_y: int, artist_y: int,
) -> list[str]:
    """
    TRACK TITLE (большое, белое) + Artist (меньше, серое).
    В оригинальном Spotify mockup оба текста ВЫРАВНЕНЫ ПО ЛЕВОМУ КРАЮ
    (x=25 в 366 wide UI → x=71 в 1080). Но для TikTok "POV Spotify"
    центрирование смотрится чище и универсальнее — ставим center.
    """
    w, _h = cfg.resolution
    out = []

    track_text = (cfg.track_name or "Unknown Track").strip()[:30]
    fs_t = _autofit(track_text, 72, int(w * 0.78))
    out.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(track_text)}'"
        f":fontsize={fs_t}:fontcolor=white"
        f":x=(w-text_w)/2:y={track_y}"
    )
    artist_text = (cfg.artist_name or "Unknown Artist").strip()[:40]
    fs_a = _autofit(artist_text, 40, int(w * 0.82))
    out.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(artist_text)}'"
        f":fontsize={fs_a}:fontcolor=white@0.65"
        f":x=(w-text_w)/2:y={artist_y}"
    )
    return out


def _progress_bar(cfg: POVSpotifyConfig, y_pos: int) -> list[str]:
    """
    Прогресс-бар (пиксель-точно под mockup):
      - серая подложка по всей ширине на y≈1512
      - зелёный fill растёт слева направо (30 step-boxes)
      - белый playhead бежит впереди green fill
    """
    w, _h = cfg.resolution
    bar_x = 70
    bar_w = w - 2 * bar_x                  # 940 — совпадает с линией в mockup'е
    bar_h = 8                              # толщина как в mockup'е
    out = []
    # Серая подложка (чуть приглушённее чем белая из mockup'а)
    out.append(
        f"drawbox=x={bar_x}:y={y_pos - bar_h // 2}:w={bar_w}:h={bar_h}"
        f":color=white@0.28:t=fill"
    )
    # Зелёный progress growing
    steps = 30
    step_dur = cfg.duration / max(1, steps)
    for i in range(1, steps + 1):
        t_start = (i - 1) * step_dur
        t_end = i * step_dur
        step_w = int(bar_w * i / steps)
        out.append(
            f"drawbox=x={bar_x}:y={y_pos - bar_h // 2}:w={step_w}:h={bar_h}"
            f":color={SPOTIFY_GREEN}:t=fill"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
    # Playhead — белый круг-точка, чуть больше толщины бара
    r = 12
    for i in range(1, steps + 1):
        t_start = (i - 1) * step_dur
        t_end = i * step_dur
        cx = bar_x + int(bar_w * (i - 0.5) / steps)
        out.append(
            f"drawbox=x={cx - r}:y={y_pos - r}"
            f":w={2 * r}:h={2 * r}:color=white:t=fill"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
    return out


def _timestamps(cfg: POVSpotifyConfig, y_pos: int) -> list[str]:
    """0:XX слева, -M:SS справа. Живые, тикают по секундам."""
    out = []
    total_sec = int(cfg.duration) + 1
    fs = 32
    for s in range(total_sec):
        t_start = float(s)
        t_end = float(s + 1)
        out.append(
            f"drawtext=fontfile='{cfg.font_path}'"
            f":text='{_format_mmss(s)}'"
            f":fontsize={fs}:fontcolor=white@0.75"
            f":x=70:y={y_pos}"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
        remain = max(0, cfg.duration - s)
        out.append(
            f"drawtext=fontfile='{cfg.font_path}'"
            f":text='-{_format_mmss(remain)}'"
            f":fontsize={fs}:fontcolor=white@0.75"
            f":x=w-tw-70:y={y_pos}"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
    return out


# ---------------------------------------------------------------------------
#  Main render
# ---------------------------------------------------------------------------


REMOTION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remotion",
)
REMOTION_ENTRY = os.path.join(REMOTION_DIR, "src", "index.ts")


def _render_via_remotion(cfg: "POVSpotifyConfig") -> Optional[str]:
    """
    Рендер POV Spotify через Remotion (React + CSS) — pixel-perfect UI.

    Шаги:
      1. Копируем cover и audio в remotion/public/pov_<uniq>/
      2. Формируем JSON props и сохраняем во временный файл
      3. Запускаем `npx remotion render` → mp4
      4. Перемещаем результат в cfg.output_path

    Возвращает путь к рендеру или None при ошибке (бросает исключение).
    """
    import json
    import shutil
    import uuid as _uuid

    public_dir = os.path.join(REMOTION_DIR, "public")
    os.makedirs(public_dir, exist_ok=True)

    uniq = _uuid.uuid4().hex[:10]
    cover_ext = os.path.splitext(cfg.cover_path)[1] or ".jpg"
    cover_rel = f"_pov/{uniq}_cover{cover_ext}"
    audio_rel = f"_pov/{uniq}_audio.mp3"
    cover_dst = os.path.join(public_dir, cover_rel)
    audio_dst = os.path.join(public_dir, audio_rel)
    os.makedirs(os.path.dirname(cover_dst), exist_ok=True)
    shutil.copy2(cfg.cover_path, cover_dst)
    shutil.copy2(cfg.audio_path, audio_dst)

    props = {
        "trackName": (cfg.track_name or "Unknown Track")[:40],
        "artistName": (cfg.artist_name or "Unknown Artist")[:40],
        "coverSrc": cover_rel,
        "audioSrc": audio_rel,
        "duration": float(cfg.duration),
    }

    props_file = os.path.join("/tmp", f"remotion_pov_{uniq}.json")
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    # Считаем frames = duration * fps (в remotion Root.tsx fps=30)
    frames = int(round(float(cfg.duration) * 30))

    cmd = [
        "npx", "remotion", "render",
        REMOTION_ENTRY, "PovSpotify",
        os.path.abspath(cfg.output_path),
        f"--props={props_file}",
        f"--frames=0-{frames - 1}",
        "--codec=h264",
        "--concurrency=4",
    ]
    logger.info(
        f"remotion render: '{props['artistName']} — {props['trackName']}' "
        f"{frames} frames → {cfg.output_path}"
    )
    try:
        r = subprocess.run(
            cmd, cwd=REMOTION_DIR, capture_output=True, text=True, timeout=600,
        )
    finally:
        # Чистим временные public-ассеты и props-файл (но не output)
        for p in (cover_dst, audio_dst, props_file):
            try:
                os.unlink(p)
            except OSError:
                pass

    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-3000:]
        raise RuntimeError(f"remotion render failed (rc={r.returncode}):\n{tail}")
    if not os.path.exists(cfg.output_path) or os.path.getsize(cfg.output_path) < 10000:
        raise RuntimeError(f"remotion output missing/tiny: {cfg.output_path}")
    return cfg.output_path


def build_pov_spotify(cfg: POVSpotifyConfig) -> str:
    if not os.path.exists(cfg.audio_path):
        raise RuntimeError(f"audio not found: {cfg.audio_path}")
    if not os.path.exists(cfg.font_path):
        raise RuntimeError(f"font not found: {cfg.font_path}")
    if not cfg.cover_path or not os.path.exists(cfg.cover_path):
        raise RuntimeError(
            "pov_spotify требует cover (для mockup'а). Загрузи трек с cover."
        )

    os.makedirs(os.path.dirname(os.path.abspath(cfg.output_path)) or ".", exist_ok=True)

    # --- Remotion render path (приоритет) ---
    remotion_deps = os.path.join(REMOTION_DIR, "node_modules", "remotion")
    if os.path.isdir(remotion_deps):
        try:
            _render_via_remotion(cfg)
            logger.info(
                f"build_pov_spotify (remotion) done: "
                f"{os.path.getsize(cfg.output_path)} bytes"
            )
            if cfg.loop_stitch and cfg.loop_stitch_duration > 0:
                try:
                    _apply_loop_stitch(cfg.output_path, cfg.loop_stitch_duration)
                except Exception as e:
                    logger.warning(f"pov_spotify loop-stitch skipped: {e}")
            return cfg.output_path
        except Exception as e:
            logger.warning(
                f"remotion render failed, fallback to ffmpeg path: {e}"
            )

    # --- Fallback: FFmpeg + PNG mockup ---
    w, h = cfg.resolution

    _, bg_bot = POV_PALETTE_BG.get(cfg.palette_name, POV_PALETTE_BG["default"])

    # Layout (1080×1920) — синхронно с scripts/prepare_pov_spotify_mockup.py.
    # Координаты сняты из presets.json оригинального mockup'а
    # (denzven/Spotify_Album_Cover_ScreenShot_Maker) и масштабированы 2.56×.
    cov_size = 938                              # квадрат, совпадает с UI шириной
    cov_x = (w - cov_size) // 2                 # 71
    cov_y = 240                                 # cover area
    track_y = 1330                              # song name baseline
    artist_y = 1417                             # artist name
    # Progress bar y≈1523, timestamps y≈1600, controls cy≈1743 —
    # эти элементы УЖЕ есть в mockup PNG и НЕ перерисовываются динамически
    # (наложение на статичные элементы mockup'а создавало визуальный мусор).

    # --- Реальный Spotify UI mockup (из GitHub)  ---
    # Скачан из https://github.com/denzven/Spotify_Album_Cover_ScreenShot_Maker
    # /raw/master/assets/ui/ui.png и обработан scripts/prepare_pov_spotify_mockup.py
    # (осветление тёмно-серого текста, scale 2.56×, центрирование на 1080×1920).
    frame_png = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "assets", "pov_spotify_real_frame.png",
    )
    frame_exists = os.path.exists(frame_png)

    # --- Filter graph ---
    parts = []
    parts.append(f"[1:v]scale={cov_size}:{cov_size},setsar=1[cov]")
    parts.append(f"[0:v][cov]overlay={cov_x}:{cov_y}[vcov]")

    # Если frame PNG есть — накладываем его (статичные UI элементы),
    # иначе fallback на старый drawtext/drawbox путь.
    if frame_exists:
        parts.append(f"[vcov][3:v]overlay=0:0[vframe]")
        base_label = "vframe"
    else:
        logger.warning(f"pov_spotify frame PNG отсутствует: {frame_png}")
        base_label = "vcov"

    overlays = []
    # Тень под обложкой — FFmpeg (для per-palette colour accent)
    overlays.append(
        f"drawbox=x={cov_x}:y={cov_y + cov_size}:w={cov_size}:h=12"
        f":color=black@0.45:t=fill"
    )

    # Только ДИНАМИЧЕСКИЕ элементы: title/artist, hook, progress+timestamps,
    # текст мини-плеера. Все статичные иконки — в PNG frame.
    overlays.append(_hook(cfg))
    overlays.extend(_track_labels_dynamic(cfg, track_y, artist_y))

    # --- Dynamic progress bar + timestamps ---
    # Координаты из анализа pov_spotify_real_frame.png (пиксель-точно):
    #   progress line: y=1508..1516 (8px)
    #   timestamps text: y=1541..1557
    #   play circle: center=(540, 1690), radius 80
    # Чтобы заменить статику на живые элементы: закрашиваем оригинальные
    # чёрным (full-width для надёжности), сверху рисуем свои.
    progress_y = 1512          # центр линии
    timestamp_y = 1544
    play_cx = w // 2
    play_cy = 1690

    # Mask static progress line
    overlays.append(
        f"drawbox=x=0:y=1500:w={w}:h=28"
        f":color=black:t=fill"
    )
    # Mask static timestamps
    overlays.append(
        f"drawbox=x=0:y=1532:w=280:h=40"
        f":color=black:t=fill"
    )
    overlays.append(
        f"drawbox=x={w - 280}:y=1532:w=280:h=40"
        f":color=black:t=fill"
    )
    # Draw dynamic
    overlays.extend(_progress_bar(cfg, progress_y))
    overlays.extend(_timestamps(cfg, timestamp_y))

    # PAUSE bars (чёрные) внутри белого play-круга
    bar_w = 16
    bar_h = 70
    bar_gap = 26
    overlays.append(
        f"drawbox=x={play_cx - bar_gap // 2 - bar_w}:y={play_cy - bar_h // 2}"
        f":w={bar_w}:h={bar_h}:color=black:t=fill"
    )
    overlays.append(
        f"drawbox=x={play_cx + bar_gap // 2}:y={play_cy - bar_h // 2}"
        f":w={bar_w}:h={bar_h}:color=black:t=fill"
    )

    chain = ",".join(overlays)
    parts.append(f"[{base_label}]{chain},format=yuv420p[vout]")
    filter_complex = ";".join(parts)

    audio_args = []
    if cfg.apply_loudnorm:
        audio_args = ["-af", f"loudnorm=I={cfg.loudnorm_target}:TP=-1.5:LRA=11.0"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"color=c={bg_bot}:s={w}x{h}:d={cfg.duration:.3f}:r={cfg.fps}",
        "-loop", "1", "-t", f"{cfg.duration:.3f}", "-i", cfg.cover_path,
        "-i", cfg.audio_path,
    ]
    # 4-й вход — frame PNG (если есть). Его порядковый номер [3:v].
    if frame_exists:
        cmd += ["-loop", "1", "-t", f"{cfg.duration:.3f}", "-i", frame_png]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "2:a",
        "-t", f"{cfg.duration:.3f}",
        "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
        "-pix_fmt", "yuv420p",
        *audio_args,
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart",
        cfg.output_path,
    ]

    logger.info(f"build_pov_spotify: {cfg.artist_name} — {cfg.track_name} → {cfg.output_path}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        dbg_path = cfg.output_path.rsplit(".", 1)[0] + ".filter.txt"
        try:
            with open(dbg_path, "w", encoding="utf-8") as dbg:
                dbg.write(filter_complex)
        except OSError:
            dbg_path = "(n/a)"
        raise RuntimeError(
            f"ffmpeg pov_spotify failed (rc={r.returncode}):\n"
            f"filter saved: {dbg_path}\n"
            f"stderr:\n{r.stderr[:2500]}"
        )
    if not os.path.exists(cfg.output_path):
        raise RuntimeError(f"pov_spotify output not created: {cfg.output_path}")

    if cfg.loop_stitch and cfg.loop_stitch_duration > 0:
        try:
            _apply_loop_stitch(cfg.output_path, cfg.loop_stitch_duration)
        except Exception as e:
            logger.warning(f"pov_spotify loop-stitch skipped: {e}")

    logger.info(f"build_pov_spotify done: {os.path.getsize(cfg.output_path)} bytes")
    return cfg.output_path


def _apply_loop_stitch(video_path: str, crossfade_dur: float = 0.5) -> None:
    """Xfade последних X секунд к первым — seamless loop."""
    tmp_out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_out.close()
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=15,
        )
        total = float(probe.stdout.strip() or 0)
        if total <= 2 * crossfade_dur:
            raise RuntimeError(f"слишком короткий ({total:.1f}s)")
        fade_offset = total - crossfade_dur
        fc = (
            f"[0:v]trim=0:{fade_offset:.3f},setpts=PTS-STARTPTS[main];"
            f"[0:v]trim=0:{crossfade_dur:.3f},setpts=PTS-STARTPTS[head];"
            f"[0:v]trim={fade_offset:.3f}:{total:.3f},setpts=PTS-STARTPTS[tail];"
            f"[tail][head]xfade=transition=fade:duration={crossfade_dur:.3f}:offset=0[loop_join];"
            f"[main][loop_join]concat=n=2:v=1:a=0[outv]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", video_path,
            "-filter_complex", fc,
            "-map", "[outv]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", tmp_out.name,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"xfade failed: {r.stderr[:400]}")
        if os.path.getsize(tmp_out.name) < 1024:
            raise RuntimeError("loop-stitch output пустой")
        os.replace(tmp_out.name, video_path)
    except Exception:
        if os.path.exists(tmp_out.name):
            try:
                os.unlink(tmp_out.name)
            except OSError:
                pass
        raise
