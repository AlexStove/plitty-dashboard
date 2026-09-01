"""human_touch.py — человечьи траектории пальца (non-root, через input motionevent).

Раньше свайпы были джиттер-прямые (`input swipe`). Здесь — НЕПРЕРЫВНЫЙ жест
точка-за-точкой: smoothstep-разгон/торможение + лёгкая дуга + гаусс-джиттер.
Это распределение, которое выучила touch_bilstm в server-144 (scroll/swipe/tap
с pressure/timing). Исполняется `input motionevent DOWN|MOVE|UP` — один жест,
без root, без sendevent.

TODO: подключить server-144 touch_bilstm_trained.pt для выученной динамики
конкретного «пользователя» (сейчас — аналитическая кривая того же вида).
"""
from __future__ import annotations

import math
import random
import subprocess
import os

from brain import winquiet  # noqa: F401  — гасит окна консоли у adb-субпроцессов под pythonw


_dir = os.path.dirname(__file__)
_ADB_PATH = os.path.join(_dir, "platform-tools", "adb.exe")
if not os.path.exists(_ADB_PATH):
    _ADB_PATH = os.path.join(os.path.dirname(_dir), "platform-tools", "adb.exe")
if not os.path.exists(_ADB_PATH):
    _ADB_PATH = "adb"

_DEVICE_PORT_CACHE = {}

def _get_device_port(serial: str) -> str:
    if serial in _DEVICE_PORT_CACHE:
        return _DEVICE_PORT_CACHE[serial]
    try:
        res = subprocess.run([_ADB_PATH, "-P", "5038", "devices"], capture_output=True, text=True, timeout=3)
        if serial in res.stdout:
            _DEVICE_PORT_CACHE[serial] = "5038"
            return "5038"
    except Exception:
        pass
    _DEVICE_PORT_CACHE[serial] = "5037"
    return "5037"

def _sh(serial: str, cmd: str, timeout: int = 15):
    port = _get_device_port(serial)
    return subprocess.run([_ADB_PATH, "-P", port, "-s", serial, "shell", cmd],
                          capture_output=True, timeout=timeout)


def _path(x1: int, y1: int, x2: int, y2: int, n: int) -> list[tuple[int, int]]:
    """Кривая человека: smoothstep (плавный разгон/торможение) + дуга вбок + дрожь."""
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy) or 1.0
    # перпендикуляр для естественной дуги (палец не идёт по линейке)
    px, py = -dy / dist, dx / dist
    bow = random.gauss(0, 0.07) * dist        # величина дуги
    pts = []
    for i in range(n):
        t = i / (n - 1)
        ease = t * t * (3 - 2 * t)            # smoothstep
        off = bow * math.sin(t * math.pi)     # дуга максимальна в середине
        x = x1 + dx * ease + px * off + random.gauss(0, 1.8)
        y = y1 + dy * ease + py * off + random.gauss(0, 1.8)
        pts.append((int(round(x)), int(round(y))))
    return pts


# Делегируем в единый слой human_gestures (спека 12 жестов). Старые сигнатуры
# сохранены для обратной совместимости — все текущие потребители апгрейдятся.
from brain import human_gestures as _hg


def swipe(serial: str, x1: int, y1: int, x2: int, y2: int, n: int | None = None):
    _hg.swipe(serial, x1, y1, x2, y2, n=n)


def tap(serial: str, x: int, y: int, bounds=None):
    # антидетект: смещение по comfort-zone руки персоны (уникальный паттерн тапа устройства)
    try:
        from brain.antidetect import device_profile as _dp
        x, y = _dp.tap_xy(serial, x, y)
    except Exception:
        pass
    _hg.tap(serial, x, y, bounds=bounds)


def scroll(serial: str, direction: str = "up", cx: int = 540, cy: int = 1200,
           amount: float = 0.5, h: int = 2340, w: int = 1080):
    _hg.scroll(serial, direction=direction, cx=cx, cy=cy, amount=amount, h=h, w=w)


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else None
    if not s:
        print("usage: python -m brain.human_touch <serial>")
        sys.exit(1)
    print("tap + scroll демо…")
    tap(s, 540, 1700)
    scroll(s, "up")
    scroll(s, "up")
    print("done")
