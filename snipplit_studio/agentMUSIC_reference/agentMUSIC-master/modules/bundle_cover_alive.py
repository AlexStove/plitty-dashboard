"""
Bundle Cover Alive — cover art с parallax zoom и kinetic lyrics поверх.

Формат для продвижения ноунейм-треков, третий вариант в mix'е.
Отличается от track_promo:
  - Cover виден ВСЁ ВРЕМЯ, не только в reveal-акте
  - Нет акта hook-card и CTA — чистый визуал + lyrics
  - Ставка на visual memory (узнаваемость обложки трека)

Структура:
  - BG: cover художка с медленным zoompan parallax (10с цикл)
  - Blur-cover сзади (фильтр boxblur) для fill без чёрных полос
  - Kinetic hero-word lyrics (переиспользуем code из track_promo)
  - Нижняя плашка с Artist/Track (постоянно видна)

Работает даже без lyrics — просто cover + artist/track label.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .types import LyricsLine
from .cta_overlay import _safe_text

logger = logging.getLogger(__name__)


@dataclass
class CoverAliveConfig:
    audio_path: str
    lyrics: list[LyricsLine]
    output_path: str
    font_path: str
    duration: float = 21.0
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    # Промо-данные
    track_name: str = ""
    artist_name: str = ""
    cover_path: Optional[str] = None
    palette_name: str = "default"
    # Качество
    crf: int = 21
    preset: str = "veryfast"
    apply_loudnorm: bool = True
    loudnorm_target: float = -14.0
    loop_stitch: bool = True
    loop_stitch_duration: float = 0.5


# Цвет подложки (должен контрастировать с cover)
BG_COLOR_BY_PALETTE = {
    "sad-girl":   "0x0A0515",
    "trap":       "0x000000",
    "dark":       "0x050505",
    "dream-pop":  "0x0A1540",
    "default":    "0x0A0A0F",
}


def _autofit(text: str, base_fs: int, max_w: int) -> int:
    if not text:
        return base_fs
    approx = int(max_w / max(1, len(text)) / 0.55)
    return max(36, min(base_fs, approx))


def _hero_lyric_filters(cfg: CoverAliveConfig) -> list[str]:
    """Kinetic hero-word в зоне между cover-постером и нижней плашкой Artist/Track."""
    w, h = cfg.resolution
    # Геометрия cover_alive (должна совпадать с build_cover_alive):
    #   cover = (w*0.80) квадрат, верх на h*0.14
    #   нижняя плашка  = h*0.18
    # Свободная зона между ними:
    cov_y = int(h * 0.14)
    cov_h = int(w * 0.80)
    bar_h = int(h * 0.18)
    free_top = cov_y + cov_h
    free_bottom = h - bar_h
    # Базовый шрифт подбираем под высоту зоны (не более её высоты)
    zone_h = max(1, free_bottom - free_top)
    base_fs = max(48, min(110, int(zone_h * 0.40)))
    # Центрируем текст по вертикали в зоне (text_h ≈ base_fs * 1.15)
    hero_y = free_top + max(0, (zone_h - int(base_fs * 1.15)) // 2)

    filters: list[str] = []
    flat_words = []
    for ln in cfg.lyrics or []:
        if not (ln.words or []):
            continue
        for w_ in ln.words:
            wt = (w_.word or "").strip()
            if not wt:
                continue
            ws = float(w_.start)
            we = float(w_.end)
            if we <= 0 or ws >= cfg.duration:
                continue
            flat_words.append((wt, max(0.0, ws), min(cfg.duration, we)))

    for i, (wt, ws, we) in enumerate(flat_words):
        next_start = flat_words[i + 1][1] if i + 1 < len(flat_words) else cfg.duration
        display_end = min(cfg.duration, next_start - 0.02)
        if display_end <= ws + 0.05:
            continue
        word_dur = max(0.05, we - ws)
        fi = min(0.08, word_dur * 0.35)
        fo = min(0.08, max(0.03, (display_end - we) * 0.55))
        fs = _autofit(wt, base_fs, int(w * 0.9))
        color = "0xFFE156" if (i % 2 == 0) else "white"
        alpha = (
            f"if(lt(t,{ws:.3f}),0,"
            f"if(lt(t,{ws + fi:.3f}),(t-{ws:.3f})/{fi:.3f},"
            f"if(lt(t,{display_end - fo:.3f}),1,"
            f"if(lt(t,{display_end:.3f}),({display_end:.3f}-t)/{fo:.3f},0))))"
        )
        filters.append(
            f"drawtext=fontfile='{cfg.font_path}'"
            f":text='{_safe_text(wt)}'"
            f":fontsize={fs}"
            f":fontcolor={color}"
            f":borderw=6:bordercolor=black"
            f":shadowcolor=black@0.80:shadowx=3:shadowy=6"
            f":x=(w-text_w)/2:y={hero_y}"
            f":alpha='{alpha}'"
            f":enable='between(t,{ws:.3f},{display_end:.3f})'"
        )
    return filters


def _label_filters(cfg: CoverAliveConfig) -> list[str]:
    """
    Постоянная плашка снизу: Artist + Track, видна весь ролик.
    Чёрная полоса внизу под текстом для читаемости.
    """
    w, h = cfg.resolution
    filters: list[str] = []
    # Bottom-bar затемнение
    bar_h = int(h * 0.18)
    filters.append(
        f"drawbox=x=0:y={h - bar_h}:w={w}:h={bar_h}"
        f":color=black@0.72:t=fill"
    )
    artist = (cfg.artist_name or "Unknown Artist").strip()[:32]
    name = (cfg.track_name or "Unknown Track").strip()[:38]
    # Artist (крупнее)
    fs_a = _autofit(artist, 74, int(w * 0.92))
    fs_t = _autofit(name, 52, int(w * 0.92))
    y_a = h - bar_h + int(bar_h * 0.20)
    y_t = h - bar_h + int(bar_h * 0.62)

    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(artist)}'"
        f":fontsize={fs_a}"
        f":fontcolor=white"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y={y_a}"
    )
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(name)}'"
        f":fontsize={fs_t}"
        f":fontcolor=0xFFE156"
        f":borderw=2:bordercolor=black"
        f":x=(w-text_w)/2:y={y_t}"
    )
    return filters


def build_cover_alive(cfg: CoverAliveConfig) -> str:
    """
    Рендер cover_alive ролика.

    Filter graph:
      [0:v] color bg
      [1:v] cover → blur-bg (fill на весь экран)
      [1:v] cover → zoompan (slow zoom 1.0→1.15 × 10с, циклично) → portrait fit
      overlay: blur-bg + zoompan-cover + lyrics + label
    """
    if not os.path.exists(cfg.audio_path):
        raise RuntimeError(f"audio not found: {cfg.audio_path}")
    if not os.path.exists(cfg.font_path):
        raise RuntimeError(f"font not found: {cfg.font_path}")
    if not cfg.cover_path or not os.path.exists(cfg.cover_path):
        raise RuntimeError(
            f"cover_alive требует cover_path (no cover = rendering impossible). "
            f"Загрузи трек через Spotify для получения обложки."
        )

    w, h = cfg.resolution
    os.makedirs(os.path.dirname(os.path.abspath(cfg.output_path)) or ".", exist_ok=True)
    bg_color = BG_COLOR_BY_PALETTE.get(cfg.palette_name, BG_COLOR_BY_PALETTE["default"])

    # Cover-центр (70% ширины, квадратный) с slow zoom
    cov_w = int(w * 0.80)
    cov_h = cov_w
    cov_x = (w - cov_w) // 2
    cov_y = int(h * 0.14)                 # отступ сверху 14% (там hero lyrics)

    frames = int(cfg.duration * cfg.fps)
    # zoompan: плавный zoom 1.0 → 1.18 за 10с cycle, linear interpolation
    # Используем on_frame, цикл через frames_period
    # Проще — один zoom-in в течение всего ролика
    zp = (
        f"zoompan=z='min(zoom+0.0008,1.20)'"
        f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":fps={cfg.fps}:s={cov_w}x{cov_h}"
    )

    # Filter complex с отдельным stream для blur-bg (full-screen fill)
    filter_complex = (
        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},boxblur=lr=30:lp=2:cr=15:cp=1,setsar=1[bg];"
        f"[1:v]{zp},setsar=1[cov];"
        f"[0:v][bg]overlay=0:0[v1];"
        f"[v1][cov]overlay={cov_x}:{cov_y}[vcov]"
    )

    # Текстовые layers на [vcov]
    text_filters = _hero_lyric_filters(cfg) + _label_filters(cfg)
    text_chain = ",".join(text_filters) if text_filters else "null"
    filter_complex += f";[vcov]{text_chain},format=yuv420p[vout]"

    # Audio args
    audio_args: list[str] = []
    if cfg.apply_loudnorm:
        audio_args = ["-af", f"loudnorm=I={cfg.loudnorm_target}:TP=-1.5:LRA=11.0"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"color=c={bg_color}:s={w}x{h}:d={cfg.duration:.3f}:r={cfg.fps}",
        "-loop", "1", "-t", f"{cfg.duration:.3f}", "-i", cfg.cover_path,
        "-i", cfg.audio_path,
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

    logger.info(
        f"build_cover_alive: {cfg.artist_name} — {cfg.track_name} → {cfg.output_path}"
    )
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg cover_alive failed (rc={r.returncode}):\n{r.stderr[:2500]}")
    if not os.path.exists(cfg.output_path):
        raise RuntimeError(f"cover_alive output not created: {cfg.output_path}")

    if cfg.loop_stitch and cfg.loop_stitch_duration > 0:
        try:
            _apply_loop_stitch(cfg.output_path, cfg.loop_stitch_duration)
        except Exception as e:
            logger.warning(f"cover_alive loop-stitch skipped: {e}")

    logger.info(f"build_cover_alive done: {os.path.getsize(cfg.output_path)} bytes")
    return cfg.output_path


def _apply_loop_stitch(video_path: str, crossfade_dur: float = 0.5) -> None:
    import tempfile
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
            raise RuntimeError(f"too short ({total:.1f}s)")
        fade_offset = total - crossfade_dur
        filter_complex = (
            f"[0:v]trim=0:{fade_offset:.3f},setpts=PTS-STARTPTS[main];"
            f"[0:v]trim=0:{crossfade_dur:.3f},setpts=PTS-STARTPTS[head];"
            f"[0:v]trim={fade_offset:.3f}:{total:.3f},setpts=PTS-STARTPTS[tail];"
            f"[tail][head]xfade=transition=fade:duration={crossfade_dur:.3f}:offset=0[loop_join];"
            f"[main][loop_join]concat=n=2:v=1:a=0[outv]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", video_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            tmp_out.name,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"xfade failed: {r.stderr[:400]}")
        if os.path.getsize(tmp_out.name) < 1024:
            raise RuntimeError("loop-stitch output empty")
        os.replace(tmp_out.name, video_path)
    except Exception:
        if os.path.exists(tmp_out.name):
            try:
                os.unlink(tmp_out.name)
            except OSError:
                pass
        raise
