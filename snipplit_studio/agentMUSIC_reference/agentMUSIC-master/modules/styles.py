"""
Стили текста для караоке-видео.
Адаптированы под двухслойный Apple Music scroll (active + context).
"""

STYLE_PRESETS = {
    "glow": {
        "label": "Glow",
        "color_active": "white",
        "color_context": "0x4488CC",
        "border_color": "0x0096FF",
        "shadow_color": "0x0096FF@0.6",
    },
    "neon": {
        "label": "Neon",
        "color_active": "0xFF00C8",
        "color_context": "0x6B3FA0",
        "border_color": "0x00FFFF",
        "shadow_color": "0xFF00C8@0.7",
    },
    "clean": {
        "label": "Clean",
        "color_active": "0xF5E6D0",
        "color_context": "0x9B8B7A",
        "border_color": "black",
        "shadow_color": "black@0.3",
    },
    "fire": {
        "label": "Fire",
        "color_active": "0xFFC832",
        "color_context": "0x8B5A00",
        "border_color": "0x8B1400",
        "shadow_color": "0xFF5000@0.7",
    },
}

DEFAULT_STYLE = "clean"
