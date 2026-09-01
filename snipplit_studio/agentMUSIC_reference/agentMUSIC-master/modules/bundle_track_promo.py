"""
Bundle Track Promo — главный формат ПРОДВИЖЕНИЯ ноунейм-трека.

Отличие от других bundle:
  - Задача НЕ красиво выглядеть, а КОНВЕРТИРОВАТЬ view → stream.
  - Каждый из 4 актов решает одну задачу воронки:

  [0.0—2.5с] HOOK (pattern interrupt)
    Задача: остановить скролл
    Сборка: hook-card крупный, blur cover как фон, audio тишина/подводка

  [2.5—10с] CHORUS (прикольно / хедонически)
    Задача: доказать что трек цепляет
    Сборка: kinetic hero-word на лучшем моменте припева (viral_segment_picker)
            cover art inset 160×160 в правом нижнем углу — attribution builds

  [10—15с] REVEAL (идентификация)
    Задача: зритель запомнил ЧТО за трек
    Сборка: cover art 70% экрана, crossfade zoom, artist 80px, track 64px,
            5 секунд подряд — достаточно чтобы читнуть и запомнить

  [15—21с] CTA (конверсия)
    Задача: дать пути к Spotify
    Сборка: "save this before it blows up", Spotify mockup playbar,
            UTM-URL / QR code, continued chorus

Используется существующая инфра:
  - viral_segment_picker для выбора лучших 21с
  - cta_overlay для hook-card
  - spotify_cover_fetcher для cover jpg
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .types import LyricsLine
from .cta_overlay import HookCardConfig, apply_palette_style, _safe_text
from .bundle1_karaoke import (
    _alpha_for_dist,
    _build_piecewise_expr,
    _smooth_keyframes,
    _wrap_text,
    _esc as _karaoke_esc,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Config + timings
# ---------------------------------------------------------------------------


@dataclass
class TrackPromoTimings:
    """Относительно ролика, в секундах."""
    hook_start: float = 0.0
    hook_end: float = 2.5
    chorus_start: float = 2.5
    chorus_end: float = 10.0
    reveal_start: float = 10.0
    reveal_end: float = 15.0
    cta_start: float = 15.0
    cta_end: float = 21.0
    # cinematic intro — обложка крупно в первые ~1.2 сек (останавливает скролл)
    intro_end: float = 1.2
    # финальный blow-up CTA в последние ~1.5 сек (Artist • Track • out now)
    finale_start: float = 19.5


@dataclass
class TrackPromoConfig:
    audio_path: str                      # припев mp3
    lyrics: list[LyricsLine]             # относительные (0 = начало аудио)
    output_path: str
    font_path: str
    duration: float = 21.0
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    # Промо-данные
    track_name: str = ""
    artist_name: str = ""
    cover_path: Optional[str] = None     # jpg/png 640×640+
    spotify_url: str = ""                # с UTM
    # Копирайт и CTA
    hook_phrase: str = "you need to hear this"
    palette_name: str = "default"        # sad-girl / trap / dark / dream-pop / default
    cta_text: str = "save this before it blows up"
    # Тайминги (можно подогнать под duration)
    timings: TrackPromoTimings = field(default_factory=TrackPromoTimings)
    # Качество
    crf: int = 21
    preset: str = "veryfast"
    # Loudness normalization
    apply_loudnorm: bool = True
    loudnorm_target: float = -14.0
    # Loop-stitch на финал для TikTok
    loop_stitch: bool = True
    loop_stitch_duration: float = 0.5


# Палитры bg под каждую палитру (для акта HOOK и CTA — фоном за cover)
PROMO_PALETTE_BG = {
    "sad-girl":   "0x1B0B2E",
    "trap":       "0x000000",
    "dark":       "0x0A0A0A",
    "dream-pop":  "0x1E2A78",
    "default":    "0x0F0E17",
}


# Караоке-палитра для текста припева: активная строка + тусклый контекст + glow
# под каждый стиль трека. Формат FFmpeg: 0xRRGGBB / 0xRRGGBB@alpha.
CHORUS_LYRIC_STYLES: dict[str, dict[str, str]] = {
    "sad-girl":   {"color_active": "0xFFE1F5", "color_context": "0xB08BA0", "glow": "0xFF4D9E"},
    "trap":       {"color_active": "0xFFD700", "color_context": "0x8F7A00", "glow": "0xFF8C00"},
    "dark":       {"color_active": "0xFFFFFF", "color_context": "0x9B8FB5", "glow": "0x7F00FF"},
    "dream-pop":  {"color_active": "0xFFF4A3", "color_context": "0x89A0D0", "glow": "0x89CFF0"},
    "default":    {"color_active": "0xF5E6D0", "color_context": "0x9B8B7A", "glow": "0x1DB954"},
}


# ---------------------------------------------------------------------------
#  Акты: filter-строки для FFmpeg filter_complex
# ---------------------------------------------------------------------------


def _act_hook_card_filter(cfg: TrackPromoConfig) -> str:
    """
    Акт 1 (0-2.5с): hook-фраза крупно над blur-фоном из cover.

    Выход фильтра подключается к layer поверх bg.
    """
    hc = HookCardConfig(
        text=cfg.hook_phrase,
        duration=cfg.timings.hook_end,
        fontsize=84,                                # крупнее стандарта
        y_position="center",
    )
    apply_palette_style(hc, cfg.palette_name)
    # Hook-card появляется ПОСЛЕ intro-кадра с обложкой (чтобы cover-крупно
    # первым зацепил взгляд), т.е. с intro_end до hook_end.
    start = cfg.timings.intro_end
    end = cfg.timings.hook_end
    text = _safe_text(cfg.hook_phrase)
    # autofit
    length = max(1, len(cfg.hook_phrase))
    max_w = int(cfg.resolution[0] * 0.9)
    fs = max(48, min(hc.fontsize, int(max_w / length / 0.55)))
    border = ""
    if hc.border_width > 0 and hc.border_color:
        border = f":borderw={hc.border_width}:bordercolor={hc.border_color}"
    return (
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{text}'"
        f":fontsize={fs}"
        f":fontcolor={hc.color}"
        f":box=1:boxcolor={hc.bg_color}:boxborderw=36"
        f"{border}"
        f":shadowcolor=black@0.65:shadowx=3:shadowy=5"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":enable='between(t,{start:.2f},{end:.2f})'"
    )


def _act_chorus_hero_filters(cfg: TrackPromoConfig) -> list[str]:
    """
    Акт 2 (chorus window): Karaoke scroll по центру экрана.

    Apple-Music лента:
      • Активная строка — крупно, ярко, строго по центру (y = h/2)
      • ±1 и ±2 соседние строки — мельче, тускло, сверху (уже спето) и снизу (будет)
      • При смене активной строки вся лента плавно скроллится вверх на gap
      • Уже спетые строки уезжают вверх и тускнеют; будущие снизу — наоборот
        ярчеют и «перетекают» в активную позицию по центру

    КРИТИЧНО: lyrics тайминги = позиции строк в audio. Окно: [chorus_start, chorus_end].
    """
    w, h = cfg.resolution
    t_start = cfg.timings.chorus_start
    t_end = cfg.timings.chorus_end

    # Палитра под стиль трека
    palette = CHORUS_LYRIC_STYLES.get(cfg.palette_name, CHORUS_LYRIC_STYLES["default"])
    color_active = palette["color_active"]
    color_context = palette["color_context"]
    glow_color = palette["glow"]

    # Собираем строки, пересекающиеся с окном акта
    raw_lines: list[tuple[str, float, float]] = []
    for ln in cfg.lyrics:
        text = (ln.text or "").strip()
        if not text:
            continue
        ls = float(ln.start)
        le = float(ln.end)
        if le <= t_start or ls >= t_end:
            continue
        raw_lines.append((text, ls, le))

    # Fallback: если разметка строк отсутствует — агрегируем слова по паузам
    if not raw_lines:
        flat_words = []
        for ln in cfg.lyrics:
            for w_ in ln.words or []:
                wt = (w_.word or "").strip()
                if not wt:
                    continue
                ws = float(w_.start)
                we = float(w_.end)
                if we <= t_start or ws >= t_end:
                    continue
                flat_words.append((wt, ws, we))
        if flat_words:
            cur_words: list[str] = []
            cur_start = flat_words[0][1]
            last_end = flat_words[0][2]
            for wt, ws, we in flat_words:
                if cur_words and (ws - last_end > 0.40 or len(" ".join(cur_words)) + len(wt) > 48):
                    raw_lines.append((" ".join(cur_words), cur_start, last_end))
                    cur_words = []
                    cur_start = ws
                if not cur_words:
                    cur_start = ws
                cur_words.append(wt)
                last_end = we
            if cur_words:
                raw_lines.append((" ".join(cur_words), cur_start, last_end))

    if not raw_lines:
        return []

    # Размеры: активная крупная, контекстная мельче. gap — вертикальный шаг ленты.
    fs_active = 76
    fs_context = 50
    gap = int(fs_active * 1.9)           # ~144 px — 2 строки сверху/снизу влезают
    y_center = h // 2
    # Wrap длинных строк в sub-lines (чтобы активная помещалась в 88% ширины)
    max_chars = max(8, int((w * 0.88) / (fs_active * 0.55)))

    display: list[tuple[str, float, float]] = []  # (text, start, end) по sub-line
    for text, ls, le in raw_lines:
        subs = _wrap_text(text, max_chars)
        dur = max(0.1, le - ls)
        sub_dur = dur / len(subs)
        for j, sub in enumerate(subs):
            s = ls + j * sub_dur
            e = ls + (j + 1) * sub_dur
            display.append((sub, s, e))

    N = len(display)
    if N == 0:
        return []

    # Лид-ин/аут и длительность перехода
    TRANS = 0.40
    LEAD = 0.5
    t_first = display[0][1]
    t_last_end = display[-1][2]

    # Временная директория для textfile='...'
    sid = uuid.uuid4().hex[:8]
    tmp = os.path.join(tempfile.gettempdir(), f"am_tp_{sid}")
    os.makedirs(tmp, exist_ok=True)

    # Клипирование окна видимости: плюс небольшой запас на fade
    vis_start = max(t_start, t_first - LEAD - 0.1)
    vis_end = min(t_end + 0.1, t_last_end + LEAD + 0.1)

    filters: list[str] = []

    for i in range(N):
        # === Y keyframes: позиция строки i во времени ===
        # До первой активной — строка на позиции (y_center + i*gap) относительно центра
        # В момент display[j].start — активная = j, позиция i = y_center + (i-j)*gap
        y_kf: list[tuple[float, float]] = []
        y_kf.append((max(0.0, t_first - LEAD), float(y_center + i * gap)))
        for j in range(N):
            y_kf.append((display[j][1], float(y_center + (i - j) * gap)))
        y_kf.append((t_last_end + LEAD, float(y_center + (i - (N - 1)) * gap)))

        smooth_y = _smooth_keyframes(y_kf, TRANS)
        y_expr_line = _build_piecewise_expr(smooth_y)

        # === Файлы текста для активного и контекстного слоя ===
        p_ctx = os.path.join(tmp, f"ctx_{i:03d}.txt")
        with open(p_ctx, "w", encoding="utf-8") as f:
            f.write(display[i][0])
        ep_ctx = _karaoke_esc(p_ctx)

        p_act = os.path.join(tmp, f"act_{i:03d}.txt")
        with open(p_act, "w", encoding="utf-8") as f:
            f.write(display[i][0])
        ep_act = _karaoke_esc(p_act)

        # === СЛОЙ 1: контекстный (мелкий, тусклый, всегда видимый в окне акта) ===
        a_kf_ctx: list[tuple[float, float]] = []
        init_alpha = _alpha_for_dist(i) if i != 0 else 0.0
        a_kf_ctx.append((max(0.0, t_first - LEAD), 0.0))
        a_kf_ctx.append((max(0.01, t_first - LEAD * 0.4), init_alpha))
        for j in range(N):
            dist = abs(i - j)
            # Когда строка активна (dist=0) — контекст гасим, работает яркий слой
            ctx_alpha = 0.0 if dist == 0 else _alpha_for_dist(dist)
            a_kf_ctx.append((display[j][1], ctx_alpha))
        final_alpha = _alpha_for_dist(abs(i - (N - 1))) if i != N - 1 else 0.0
        a_kf_ctx.append((t_last_end, final_alpha))
        a_kf_ctx.append((t_last_end + LEAD, 0.0))
        smooth_a_ctx = _smooth_keyframes(a_kf_ctx, TRANS * 0.7)
        a_expr_ctx = _build_piecewise_expr(smooth_a_ctx)

        filters.append(
            f"drawtext=fontfile='{cfg.font_path}'"
            f":textfile='{ep_ctx}'"
            f":fontsize={fs_context}"
            f":fontcolor={color_context}"
            f":borderw=0"
            f":shadowcolor=black@0.55:shadowx=1:shadowy=2"
            f":x=(w-text_w)/2"
            f":y='{y_expr_line}'"
            f":alpha='{a_expr_ctx}'"
            f":enable='between(t,{vis_start:.3f},{vis_end:.3f})'"
        )

        # === СЛОЙ 2: активный (крупный, яркий, палитровый + glow) ===
        a_kf_act: list[tuple[float, float]] = []
        a_kf_act.append((max(0.0, t_first - LEAD), 0.0))
        for j in range(N):
            a_kf_act.append((display[j][1], 1.0 if j == i else 0.0))
        a_kf_act.append((t_last_end, 0.0))
        a_kf_act.append((t_last_end + LEAD, 0.0))
        smooth_a_act = _smooth_keyframes(a_kf_act, TRANS * 0.7)
        a_expr_act = _build_piecewise_expr(smooth_a_act)

        # Компенсируем разницу font-size чтобы базовая линия активной совпадала
        y_offset = int((fs_active - fs_context) * 0.4)
        y_expr_active = f"({y_expr_line}-{y_offset})"

        filters.append(
            f"drawtext=fontfile='{cfg.font_path}'"
            f":textfile='{ep_act}'"
            f":fontsize={fs_active}"
            f":fontcolor={color_active}"
            f":borderw=3:bordercolor={glow_color}@0.55"
            f":shadowcolor=black@0.75:shadowx=2:shadowy=4"
            f":x=(w-text_w)/2"
            f":y='{y_expr_active}'"
            f":alpha='{a_expr_act}'"
            f":enable='between(t,{vis_start:.3f},{vis_end:.3f})'"
        )

    return filters


def _act_reveal_texts(cfg: TrackPromoConfig) -> list[str]:
    """
    Акт 3 (10-15с): текст artist + track крупно под cover.
    Cover сам накладывается через input (см. build_track_promo).
    """
    w, h = cfg.resolution
    ts = cfg.timings.reveal_start
    te = cfg.timings.reveal_end

    artist = (cfg.artist_name or "Unknown Artist").strip()
    name = (cfg.track_name or "Unknown Track").strip()
    # Обрезаем длинные
    if len(artist) > 25:
        artist = artist[:23] + "..."
    if len(name) > 28:
        name = name[:26] + "..."

    # Artist — крупно
    artist_y = int(h * 0.72)
    name_y = int(h * 0.80)

    filters: list[str] = []
    fade_in = 0.4
    fade_out = 0.4
    alpha_base = (
        f"if(lt(t,{ts:.3f}),0,"
        f"if(lt(t,{ts + fade_in:.3f}),(t-{ts:.3f})/{fade_in:.3f},"
        f"if(lt(t,{te - fade_out:.3f}),1,"
        f"if(lt(t,{te:.3f}),({te:.3f}-t)/{fade_out:.3f},0))))"
    )
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(artist)}'"
        f":fontsize=80"
        f":fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":shadowcolor=black@0.7:shadowx=3:shadowy=5"
        f":x=(w-text_w)/2:y={artist_y}"
        f":alpha='{alpha_base}'"
        f":enable='between(t,{ts:.2f},{te:.2f})'"
    )
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(name)}'"
        f":fontsize=56"
        f":fontcolor=0xFFE156"
        f":borderw=4:bordercolor=black"
        f":shadowcolor=black@0.6:shadowx=2:shadowy=4"
        f":x=(w-text_w)/2:y={name_y + 100}"
        f":alpha='{alpha_base}'"
        f":enable='between(t,{ts:.2f},{te:.2f})'"
    )
    return filters


def _autofit_fs(text: str, base_fs: int, max_w: int) -> int:
    """Подгон fontsize под max_width (коэффициент 0.55 для Bold)."""
    if not text:
        return base_fs
    approx = int(max_w / max(1, len(text)) / 0.55)
    return max(36, min(base_fs, approx))


def _act_cta_filters(cfg: TrackPromoConfig) -> list[str]:
    """
    Акт 4 (cta_start → finale_start): «save this before it blows up» + Spotify.
    Финальный blow-up (finale_start → duration): Artist • Track • out now крупно.
    """
    w, h = cfg.resolution
    ts = cfg.timings.cta_start
    # Основной CTA-текст теперь заканчивается перед финальным blow-up,
    # чтобы не наложиться на него.
    te = min(cfg.timings.cta_end, cfg.timings.finale_start)

    cta_y = int(h * 0.42)
    spotify_y = int(h * 0.55)

    filters: list[str] = []
    fade_in = 0.3
    fade_out = 0.3
    alpha = (
        f"if(lt(t,{ts:.3f}),0,"
        f"if(lt(t,{ts + fade_in:.3f}),(t-{ts:.3f})/{fade_in:.3f},"
        f"if(lt(t,{te - fade_out:.3f}),1,"
        f"if(lt(t,{te:.3f}),({te:.3f}-t)/{fade_out:.3f},0))))"
    )

    # CTA line — autofit под ширину экрана минус 10% padding
    cta_fs = _autofit_fs(cfg.cta_text, 72, int(w * 0.88))
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(cfg.cta_text)}'"
        f":fontsize={cta_fs}"
        f":fontcolor=white"
        f":box=1:boxcolor=0x1DB954@0.90:boxborderw=28"      # Spotify green!
        f":borderw=4:bordercolor=black"
        f":x=(w-text_w)/2:y={cta_y}"
        f":alpha='{alpha}'"
        f":enable='between(t,{ts:.2f},{te:.2f})'"
    )
    # Spotify подсказка
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='link in bio - Spotify'"
        f":fontsize=44"
        f":fontcolor=0x1DB954"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y={spotify_y}"
        f":alpha='{alpha}'"
        f":enable='between(t,{ts:.2f},{te:.2f})'"
    )

    # ── FINALE (последние ~1.5 сек): тёмная плёнка + Artist • Track • out now
    fs = cfg.timings.finale_start
    fe = cfg.timings.cta_end
    f_fade_in = 0.25
    finale_alpha = (
        f"if(lt(t,{fs:.3f}),0,"
        f"if(lt(t,{fs + f_fade_in:.3f}),(t-{fs:.3f})/{f_fade_in:.3f},1))"
    )
    artist_clean = (cfg.artist_name or "Unknown Artist").strip()
    track_clean = (cfg.track_name or "Unknown Track").strip()
    if len(artist_clean) > 28:
        artist_clean = artist_clean[:26] + "…"
    if len(track_clean) > 30:
        track_clean = track_clean[:28] + "…"
    # Затемняющий box на весь экран — контраст для CTA
    filters.append(
        f"drawbox=x=0:y=0:w={w}:h={h}:color=black@0.72:t=fill:"
        f"enable='between(t,{fs:.3f},{fe:.3f})'"
    )
    # «out now» — мелко сверху
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='OUT NOW'"
        f":fontsize=52"
        f":fontcolor=0x1DB954"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y={int(h * 0.30)}"
        f":alpha='{finale_alpha}'"
        f":enable='between(t,{fs:.3f},{fe:.3f})'"
    )
    # Артист — очень крупно
    artist_fs = _autofit_fs(artist_clean, 118, int(w * 0.88))
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(artist_clean)}'"
        f":fontsize={artist_fs}"
        f":fontcolor=white"
        f":borderw=6:bordercolor=black"
        f":shadowcolor=black@0.8:shadowx=3:shadowy=6"
        f":x=(w-text_w)/2:y={int(h * 0.40)}"
        f":alpha='{finale_alpha}'"
        f":enable='between(t,{fs:.3f},{fe:.3f})'"
    )
    # Трек — крупно, акцентный цвет
    track_fs = _autofit_fs(track_clean, 84, int(w * 0.88))
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='{_safe_text(track_clean)}'"
        f":fontsize={track_fs}"
        f":fontcolor=0xFFE156"
        f":borderw=5:bordercolor=black"
        f":shadowcolor=black@0.7:shadowx=3:shadowy=5"
        f":x=(w-text_w)/2:y={int(h * 0.52)}"
        f":alpha='{finale_alpha}'"
        f":enable='between(t,{fs:.3f},{fe:.3f})'"
    )
    # Платформы — мелким шрифтом снизу
    filters.append(
        f"drawtext=fontfile='{cfg.font_path}'"
        f":text='Spotify  •  Apple Music  •  YouTube Music'"
        f":fontsize=38"
        f":fontcolor=white@0.85"
        f":borderw=2:bordercolor=black"
        f":x=(w-text_w)/2:y={int(h * 0.64)}"
        f":alpha='{finale_alpha}'"
        f":enable='between(t,{fs:.3f},{fe:.3f})'"
    )
    return filters


# ---------------------------------------------------------------------------
#  Главная сборка
# ---------------------------------------------------------------------------


def build_track_promo(cfg: TrackPromoConfig) -> str:
    """
    Собирает 4-актный promo-ролик.

    Inputs:
      [0:v] bg color (палитра)
      [1:v] cover.jpg (если есть) — используется как blur bg в акте 1
                                   и как hero reveal в акте 3
      [2:a] audio припева
    """
    if not os.path.exists(cfg.audio_path):
        raise RuntimeError(f"audio not found: {cfg.audio_path}")
    if not os.path.exists(cfg.font_path):
        raise RuntimeError(f"font not found: {cfg.font_path}")

    w, h = cfg.resolution
    os.makedirs(os.path.dirname(os.path.abspath(cfg.output_path)) or ".", exist_ok=True)

    bg_color = PROMO_PALETTE_BG.get(cfg.palette_name, PROMO_PALETTE_BG["default"])
    has_cover = bool(cfg.cover_path and os.path.exists(cfg.cover_path))

    # Filter graph
    # [0:v] bg цвет (сплошной)
    # [1:v] cover (если есть):
    #   а) blur+scale bg на акт 1 (hook)
    #   б) small inset в акте 2 (chorus) — 220×220 в правом нижнем
    #   в) large reveal в акте 3 (reveal) — 70% ширины, центрированно
    #
    # Акты overlayятся друг на друга через enable=between().

    # Layer 0: base color
    chain_parts: list[str] = []
    inputs_count = 1  # [0:v] bg

    if has_cover:
        # Layer 1: cover blur-bg (полный экран, сильный blur) — fone весь ролик.
        # Это убирает «пустоту» монотонного цвета: вместо пурпурной стены — размытая
        # обложка в цветах трека. Глубина → зритель чувствует, что это про ЭТОТ трек.
        inputs_count = 2
        chain_parts.append(
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=luma_radius=30:luma_power=1:"
            f"chroma_radius=18:chroma_power=1,"
            f"eq=brightness=-0.18:saturation=1.10,"
            f"setsar=1[hook_bg]"
        )
        # Layer 2 (NEW): cover_intro — крупно в первые intro_end секунд.
        # Hook-shot: лицо с обложки бросается в глаза → стоп скролла.
        cov_intro_w = int(w * 0.86)
        cov_intro_h = cov_intro_w
        intro_frames = max(1, int(cfg.timings.intro_end * cfg.fps))
        # Лёгкий zoom 1.00 → 1.04 линейно. Oversampled 2× + lanczos → без дребезга.
        intro_step = 0.04 / max(1, intro_frames - 1)
        chain_parts.append(
            f"[1:v]scale={cov_intro_w*2}:{cov_intro_h*2}:flags=lanczos,"
            f"zoompan=z='1+{intro_step:.7f}*in'"
            f":d={intro_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":fps={cfg.fps}:s={cov_intro_w*2}x{cov_intro_h*2},"
            f"scale={cov_intro_w}:{cov_intro_h}:flags=lanczos,"
            f"setsar=1[cover_intro]"
        )
        # Layer 3: cover large reveal (70% экрана, акт 3) с мягким «дыханием».
        cov_w = int(w * 0.70)
        cov_h = cov_w
        big_frames = max(1, int(cfg.duration * cfg.fps))
        # Период дыхания ≈ 2×downbeat на 120 BPM → 1 сек; для ролика берём 3с
        # (визуально успокаивает). Амплитуда 0.03 (1.00 ↔ 1.03).
        breath_period = max(1, int(3.0 * cfg.fps))
        chain_parts.append(
            f"[1:v]scale={cov_w*2}:{cov_h*2}:flags=lanczos,"
            f"zoompan=z='1.02+0.02*sin(2*PI*in/{breath_period})'"
            f":d={big_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":fps={cfg.fps}:s={cov_w*2}x{cov_h*2},"
            f"scale={cov_w}:{cov_h}:flags=lanczos,setsar=1[cover_large]"
        )
        # Layer 4: cover inset (220×220) с лёгкой пульсацией в такт — акт 2.
        # Небольшая связь визуала с музыкой → ролик ощущается «в ритме».
        small_pulse_period = max(1, int(1.5 * cfg.fps))
        chain_parts.append(
            f"[1:v]scale=440:440:flags=lanczos,"
            f"zoompan=z='1.02+0.02*sin(2*PI*in/{small_pulse_period})'"
            f":d={big_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":fps={cfg.fps}:s=440x440,"
            f"scale=220:220:flags=lanczos,setsar=1[cover_small]"
        )

    # Overlay chain
    if has_cover:
        # (1) base + blurred cover-bg НА ВЕСЬ РОЛИК (не только hook).
        # Монотонного пурпурного больше нет — всегда «глубина» из обложки.
        chain_parts.append(f"[0:v][hook_bg]overlay=0:0[v1]")

        # (2) cover_intro — крупно по центру в первые intro_end сек, останавливает скрол.
        intro_x = (w - int(w * 0.86)) // 2
        intro_y = int(h * 0.12)
        chain_parts.append(
            f"[v1][cover_intro]overlay={intro_x}:{intro_y}:"
            f"enable='lt(t,{cfg.timings.intro_end:.2f})'[v1b]"
        )
        # (3) cover_large в акте reveal (центр, верхние 65% экрана)
        cov_x = (w - int(w * 0.70)) // 2
        cov_y = int(h * 0.10)          # отступ сверху 10% экрана
        chain_parts.append(
            f"[v1b][cover_large]overlay={cov_x}:{cov_y}:"
            f"enable='between(t,{cfg.timings.reveal_start:.2f},"
            f"{cfg.timings.reveal_end:.2f})'[v2]"
        )
        # (4) cover_small в акте chorus (правый нижний)
        inset_x = w - 220 - 40
        inset_y = h - 220 - 180      # отступ снизу чтобы не перекрывать UI
        chain_parts.append(
            f"[v2][cover_small]overlay={inset_x}:{inset_y}:"
            f"enable='between(t,{cfg.timings.chorus_start:.2f},"
            f"{cfg.timings.chorus_end:.2f})'[v3]"
        )
        base_pad = "v3"
    else:
        base_pad = "0:v"

    # Текстовые overlays (все drawtext на base_pad)
    text_filters: list[str] = []
    text_filters.append(_act_hook_card_filter(cfg))
    text_filters += _act_chorus_hero_filters(cfg)
    text_filters += _act_reveal_texts(cfg)
    text_filters += _act_cta_filters(cfg)

    text_chain = ",".join(text_filters) if text_filters else "null"
    # Финальный цвет/текстура:
    #   • subtle film-grain (noise=10 temporal) — даёт «аналог», sad-girl / indie look
    #   • slight vignette (vignette=PI/5) — фокус к центру, поджимает края
    #   • format yuv420p — для совместимости
    finish_chain = "noise=alls=10:allf=t,vignette=angle=PI/5,format=yuv420p"
    chain_parts.append(f"[{base_pad}]{text_chain},{finish_chain}[vout]")

    filter_complex = ";".join(chain_parts)

    # FFmpeg command
    audio_args: list[str] = []
    if cfg.apply_loudnorm:
        audio_args = ["-af", f"loudnorm=I={cfg.loudnorm_target}:TP=-1.5:LRA=11.0"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"color=c={bg_color}:s={w}x{h}:d={cfg.duration:.3f}:r={cfg.fps}",
    ]
    if has_cover:
        # looped still image
        cmd += ["-loop", "1", "-t", f"{cfg.duration:.3f}", "-i", cfg.cover_path]
    cmd += ["-i", cfg.audio_path]

    audio_input_idx = inputs_count
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", f"{audio_input_idx}:a",
        "-t", f"{cfg.duration:.3f}",
        "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf),
        "-pix_fmt", "yuv420p",
        *audio_args,
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart",
        cfg.output_path,
    ]

    logger.info(
        f"build_track_promo: cover={bool(has_cover)} palette={cfg.palette_name} "
        f"→ {cfg.output_path}"
    )
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        # Для дебага пишем filter рядом с output (легко найти и почистить вместе
        # с output_dir), вместо /tmp где leak накапливается без ротации.
        dbg_path = cfg.output_path.rsplit(".", 1)[0] + ".filter.txt"
        try:
            with open(dbg_path, "w", encoding="utf-8") as dbg:
                dbg.write(filter_complex)
        except OSError:
            dbg_path = "(n/a)"
        raise RuntimeError(
            f"ffmpeg track_promo failed (rc={r.returncode}):\n"
            f"filter saved: {dbg_path}\n"
            f"stderr:\n{r.stderr[:2500]}"
        )
    if not os.path.exists(cfg.output_path):
        raise RuntimeError(f"output not created: {cfg.output_path}")

    if cfg.loop_stitch and cfg.loop_stitch_duration > 0:
        try:
            _apply_loop_stitch(cfg.output_path, cfg.loop_stitch_duration)
        except Exception as e:
            logger.warning(f"track_promo loop-stitch skipped: {e}")

    logger.info(f"build_track_promo done: size={os.path.getsize(cfg.output_path)} bytes")
    return cfg.output_path


def _apply_loop_stitch(video_path: str, crossfade_dur: float = 0.5) -> None:
    """Xfade последних X секунд к первым X — тот же приём что в kinetic/hypno."""
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
            raise RuntimeError("loop-stitch output пустой")
        os.replace(tmp_out.name, video_path)
    except Exception:
        if os.path.exists(tmp_out.name):
            try:
                os.unlink(tmp_out.name)
            except OSError:
                pass
        raise
