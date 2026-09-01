"""
Собирает готовый Spotify-player BACKGROUND в один PNG:

  1. Тёмный dark-spotify фон (#121212) на весь 1080×1920
  2. Поверх — UI-оверлей из реального mockup'а
     (denzven/Spotify_Album_Cover_ScreenShot_Maker/assets/ui/ui.png)
  3. В области обложки — прозрачная "дырка" (alpha=0), куда bundle_pov_spotify
     просто положит cover без каких-либо масок

Результат: static/assets/pov_spotify_bg.png

После этого в видео-pipeline остаётся только:
  - положить фон (1080×1920)
  - overlay cover в заданные координаты
  - overlay динамический текст (Track/Artist/timestamps/progress)

Никаких drawbox-масок для скрытия mockup'овых элементов не нужно —
progress bar и timestamps ЗАКРАШЕНЫ тёмным в фоне (т.е. их просто нет),
а мы рисуем свои.

Запуск: python scripts/prepare_pov_spotify_mockup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PNG = ROOT / "static" / "assets" / "pov_spotify_source.png"
OUTPUT_BG = ROOT / "static" / "assets" / "pov_spotify_bg.png"

TARGET_W, TARGET_H = 1080, 1920
SCALE = TARGET_H / 749                              # ≈ 2.56
SPOTIFY_DARK = (18, 18, 18)                         # #121212 — канон Spotify

# Координаты (синхронно с bundle_pov_spotify.py):
COVER_X = 71
COVER_Y = 240
COVER_SIZE = 938

# Области статичных mockup'овых элементов, которые мы хотим ВЫРЕЗАТЬ
# (чтобы потом нарисовать динамические поверх тёмного фона):
#   progress bar line: y=1500..1528
#   timestamps text:   y=1532..1580
#   Song / Artist text — в исходнике их нет на ui.png (только UI-chrome).
ERASE_BANDS = [
    (0, 1500, TARGET_W, 1528),       # progress
    (0, 1532, TARGET_W, 1580),       # timestamps
]


def brighten_dark_text(img: Image.Image) -> Image.Image:
    """Осветляет тёмно-серый текст до белого (оригинал для light-темы)."""
    arr = np.array(img.convert("RGBA"))
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    is_gray = (
        (np.abs(r.astype(int) - g.astype(int)) < 10)
        & (np.abs(g.astype(int) - b.astype(int)) < 10)
        & (r < 180)
        & (a > 20)
    )
    arr[is_gray, 0] = 255
    arr[is_gray, 1] = 255
    arr[is_gray, 2] = 255
    return Image.fromarray(arr, mode="RGBA")


def main():
    if not SOURCE_PNG.exists():
        print(f"ERROR: source не найден: {SOURCE_PNG}", file=sys.stderr)
        sys.exit(1)

    src = Image.open(SOURCE_PNG).convert("RGBA")
    print(f"source: {src.size}")
    src = brighten_dark_text(src)

    # Scale UI
    new_w = int(src.width * SCALE)
    new_h = int(src.height * SCALE)
    ui_scaled = src.resize((new_w, new_h), Image.LANCZOS)
    print(f"ui scaled: {ui_scaled.size}")

    # Собираем dark background 1080×1920
    bg = Image.new("RGBA", (TARGET_W, TARGET_H), SPOTIFY_DARK + (255,))

    # Паста UI (transparent PNG) поверх dark
    offset_x = (TARGET_W - new_w) // 2
    bg.paste(ui_scaled, (offset_x, 0), ui_scaled)

    # Стираем статичные progress + timestamps (закрашиваем тёмным),
    # чтобы bundle_pov_spotify мог поверх нарисовать живые
    from PIL import ImageDraw
    draw = ImageDraw.Draw(bg)
    for (x0, y0, x1, y1) in ERASE_BANDS:
        draw.rectangle((x0, y0, x1, y1), fill=SPOTIFY_DARK + (255,))

    # Пробиваем "дыру" под обложку (alpha=0 в этой зоне — cover виден напрямую)
    # Делается через прямоугольный вырез в alpha-канале
    arr = np.array(bg)
    arr[COVER_Y:COVER_Y + COVER_SIZE, COVER_X:COVER_X + COVER_SIZE, 3] = 0
    bg = Image.fromarray(arr, mode="RGBA")

    OUTPUT_BG.parent.mkdir(parents=True, exist_ok=True)
    bg.save(OUTPUT_BG, "PNG")
    print(f"OK: saved {OUTPUT_BG} ({OUTPUT_BG.stat().st_size} bytes)")

    print("\nLayout (1080×1920):")
    print(f"  cover hole:  x={COVER_X} y={COVER_Y}  size={COVER_SIZE}×{COVER_SIZE}")
    print(f"  track title: y=1330 (dynamic)")
    print(f"  artist:      y=1417 (dynamic)")
    print(f"  progress:    y=1512 (dynamic)")
    print(f"  timestamps:  y=1544 (dynamic)")
    print(f"  play circle: cy=1690 (from mockup)")


if __name__ == "__main__":
    main()
