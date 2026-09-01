"""
Light Leaks — лёгкие световые засветки для анимированного фона.

Inline-подход: выражения встраиваются аддитивно в основной geq.
Все выражения используют ТОЛЬКО sin/cos/max/min/if/pow — никаких
sqrt, atan2, exp (они в 10-50x медленнее в geq на 1080x1920).

8 типов light leaks с palette-aware тинтингом.
"""

import random


def palette_tint(palette: dict) -> tuple[float, float, float]:
    """Извлечь RGB-тинт из самого яркого цвета палитры (0.0-1.0)."""
    c3 = palette["gradient"][2]
    mx = max(c3[0], c3[1], c3[2], 1)
    return (c3[0] / mx, c3[1] / mx, c3[2] / mx)


# ──────────────────────────────────────────────────────────────
# Лёгкие inline light leaks — только sin/cos/pow/max/if
# Возвращают (r_add, g_add, b_add) для аддитивного geq
# Яркость 30-60 (мягкие засветки без пересвета)
# ──────────────────────────────────────────────────────────────

def _ll_warm_wipes(pf, ph, tr, tg, tb):
    """Горизонтальные тёплые полосы."""
    base = f"pow(max(0,sin(2*PI*{pf * 0.3:.4f}*T+X/W*5+{ph:.2f})),6)*50"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_vertical_glow(pf, ph, tr, tg, tb):
    """Вертикальные мягкие полосы света."""
    base = f"pow(max(0,sin(2*PI*{pf * 0.2:.4f}*T+Y/H*4+{ph:.2f})),5)*45"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_diagonal_streaks(pf, ph, tr, tg, tb):
    """Диагональные полосы света."""
    base = f"pow(max(0,sin((X+Y)/(W*0.2)+2*PI*{pf * 0.5:.4f}*T+{ph:.2f})),8)*55"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_pulse(pf, ph, tr, tg, tb):
    """Мягкая пульсация — весь кадр мягко дышит."""
    base = f"pow(max(0,sin(2*PI*{pf * 0.15:.4f}*T+{ph:.2f})),3)*35"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_edge_burn(pf, ph, tr, tg, tb):
    """Засветки с краёв — через abs(X) без sqrt."""
    edge = "max(pow(abs(2.0*X/W-1),2),pow(abs(2.0*Y/H-1),2))"
    base = f"{edge}*pow(max(0,sin(2*PI*{pf * 0.12:.4f}*T+{ph:.2f})),3)*50"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_hard_bars(pf, ph, tr, tg, tb):
    """Геометрические полосы."""
    base = f"if(gt(sin(2*PI*{pf * 0.25:.4f}*T+X/W*6+Y/H*2+{ph:.2f}),0.75),45,0)"
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


def _ll_color_shift(pf, ph, tr, tg, tb):
    """Цветовой сдвиг — каналы с разной фазой."""
    r = f"pow(max(0,sin(2*PI*{pf * 0.3:.4f}*T+X/W*3+{ph:.2f})),5)*40*{tr:.2f}"
    g = f"pow(max(0,sin(2*PI*{pf * 0.3:.4f}*T+X/W*3+{ph + 2.1:.2f})),5)*40*{tg:.2f}"
    b = f"pow(max(0,sin(2*PI*{pf * 0.3:.4f}*T+X/W*3+{ph + 4.2:.2f})),5)*40*{tb:.2f}"
    return (r, g, b)


def _ll_wave_overlay(pf, ph, tr, tg, tb):
    """Волновая засветка — двойная синусоида."""
    base = (f"pow(max(0,sin(X/W*3.14+2*PI*{pf * 0.2:.4f}*T+{ph:.2f})"
            f"*sin(Y/H*2+2*PI*{pf * 0.15:.4f}*T)),2)*45")
    return (f"{base}*{tr:.2f}", f"{base}*{tg:.2f}", f"{base}*{tb:.2f}")


LIGHT_LEAKS = [
    ("warm_wipes", _ll_warm_wipes),
    ("vertical_glow", _ll_vertical_glow),
    ("diagonal_streaks", _ll_diagonal_streaks),
    ("pulse", _ll_pulse),
    ("edge_burn", _ll_edge_burn),
    ("hard_bars", _ll_hard_bars),
    ("color_shift", _ll_color_shift),
    ("wave_overlay", _ll_wave_overlay),
]


def build_inline_light_leak(
    palette: dict,
    pulse_freq: float,
    seed: int = 0,
) -> tuple[str, str, str]:
    """
    Выбирает light leak и возвращает (r_add, g_add, b_add) —
    лёгкие geq-выражения для аддитивного наложения.
    """
    rng = random.Random(seed + 77)
    tint = palette_tint(palette)
    _, ll_func = rng.choice(LIGHT_LEAKS)
    ph = rng.uniform(0, 6.28)
    return ll_func(pulse_freq, ph, *tint)
