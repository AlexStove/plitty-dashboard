"""
Генерация анимированного фона по динамике трека через ffmpeg.

Алгоритм:
1. librosa анализирует трек: BPM, RMS, onset strength.
2. По динамике вычисляем pulse_freq (как часто фон "дышит") и
   wave_smooth (насколько сильно сглаживать волну во времени):
   - плавный/медленный трек → 0.10-0.20 Гц + сильное сглаживание (tmix=10)
   - энергичный трек → 0.50-0.90 Гц + слабое сглаживание (tmix=3)
3. ffmpeg рендерит фон через geq + один из 12 паттернов фона +
   один из 4 стилей визуализации звука:
   Паттерны: diagonal_gradient, vertical_waves, pulsing_circles, plasma,
   diamond_grid, radial_burst, horizontal_scan, tunnel, spiral,
   checkerboard, aurora, fire_rise
   Wave-стили: smooth_line, centered_glow, freq_bars, spectrum_glow
   Light leaks: 8 типов лёгких palette-aware засветок
   Итого: 24 палитры × 12 фонов × 4 wave-стиля × 8 light leaks = 9216 комбинаций.
"""

import logging
import os
import random
import subprocess
from typing import Optional

# Совместимость librosa со scipy >= 1.13 (где удалён scipy.signal.hann)
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import librosa
import numpy as np

from .light_leaks import build_inline_light_leak

logger = logging.getLogger(__name__)


def analyze_dynamics(audio_path: str, sr: int = 22050) -> dict:
    """
    Возвращает {bpm, energy, pulse_freq, wave_smooth, is_calm, beat_times}.

    pulse_freq — частота "дыхания" фона (Гц)
    wave_smooth — кол-во кадров для tmix сглаживания волны (3-12)
    """
    try:
        y, sr = librosa.load(audio_path, sr=sr, mono=True)
    except Exception as e:
        logger.warning(f"librosa load failed: {e}")
        return {
            "bpm": 100.0, "energy": 0.5, "pulse_freq": 0.25,
            "wave_smooth": 6, "is_calm": True, "beat_times": [],
        }

    beat_times = []
    try:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])
        if bpm < 40 or bpm > 200:
            bpm = 100.0
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    except Exception:
        bpm = 100.0

    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_norm = float(np.clip(np.mean(onset_env) / 5.0, 0.0, 1.0))
    except Exception:
        onset_norm = 0.5

    try:
        rms = librosa.feature.rms(y=y)[0]
        rms_norm = float(np.clip(np.mean(rms) / 0.15, 0.0, 1.0))
    except Exception:
        rms_norm = 0.5

    energy = float(np.clip(onset_norm * 0.6 + rms_norm * 0.4, 0.0, 1.0))

    # pulse_freq: 0.10 (медленно) → 0.90 (быстро)
    pulse_freq = 0.10 + energy * 0.80
    if bpm > 140 and energy > 0.5:
        pulse_freq = min(1.0, pulse_freq + 0.15)
    if bpm < 80 and energy < 0.4:
        pulse_freq = max(0.08, pulse_freq - 0.05)

    # wave_smooth: для спокойных треков сильнее сглаживаем (медленнее волны)
    # energy=0.0 → 12 кадров, energy=1.0 → 3 кадра
    wave_smooth = int(round(12 - energy * 9))
    wave_smooth = max(3, min(12, wave_smooth))

    is_calm = energy < 0.45

    logger.info(
        f"Dynamics: BPM={bpm:.0f} energy={energy:.2f} "
        f"pulse={pulse_freq:.3f}Hz smooth={wave_smooth}fr "
        f"{'calm' if is_calm else 'energetic'}"
    )
    return {
        "bpm": bpm,
        "energy": energy,
        "pulse_freq": pulse_freq,
        "wave_smooth": wave_smooth,
        "is_calm": is_calm,
        "beat_times": beat_times,
    }


def analyze_bpm(audio_path: str, sr: int = 22050) -> float:
    """Совместимость со старым API."""
    return analyze_dynamics(audio_path, sr=sr)["bpm"]


