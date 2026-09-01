"""
CTA Overlay — Call-to-Action слои для ноунейм-промо.

Три независимые утилиты, все — чистые функции, возвращают строки FFmpeg-фильтров
или готовые тексты. НИЧЕГО не трогают в существующих bundle-рендерах:
добавляются к filter_complex опционально, по желанию вызывающего кода.

1. build_hook_card_filter() — статический текст первого кадра (0.3-0.8с),
   "pattern interrupt" для перехвата свайпа TikTok.
2. build_track_card_filter() — мини-плашка "🎧 TRACK: Name — Artist"
   в нижней 1/3, появляется 1 раз внутри ролика.
3. build_description() + build_utm_link() — текст описания под ролик
   с UTM-мечеными Spotify-ссылками для трекинга CTR.

Шрифт — тот же, что и в bundle1_karaoke (Montserrat-Bold.ttf),
передаётся через font_path параметр.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


# TikTok safe-zone для portrait 1080x1920:
# верх  — 0-250px (там появляется username/back)
# низ   — 1580-1920px (caption, кнопки, музыка)
# право — 930-1080px (like/share/comment)
# безопасная зона текста: x in [80, 1000], y in [300, 1550]

SAFE_TOP_Y = 300
SAFE_BOTTOM_Y = 1500
SAFE_CENTER_X = 540  # середина 1080

# ---------------------------------------------------------------------------
#  Hook-card (первый кадр, pattern interrupt)
# ---------------------------------------------------------------------------

HOOK_TEMPLATES = {
    # US-native формулировки под ноунейм-промо.
    # Плейсхолдеры: {streams}, {artist}.
    "discovery":     "you need to hear this",
    "streams_count": "only {streams} streams",
    "pov":           "POV: your new favorite song",
    "curiosity":     "why is nobody talking about this",
    "fomo":          "don't scroll past this",
    "gatekeeper":    "I'm gatekeeping this artist",
    "cant_believe":  "I can't believe this is unreleased",
    "warning":       "this song will ruin your night",
}


@dataclass
class HookCardConfig:
    text: str
    duration: float = 0.7           # сколько секунд висит на первом кадре
    fontsize: int = 72
    color: str = "white"
    bg_color: str = "black@0.55"    # полупрозрачная подложка, для читабельности
    y_position: str = "center"      # "center" | "top" | "upper-third"
    border_color: str = ""          # опциональная цветная обводка (hex 0xRRGGBB или имя)
    border_width: int = 0           # толщина обводки, 0 = выключена


# Пресеты hook-card под палитры kinetic-рендера.
# Подбираем так, чтобы box контрастировал с bg_base палитры,
# но сохранял US-TikTok эстетику (неон/контраст, не серо-бежево).
HOOK_PALETTE_STYLES: dict[str, dict[str, str | int]] = {
    # Тёмные палитры — яркий неоновый box + белый текст + цветная обводка
    "dark":       {"color": "white", "bg_color": "0x7F00FF@0.85", "border_color": "white",    "border_width": 4},
    "trap":       {"color": "black", "bg_color": "0xFFD700@0.92", "border_color": "0xFF8C00", "border_width": 4},
    "sad-girl":   {"color": "white", "bg_color": "0xE91E63@0.85", "border_color": "white",    "border_width": 4},
    # Светло-синяя — тёмный box, яркий текст
    "dream-pop":  {"color": "0xFFE156", "bg_color": "0x1E2A78@0.85", "border_color": "0x89CFF0", "border_width": 4},
    "default":    {"color": "white",  "bg_color": "black@0.60",    "border_color": "",         "border_width": 0},
}


def _safe_text(s: str) -> str:
    """
    Экранирует символы, опасные для FFmpeg drawtext text-параметра.
    Покрывает самые частые: :, ', \\, %.
    """
    return (s.replace("\\", "\\\\")
             .replace(":", "\\:")
             .replace("'", "\u2019")   # умная кавычка — безопаснее
             .replace("%", "\\%"))


def _y_expr(position: str, fontsize: int) -> str:
    """Переводит 'center'/'top'/'upper-third' в y-выражение FFmpeg."""
    if position == "top":
        return str(SAFE_TOP_Y)
    if position == "upper-third":
        return f"h*0.30-{fontsize // 2}"
    # center
    return f"(h-text_h)/2"


def _autofit_fontsize(text: str, base_fs: int, max_width_px: int = 960) -> int:
    """
    Режет fontsize если текст не влезает в max_width_px.
    Эмпирика для Montserrat-Bold: ~0.55 × fontsize на символ.
    """
    if not text:
        return base_fs
    approx_max = int(max_width_px / max(1, len(text)) / 0.55)
    return max(36, min(base_fs, approx_max))


def apply_palette_style(cfg: HookCardConfig, palette_name: str) -> HookCardConfig:
    """
    Применяет пресет цветов из HOOK_PALETTE_STYLES к HookCardConfig,
    если пользователь не выставил цвета явно (color/bg_color — defaults).
    Возвращает тот же объект (in-place), чтобы было удобно chain-ить.
    """
    style = HOOK_PALETTE_STYLES.get(palette_name)
    if not style:
        return cfg
    cfg.color = str(style.get("color", cfg.color))
    cfg.bg_color = str(style.get("bg_color", cfg.bg_color))
    cfg.border_color = str(style.get("border_color", cfg.border_color))
    cfg.border_width = int(style.get("border_width", cfg.border_width))
    return cfg


def build_hook_card_filter(
    cfg: HookCardConfig,
    font_path: str,
    hook_end_sec: float | None = None,
    max_width_px: int = 960,
) -> str:
    """
    Возвращает drawtext-фильтр для первого кадра.

    Args:
        cfg: HookCardConfig с текстом и параметрами.
        font_path: путь к .ttf, совместимо с bundle1_karaoke.
        hook_end_sec: когда выключить hook-card. По умолчанию = cfg.duration.
        max_width_px: макс. ширина в пикселях. fontsize автоматически
                     уменьшается, если текст не влезает.

    Returns:
        Строка вида "drawtext=...:enable='lt(t,N)'" для filter_complex.
    """
    end = hook_end_sec if hook_end_sec is not None else cfg.duration
    text = _safe_text(cfg.text)
    fs = _autofit_fontsize(cfg.text, cfg.fontsize, max_width_px)
    y = _y_expr(cfg.y_position, fs)
    border_parts = ""
    if cfg.border_width > 0 and cfg.border_color:
        border_parts = f":borderw={cfg.border_width}:bordercolor={cfg.border_color}"
    return (
        f"drawtext=fontfile='{font_path}'"
        f":text='{text}'"
        f":fontsize={fs}"
        f":fontcolor={cfg.color}"
        f":box=1:boxcolor={cfg.bg_color}:boxborderw=28"
        f"{border_parts}"
        f":shadowcolor=black@0.55:shadowx=2:shadowy=3"
        f":x=(w-text_w)/2"
        f":y={y}"
        f":enable='lt(t,{end:.2f})'"
    )


def pick_hook_template(
    streams: Optional[int] = None,
    genre: Optional[str] = None,
) -> tuple[str, str]:
    """
    Эвристика выбора hook-шаблона под контекст трека.
    Возвращает (template_key, рендеренный_текст).
    """
    # Стримы 0-500 — максимально выгодный ракурс "гейткипю"
    if streams is not None and streams < 500:
        return "gatekeeper", HOOK_TEMPLATES["gatekeeper"]
    # Стримы 500-5000 — "почему никто не знает"
    if streams is not None and streams < 5000:
        return "curiosity", HOOK_TEMPLATES["curiosity"]
    # Стримы 5K-50K — "только X стримов"
    if streams is not None and streams < 50_000:
        return "streams_count", HOOK_TEMPLATES["streams_count"].format(streams=_fmt_streams(streams))
    # Dark/phonk/drill → warning
    if genre and genre in {"phonk", "drill", "trap-flex"}:
        return "warning", HOOK_TEMPLATES["warning"]
    # По умолчанию — POV
    return "pov", HOOK_TEMPLATES["pov"]


def _fmt_streams(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n // 1000}K"
    return f"{n // 1_000_000}M"


# ---------------------------------------------------------------------------
#  Track-card (мини-плашка внутри ролика)
# ---------------------------------------------------------------------------


@dataclass
class TrackCardConfig:
    track_name: str
    artist: str = ""
    show_at: float = 8.0             # начинает показываться, сек от старта ролика
    duration: float = 4.0            # сколько висит
    fontsize: int = 36
    color: str = "white"
    bg_color: str = "black@0.60"
    prefix: str = "TRACK"            # без эмодзи — FFmpeg на них иногда ругается


def build_track_card_filter(
    cfg: TrackCardConfig,
    font_path: str,
    resolution: tuple[int, int] = (1080, 1920),
) -> str:
    """
    Плашка «TRACK: Name — Artist» появляется на show_at, висит duration секунд.
    Позиция — в нижней 1/3, но выше safe-zone TikTok UI.
    """
    _w, h = resolution
    text_raw = f"{cfg.prefix}: {cfg.track_name}"
    if cfg.artist:
        text_raw += f" — {cfg.artist}"
    text = _safe_text(text_raw)
    y = max(SAFE_TOP_Y, int(h * 0.78))
    end = cfg.show_at + cfg.duration
    # Fade in/out через alpha-выражение (0.3с)
    fade = 0.3
    alpha_expr = (
        f"if(lt(t,{cfg.show_at:.2f}),0,"
        f"if(lt(t,{cfg.show_at + fade:.2f}),(t-{cfg.show_at:.2f})/{fade:.2f},"
        f"if(lt(t,{end - fade:.2f}),1,"
        f"if(lt(t,{end:.2f}),({end:.2f}-t)/{fade:.2f},0))))"
    )
    return (
        f"drawtext=fontfile='{font_path}'"
        f":text='{text}'"
        f":fontsize={cfg.fontsize}"
        f":fontcolor={cfg.color}"
        f":box=1:boxcolor={cfg.bg_color}:boxborderw=14"
        f":x=(w-text_w)/2"
        f":y={y}"
        f":alpha='{alpha_expr}'"
        f":enable='between(t,{cfg.show_at:.2f},{end:.2f})'"
    )


# ---------------------------------------------------------------------------
#  UTM-линки и описание под видео
# ---------------------------------------------------------------------------


def build_utm_link(
    spotify_url: str,
    video_id: str,
    platform: str = "tiktok",
    campaign: str = "agentmusic",
) -> str:
    """
    Добавляет UTM-метки к Spotify-ссылке для трекинга CTR.
    Безопасно: если URL уже содержит query — добавляет через &.
    """
    if not spotify_url:
        return ""
    params = {
        "utm_source": platform,
        "utm_medium": "short-form",
        "utm_campaign": campaign,
        "utm_content": video_id,
    }
    encoded = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    sep = "&" if "?" in spotify_url else "?"
    return f"{spotify_url}{sep}{encoded}"


@dataclass
class DescriptionConfig:
    track_name: str
    artist: str
    spotify_url: str
    video_id: str
    hook_line: str = ""             # лучшая строка из US-lyric analyzer
    genre_hashtags: list[str] = field(default_factory=list)
    platform: str = "tiktok"        # tiktok | reels | shorts


# Базовые алгоритм-дружественные хэштеги US 2025-2026.
# Микс: 2 macro (#fyp) + 3 niche-music + 3 slot под жанровые.
US_CORE_HASHTAGS = {
    "tiktok": ["fyp", "foryou", "musicdiscovery", "newmusic", "undergroundartist"],
    "reels":  ["reels", "reelsmusic", "newmusic", "musicdiscovery", "indieartist"],
    "shorts": ["shorts", "music", "newmusic", "musicdiscovery", "indie"],
}


def build_description(cfg: DescriptionConfig) -> str:
    """
    Готовое описание под пост в TikTok/Reels/Shorts.
    Формат проверен на алгоритм-дружественность US:
      1. Hook-line / track name — первая строка цепляет.
      2. Spotify-линк с UTM — вторая строка, для CTR.
      3. 1-строчный CTA в комменты.
      4. 8 хэштегов: 3 core + 3 niche-genre + 2 macro.
    """
    utm_link = build_utm_link(cfg.spotify_url, cfg.video_id, cfg.platform)
    header = cfg.hook_line.strip() or f"{cfg.track_name} — {cfg.artist}".strip(" —")
    core = US_CORE_HASHTAGS.get(cfg.platform, US_CORE_HASHTAGS["tiktok"])
    # Финальный набор — не больше 8, dedup, нижний регистр.
    all_tags = [h.lower().lstrip("#") for h in core]
    for h in cfg.genre_hashtags:
        h = h.lower().lstrip("#")
        if h and h not in all_tags:
            all_tags.append(h)
    all_tags = all_tags[:8]
    tags_line = " ".join(f"#{h}" for h in all_tags)
    cta_line = "which part hits hardest? drop a time ⬇️"
    parts = [
        header,
    ]
    if utm_link:
        parts.append(f"full track → {utm_link}")
    parts.extend([cta_line, "", tags_line])
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
#  Удобный one-shot: весь overlay-стек одной строкой для filter_complex
# ---------------------------------------------------------------------------


def build_full_overlay_chain(
    hook: Optional[HookCardConfig],
    track_card: Optional[TrackCardConfig],
    font_path: str,
    resolution: tuple[int, int] = (1080, 1920),
) -> str:
    """
    Собирает готовую цепочку drawtext-фильтров (через запятую),
    которую можно подставить в конец существующего filter_complex.

    Вернёт пустую строку, если обе конфигурации None.
    """
    parts: list[str] = []
    if hook:
        parts.append(build_hook_card_filter(hook, font_path))
    if track_card:
        parts.append(build_track_card_filter(track_card, font_path, resolution))
    return ",".join(parts)
