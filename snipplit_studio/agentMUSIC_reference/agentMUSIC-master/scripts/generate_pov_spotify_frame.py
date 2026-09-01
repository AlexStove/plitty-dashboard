"""
Генерирует pixel-perfect Spotify UI frame через PIL:
  - Прозрачный фон, 1080×1920
  - Все статичные UI элементы (иконки, кнопки, линии) — AA-рендер
  - Области под dynamic-контент оставлены прозрачными:
      * cover    (928×928 под y=230)  — FFmpeg нижним слоем положит cover
      * title/artist — рисуются FFmpeg'ом (меняются per-track)
      * progress fill + timestamps   — FFmpeg (per-frame)
      * mini-player text             — FFmpeg

Результат: static/assets/pov_spotify_frame.png

Запуск: python scripts/generate_pov_spotify_frame.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920

# Layout matches bundle_pov_spotify.py (synced)
COV_SIZE = int(W * 0.86)      # 928
COV_X = (W - COV_SIZE) // 2   # 76
COV_Y = int(H * 0.12)         # 230

TRACK_Y = COV_Y + COV_SIZE + 50            # ~1208 (FFmpeg рисует сам)
PROGRESS_Y = TRACK_Y + 82 + 20 + 46 + 26   # ~1382 (синхронно с bundle)
CONTROLS_CY = PROGRESS_Y + 22 + 140        # ~1544
MINI_Y_TOP = H - 110                        # 1810

SPOTIFY_GREEN = (29, 185, 84, 255)
WHITE = (255, 255, 255, 255)
WHITE_DIM = (255, 255, 255, 217)           # alpha 0.85
WHITE_FAINT = (255, 255, 255, 153)         # alpha 0.6
BLACK = (0, 0, 0, 255)

SYMBOL_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def find_font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise RuntimeError(f"Ни один шрифт не найден: {paths}")


def draw_centered_text(
    img: Image.Image, pos_cx: int, pos_cy: int, text: str,
    font: ImageFont.FreeTypeFont, fill=WHITE,
):
    """Рисует текст с центром в (pos_cx, pos_cy). Aнтиалиасинг PIL."""
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    # textbbox возвращает bbox включая ascent/descent, но pad сверху обычно есть;
    # компенсируем top-offset
    draw.text((pos_cx - tw // 2 - bbox[0], pos_cy - th // 2 - bbox[1]), text, font=font, fill=fill)


def draw_spotify_frame(out_path: str):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    sym_font_big = find_font(SYMBOL_FONT_CANDIDATES, 56)     # ← ♡ big
    sym_font_med = find_font(SYMBOL_FONT_CANDIDATES, 50)     # ♥ ★
    sym_font_sh = find_font(SYMBOL_FONT_CANDIDATES, 42)      # ⇄ ⌃
    sym_font_play = find_font(SYMBOL_FONT_CANDIDATES, 22)    # ▶ в мини-плеере
    prev_next_font = find_font(SYMBOL_FONT_CANDIDATES, 64)   # prev/next triangles

    # ------ TOP BAR ------
    # ← back (y=96)
    draw.text((52, 96), "←", font=sym_font_big, fill=WHITE)
    # ♡ heart (top-right)
    hb = draw.textbbox((0, 0), "♡", font=sym_font_med)
    draw.text((W - (hb[2] - hb[0]) - 58, 98), "♡", font=sym_font_med, fill=WHITE_DIM)

    # ------ COVER SHADOW (тонкая тень под обложкой) ------
    shadow_y = COV_Y + COV_SIZE
    for i in range(12):
        alpha = int(115 - i * 9)
        if alpha <= 0:
            break
        draw.rectangle(
            (COV_X, shadow_y + i, COV_X + COV_SIZE, shadow_y + i + 1),
            fill=(0, 0, 0, alpha),
        )

    # ------ SHUFFLE ICON справа от title ------
    # Title центр ~ W/2, fs ~82. Справа от заголовка рисуем ⇄.
    # В реальности title рендерит FFmpeg, но поставим shuffle в статике на конце строки.
    shuf_x = W - 80 - 44
    shuf_y = TRACK_Y + 41 - 22     # выровнено по центру title (≈ TRACK_Y + half of 82)
    draw.text((shuf_x, shuf_y), "⇄", font=sym_font_sh, fill=WHITE_DIM)

    # ------ CONTROLS ROW ------
    play_r = 66
    play_cx = W // 2
    play_cy = CONTROLS_CY

    # Heart (green) — left edge
    draw_centered_text(img, 110, play_cy, "♥", sym_font_med, fill=SPOTIFY_GREEN)

    # Prev triangles "⏪" — слева от play. Unicode ⏮ тофится, делаем два треугольника.
    # Используем два "◀" (U+25C0) — проверим поддержку.
    side_off = 240
    # Два треугольника прев (как в мокапе AirPods: ⏪ = два треугольника)
    _draw_double_triangle(draw, play_cx - side_off, play_cy, size=26, direction="left")
    _draw_double_triangle(draw, play_cx + side_off, play_cy, size=26, direction="right")

    # PLAY CIRCLE (белый круг + чёрная пауза ||)
    # Круг — использем ellipse (PIL делает anti-aliased круг нормально)
    draw.ellipse(
        (play_cx - play_r, play_cy - play_r,
         play_cx + play_r, play_cy + play_r),
        fill=WHITE,
    )
    # Pause bars — чёрные
    bar_w = 10
    bar_h = 50
    bar_gap = 16
    draw.rectangle(
        (play_cx - bar_gap // 2 - bar_w, play_cy - bar_h // 2,
         play_cx - bar_gap // 2,          play_cy + bar_h // 2),
        fill=BLACK,
    )
    draw.rectangle(
        (play_cx + bar_gap // 2,            play_cy - bar_h // 2,
         play_cx + bar_gap // 2 + bar_w,    play_cy + bar_h // 2),
        fill=BLACK,
    )

    # Star справа — белая
    draw_centered_text(img, W - 110, play_cy, "★", sym_font_med, fill=WHITE)

    # ------ MINI-PLAYER FOOTER ------
    strip_h = 86
    # Полупрозрачная плашка — не делаем (FFmpeg положит сверху). Вместо этого
    # рисуем тонкую разделительную линию сверху + мелкий green play круг + ⌃
    # Линия
    draw.rectangle(
        (0, MINI_Y_TOP, W, MINI_Y_TOP + 1),
        fill=(255, 255, 255, 40),
    )
    # Green play circle (слева)
    play_r_sm = 28
    play_cx_sm = 70
    play_cy_sm = MINI_Y_TOP + strip_h // 2
    draw.ellipse(
        (play_cx_sm - play_r_sm, play_cy_sm - play_r_sm,
         play_cx_sm + play_r_sm, play_cy_sm + play_r_sm),
        fill=SPOTIFY_GREEN,
    )
    # Triangle ▶ white inside (draw triangle via polygon)
    tri_size = 14
    tri_poly = [
        (play_cx_sm - tri_size // 2 + 2, play_cy_sm - tri_size),
        (play_cx_sm - tri_size // 2 + 2, play_cy_sm + tri_size),
        (play_cx_sm + tri_size + 2,      play_cy_sm),
    ]
    draw.polygon(tri_poly, fill=WHITE)

    # ⌃ up chevron (справа)
    draw.text((W - 80, play_cy_sm - 22), "⌃", font=sym_font_sh, fill=WHITE_DIM)

    # Save
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _draw_double_triangle(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int, size: int, direction: str = "left",
):
    """Рисует два треугольника (как ⏪ prev или ⏩ next)."""
    color = WHITE
    if direction == "left":
        # Левее: два треугольника указывают влево
        for i, off in enumerate([-size + 2, size - 2]):
            # треугольник острием влево
            pts = [
                (cx + off + size // 2,  cy - size),
                (cx + off + size // 2,  cy + size),
                (cx + off - size // 2,  cy),
            ]
            draw.polygon(pts, fill=color)
    else:
        for i, off in enumerate([-size + 2, size - 2]):
            pts = [
                (cx + off - size // 2,  cy - size),
                (cx + off - size // 2,  cy + size),
                (cx + off + size // 2,  cy),
            ]
            draw.polygon(pts, fill=color)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    out = here / "static" / "assets" / "pov_spotify_frame.png"
    draw_spotify_frame(str(out))
    print(f"OK: saved {out} ({out.stat().st_size} bytes)")