# Цветовые палитры (c1 >= 40 — без чёрных областей).
# wave — цвет визуализации (контрастный к фону).
# 24 палитры — максимальное разнообразие.
PALETTES = [
    # --- Синие / голубые ---
    # 0 — ocean cyan
    {"gradient": [(45, 65, 95), (55, 120, 175), (85, 200, 240)], "wave": "0xCFF5FF"},
    # 1 — arctic blue
    {"gradient": [(45, 60, 85), (70, 115, 185), (155, 220, 255)], "wave": "0xE8F4FF"},
    # 2 — deep indigo
    {"gradient": [(50, 45, 90), (65, 55, 145), (105, 95, 220)], "wave": "0xC0C0FF"},
    # 3 — electric blue
    {"gradient": [(40, 50, 100), (50, 80, 180), (80, 140, 255)], "wave": "0xD0E8FF"},

    # --- Зелёные / бирюзовые ---
    # 4 — forest green
    {"gradient": [(45, 70, 50), (65, 140, 80), (120, 220, 120)], "wave": "0xD8FFD0"},
    # 5 — emerald
    {"gradient": [(40, 65, 55), (55, 135, 100), (110, 220, 170)], "wave": "0xD0FFE8"},
    # 6 — teal
    {"gradient": [(40, 60, 70), (50, 95, 115), (90, 180, 195)], "wave": "0xB8FFEC"},
    # 7 — lime neon
    {"gradient": [(50, 65, 40), (100, 180, 45), (190, 250, 85)], "wave": "0xF0FFB0"},

    # --- Красные / оранжевые ---
    # 8 — amber fire
    {"gradient": [(75, 50, 40), (200, 95, 40), (255, 170, 65)], "wave": "0xFFF0C0"},
    # 9 — lava red
    {"gradient": [(70, 45, 40), (165, 60, 45), (250, 115, 70)], "wave": "0xFFD8B0"},
    # 10 — warm copper
    {"gradient": [(65, 50, 40), (165, 90, 50), (235, 155, 90)], "wave": "0xFFE0C0"},
    # 11 — crimson rose
    {"gradient": [(80, 40, 50), (180, 50, 75), (250, 90, 120)], "wave": "0xFFD0D8"},

    # --- Золотые / жёлтые ---
    # 12 — golden hour
    {"gradient": [(70, 55, 40), (180, 110, 50), (250, 200, 100)], "wave": "0xFFF0C8"},
    # 13 — sunset peach
    {"gradient": [(80, 55, 50), (200, 110, 70), (255, 185, 120)], "wave": "0xFFE8D0"},
    # 14 — honey gold
    {"gradient": [(70, 60, 40), (170, 140, 45), (240, 220, 80)], "wave": "0xFFFFC0"},

    # --- Фиолетовые / розовые ---
    # 15 — purple night
    {"gradient": [(55, 45, 90), (105, 60, 175), (175, 110, 235)], "wave": "0xE0D0FF"},
    # 16 — magenta dream
    {"gradient": [(70, 40, 70), (160, 55, 140), (240, 100, 200)], "wave": "0xFFD0F0"},
    # 17 — lavender mist
    {"gradient": [(60, 55, 80), (120, 100, 160), (190, 170, 240)], "wave": "0xE8E0FF"},
    # 18 — neon pink
    {"gradient": [(75, 40, 60), (190, 50, 110), (255, 95, 175)], "wave": "0xFFD0E8"},

    # --- Мультиколор / особые ---
    # 19 — aurora borealis (зелёно-голубой)
    {"gradient": [(40, 70, 65), (50, 160, 130), (80, 240, 200)], "wave": "0xD0FFF0"},
    # 20 — tropical (оранж → розовый)
    {"gradient": [(80, 55, 45), (200, 80, 90), (255, 140, 160)], "wave": "0xFFE0E0"},
    # 21 — ocean sunset (синий → оранж)
    {"gradient": [(50, 55, 85), (120, 80, 130), (220, 130, 80)], "wave": "0xFFE0C0"},
    # 22 — mint fresh
    {"gradient": [(45, 70, 65), (70, 170, 150), (130, 240, 210)], "wave": "0xD8FFF0"},
    # 23 — steel blue
    {"gradient": [(50, 55, 65), (80, 95, 120), (140, 165, 200)], "wave": "0xD8E8FF"},
]

# Стили визуализации (выбираются по seed)
WAVE_STYLES = ["smooth_line", "centered_glow", "freq_bars", "spectrum_glow"]


# ──────────────────────────────────────────────────────────────
# 12 паттернов анимированного фона (geq-выражения для r/g/b).
# Каждая функция принимает (c1, c2, c3, pulse_freq) и возвращает
# кортеж (r_expr, g_expr, b_expr).
# ──────────────────────────────────────────────────────────────

def _bg_diagonal_gradient(c1, c2, c3, pf):
    """Оригинальный диагональный градиент с дыханием."""
    def ch(v1, v2, v3, phase):
        mid = (v1 + v3) / 2
        amp = (v3 - v1) / 2
        off = v2 - mid
        sm = (f"(0.5+0.5*sin(2*PI*{pf:.4f}*T+X/W*PI*1.5+Y/H*PI*1.0+{phase:.4f}))")
        return (f"{mid:.1f}+{amp:.1f}*sin(2*PI*{pf:.4f}*T"
                f"+X/W*PI*1.5+Y/H*PI*1.0+{phase:.4f})"
                f"+{off:.1f}*{sm}*0.3")
    return ch(c1[0],c2[0],c3[0],0.0), ch(c1[1],c2[1],c3[1],0.7), ch(c1[2],c2[2],c3[2],1.4)


def _bg_vertical_waves(c1, c2, c3, pf):
    """Вертикальные волны с горизонтальным перетеканием (2D)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin(2*PI*{pf:.4f}*T+X/W*6.28*3+{phase:.4f})"
                f"*0.6+{amp:.1f}*sin(Y/H*4+2*PI*{pf:.4f}*T*0.7+{phase:.4f})*0.4")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.8), ch(c1[2],c3[2],1.6)


def _bg_pulsing_circles(c1, c2, c3, pf):
    """Пульсирующие круги — через (X^2+Y^2) без sqrt (быстро)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin(2*PI*{pf:.4f}*T"
                f"+((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*80)+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.7), ch(c1[2],c3[2],1.4)


def _bg_plasma(c1, c2, c3, pf):
    """Плазма — сумма нескольких синусоид по X, Y и T."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*0.5*(sin(X/W*6.28+2*PI*{pf:.4f}*T+{phase:.4f})"
                f"+sin(Y/H*6.28+2*PI*{pf:.4f}*T*0.7+{phase:.4f}))")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],1.0), ch(c1[2],c3[2],2.0)


def _bg_diamond_grid(c1, c2, c3, pf):
    """Ромбовидная решётка — |X|+|Y| с пульсацией."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin(2*PI*{pf:.4f}*T"
                f"+(abs(X-W/2)+abs(Y-H/2))/100+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.6), ch(c1[2],c3[2],1.2)


def _bg_radial_burst(c1, c2, c3, pf):
    """Радиальные лучи — через sin(X)*cos(Y) (быстро, без atan2)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin(sin((X-W/2)/W*8)*cos((Y-H/2)/H*8)*6"
                f"+2*PI*{pf:.4f}*T+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.9), ch(c1[2],c3[2],1.8)


def _bg_horizontal_scan(c1, c2, c3, pf):
    """Горизонтальное сканирование с диагональным перетеканием (2D)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin(2*PI*{pf:.4f}*T+Y/H*6.28*3"
                f"+sin(X/W*3+{phase:.4f})*0.5+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.5), ch(c1[2],c3[2],1.0)


def _bg_tunnel(c1, c2, c3, pf):
    """Туннельный эффект — через 1/(x^2+y^2) без sqrt (быстро)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin("
                f"W*200/((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2)+W)"
                f"+2*PI*{pf:.4f}*T+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.8), ch(c1[2],c3[2],1.6)


def _bg_spiral(c1, c2, c3, pf):
    """Спираль — через sin(X)*Y + cos(Y)*X без atan2/sqrt (быстро)."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin("
                f"sin((X-W/2)/W*4)*(Y-H/2)/H*6+cos((Y-H/2)/H*4)*(X-W/2)/W*6"
                f"+2*PI*{pf:.4f}*T+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.7), ch(c1[2],c3[2],1.4)


def _bg_checkerboard(c1, c2, c3, pf):
    """Анимированная шахматная доска."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin("
                f"floor(X/120+sin(2*PI*{pf:.4f}*T+{phase:.4f}))"
                f"+floor(Y/120+cos(2*PI*{pf:.4f}*T+{phase:.4f})))")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.5), ch(c1[2],c3[2],1.0)


def _bg_aurora(c1, c2, c3, pf):
    """Северное сияние — мягкие горизонтальные переливы."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*0.5*("
                f"sin(Y/H*3.14+sin(X/W*6.28+2*PI*{pf:.4f}*T)*0.5+{phase:.4f})"
                f"+sin(X/W*3.14+2*PI*{pf:.4f}*T*0.6+{phase:.4f}))")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],1.1), ch(c1[2],c3[2],2.2)


def _bg_fire_rise(c1, c2, c3, pf):
    """Огненный подъём — волны снизу вверх."""
    def ch(v1, v3, phase):
        mid=(v1+v3)/2; amp=(v3-v1)/2
        return (f"{mid:.1f}+{amp:.1f}*sin("
                f"(H-Y)/H*6.28*2+sin(X/W*6.28*3)*0.5"
                f"+2*PI*{pf:.4f}*T+{phase:.4f})")
    return ch(c1[0],c3[0],0.0), ch(c1[1],c3[1],0.6), ch(c1[2],c3[2],1.2)


# Список всех паттернов фона (12 штук)
BG_PATTERNS = [
    ("diagonal_gradient", _bg_diagonal_gradient),
    ("vertical_waves",    _bg_vertical_waves),
    ("pulsing_circles",   _bg_pulsing_circles),
    ("plasma",            _bg_plasma),
    ("diamond_grid",      _bg_diamond_grid),
    ("radial_burst",      _bg_radial_burst),
    ("horizontal_scan",   _bg_horizontal_scan),
    ("tunnel",            _bg_tunnel),
    ("spiral",            _bg_spiral),
    ("checkerboard",      _bg_checkerboard),
    ("aurora",            _bg_aurora),
    ("fire_rise",         _bg_fire_rise),
]


def _pick_all(seed: int = 0) -> dict:
    """Выбор компонентов с реальной случайностью + seed для вариативности.

    Используем time + os.urandom + seed, чтобы каждый запуск давал
    новую комбинацию, но разные vid_num в одной сессии отличались.
    """
    import time
    entropy = int.from_bytes(os.urandom(4), "big") ^ int(time.time() * 1000) ^ seed
    rng = random.Random(entropy)
    palette = rng.choice(PALETTES)
    _, bg_func = bg_pick = rng.choice(BG_PATTERNS)
    style = rng.choice(WAVE_STYLES)
    return {
        "palette": palette,
        "bg": bg_pick,
        "style": style,
    }


def _build_wave_filter(
    style: str,
    width: int,
    waves_h: int,
    fps: int,
    color: str,
    smooth_frames: int,
) -> str:
    """
    Возвращает filter-цепочку из [1:a] → [waves].
    Все стили заканчиваются tmix для временного сглаживания (медленные волны).
    """
    n_samples = max(800, 22050 // fps)
    tmix = max(3, smooth_frames)

    if style == "smooth_line":
        # Гладкая линия с glow
        return (
            f"[1:a]aresample=22050,"
            f"showwaves=s={width}x{waves_h}:mode=line:n={n_samples}:rate={fps}"
            f":colors={color}:scale=sqrt,"
            f"format=yuva420p,"
            f"tmix=frames={tmix},"
            f"boxblur=3:1,"
            f"colorchannelmixer=aa=0.85"
            f"[waves]"
        )

    if style == "centered_glow":
        # Центрированная волна с сильным glow и зеркалом
        return (
            f"[1:a]aresample=22050,"
            f"showwaves=s={width}x{waves_h}:mode=cline:n={n_samples}:rate={fps}"
            f":colors={color}:scale=sqrt,"
            f"format=yuva420p,"
            f"tmix=frames={tmix},"
            f"boxblur=6:2,"
            f"colorchannelmixer=aa=0.78"
            f"[waves]"
        )

    if style == "freq_bars":
        # Вертикальный эквалайзер (частотные полосы)
        return (
            f"[1:a]aresample=22050,"
            f"showfreqs=s={width}x{waves_h}:mode=bar:ascale=log:fscale=log"
            f":colors={color}:rate={fps}:win_size=2048,"
            f"format=yuva420p,"
            f"tmix=frames={tmix},"
            f"boxblur=2:1,"
            f"colorchannelmixer=aa=0.80"
            f"[waves]"
        )

    if style == "spectrum_glow":
        # Спектрограмма с blur
        return (
            f"[1:a]aresample=22050,"
            f"showspectrum=s={width}x{waves_h}:mode=combined:slide=scroll"
            f":color=intensity:scale=log:rotation=0.2,"
            f"format=yuva420p,"
            f"tmix=frames={tmix},"
            f"boxblur=4:1,"
            f"colorchannelmixer=aa=0.55"
            f"[waves]"
        )

    # Fallback
    return (
        f"[1:a]aresample=22050,"
        f"showwaves=s={width}x{waves_h}:mode=line:n={n_samples}:rate={fps}"
        f":colors={color}:scale=sqrt,"
        f"format=yuva420p,boxblur=3:1[waves]"
    )


def generate_animated_background(
    audio_path: str,
    duration: float,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    palette_seed: int = 0,
) -> Optional[tuple[str, dict]]:
    """
    Генерирует видео с анимированным фоном + динамической визуализацией звука
    + кинематографическими light leaks с beat-reactive модуляцией.

    Возвращает (output_path, palette) или None при ошибке.
    palette_seed + entropy обеспечивают уникальную комбинацию каждый запуск.
    Всего 24 палитры × 12 паттернов × 4 wave-стиля × 8 light leaks = 9216 комбинаций.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    dyn = analyze_dynamics(audio_path)
    pulse_freq = dyn["pulse_freq"]
    wave_smooth = dyn["wave_smooth"]

    picks = _pick_all(palette_seed)
    palette = picks["palette"]
    style = picks["style"]
    bg_name, bg_func = picks["bg"]
    grad = palette["gradient"]
    wave_color = palette["wave"]

    logger.info(
        f"animated_bg: bg={bg_name} style={style}"
    )

    c1 = grad[0]
    c2 = grad[1]
    c3 = grad[2]

    # Генерируем geq-выражения r/g/b через выбранный паттерн фона
    r_expr, g_expr, b_expr = bg_func(c1, c2, c3, pulse_freq)

    # Light leak — встраиваем аддитивно прямо в geq
    ll_r, ll_g, ll_b = build_inline_light_leak(
        palette=palette, pulse_freq=pulse_freq, seed=palette_seed,
    )
    r_expr = f"clip(({r_expr})+({ll_r}),0,255)"
    g_expr = f"clip(({g_expr})+({ll_g}),0,255)"
    b_expr = f"clip(({b_expr})+({ll_b}),0,255)"

    # Рендерим geq в половинном разрешении (4x меньше пикселей = 4x быстрее)
    rw = width // 2
    rh = height // 2

    hue_shift = "hue=h='10*sin(2*PI*t/30)':s=1.05"

    # Только geq-фон + light leaks, без wave overlay
    filter_complex = (
        f"color=c=black:s={rw}x{rh}:r={fps}:d={duration:.3f}[base];"
        f"[base]geq=r='{r_expr}':g='{g_expr}':b='{b_expr}',"
        f"{hue_shift},scale={width}:{height}:flags=fast_bilinear[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={rw}x{rh}:r={fps}:d={duration:.3f}",
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-t", f"{duration:.3f}",
        "-threads", "0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.exists(output_path):
            logger.info(f"Animated bg готов: {output_path}")
            return output_path, palette
        logger.error(f"animated_bg ffmpeg fail: {r.stderr[-500:]}")
        return None
    except Exception as e:
        logger.error(f"animated_bg error: {e}")
        return None
