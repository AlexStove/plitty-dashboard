"""human_gestures.py — единый человечий слой жестов (non-root).

Все касания фермы должны идти через него, а не через сырой `input tap/swipe/text`
(сырые — мгновенные, идеально прямые, фикс-паузы = палевно). Реализует спеку из 12
жестов: точка гаусс-к-центру, контакт down→удержание+микро-дрейф→up, кривые Безье с
переменной скоростью, тайминги без фикс-пауз, type с опечатками + ADBKeyboard для
кириллицы, бимодальное wait.

Без рута: исполняется `input motionevent DOWN|MOVE|UP` (удержание/дрейф/кривая есть,
давления/площади нет — для этого нужен /dev/input/minitouch с рутом). pinch/rotate
честно ограничены (мультитач без рута/minitouch недоступен) — помечены.
"""
from __future__ import annotations

import math
import random
import subprocess
import time
import os

# --- низкий уровень ---

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

def _sh(serial: str, cmd: str, timeout: int = 25):
    port = _get_device_port(serial)
    return subprocess.run([_ADB_PATH, "-P", port, "-s", serial, "shell", cmd],
                          capture_output=True, timeout=timeout)


def _u(a, b):
    return random.uniform(a, b)


def _sleep_ms(lo, hi):
    time.sleep(_u(lo, hi) / 1000.0)


def _gauss_point(x, y, bounds=None, edge=0.12):
    """Точка ВНУТРИ элемента: гаусс к центру + отступ от краёв (не центр-в-центр)."""
    if bounds:
        x1, y1, x2, y2 = bounds
        w, h = (x2 - x1), (y2 - y1)
        mx, my = w * edge, h * edge
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        # гаусс к центру, sigma ~ четверть размера, клип в [край+отступ]
        gx = random.gauss(cx, max(w / 4.5, 1))
        gy = random.gauss(cy, max(h / 4.5, 1))
        gx = min(max(gx, x1 + mx), x2 - mx)
        gy = min(max(gy, y1 + my), y2 - my)
        return int(gx), int(gy)
    # без bounds — небольшой гаусс-промах вокруг точки
    return int(random.gauss(x, 4)), int(random.gauss(y, 4))


def _bezier(x1, y1, x2, y2, n, bow=0.09):
    """Кубический Безье с боковой дугой + переменная скорость (ease-in-out -> медленно
    у концов, быстро в середине) + гаусс-джиттер по пути + джиттер концов."""
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy) or 1.0
    px, py = -dy / dist, dx / dist                 # перпендикуляр для дуги
    b = random.gauss(0, bow) * dist
    # контрольные точки кубического Безье (с боковым смещением)
    c1x, c1y = x1 + dx * 0.33 + px * b, y1 + dy * 0.33 + py * b
    c2x, c2y = x1 + dx * 0.66 + px * b * 0.6, y1 + dy * 0.66 + py * b * 0.6
    # джиттер концов ±15-20px
    x2j, y2j = x2 + random.gauss(0, 6), y2 + random.gauss(0, 6)
    pts = []
    for i in range(n):
        s = i / (n - 1)
        t = s * s * (3 - 2 * s)                     # ease-in-out: разгон/торможение
        mt = 1 - t
        bx = mt**3 * x1 + 3*mt**2*t*c1x + 3*mt*t**2*c2x + t**3 * x2j
        by = mt**3 * y1 + 3*mt**2*t*c1y + 3*mt*t**2*c2y + t**3 * y2j
        pts.append((int(bx + random.gauss(0, 1.6)), int(by + random.gauss(0, 1.6))))
    return pts


# --- 1. tap ---

def tap(serial, x, y, bounds=None, pre=True, post=True):
    px, py = _gauss_point(x, y, bounds)
    if pre:
        time.sleep(_u(0.3, 1.2))                    # пред-пауза «прицелился»
    seq = [f"input motionevent DOWN {px} {py}"]
    seq.append(f"sleep 0.0{random.randint(5, 9)}")  # удержание 50-90мс
    if random.random() < 0.6:                       # микро-дрейф 1-3px
        seq.append(f"input motionevent MOVE {px+random.randint(-3,3)} {py+random.randint(-3,3)}")
        seq.append(f"sleep 0.0{random.randint(1, 4)}")
    seq.append(f"input motionevent UP {px} {py}")
    _sh(serial, " ; ".join(seq))
    if post:
        time.sleep(_u(0.4, 0.9))                    # пост-дуэлл


# --- 2. double_tap ---

def double_tap(serial, x, y, bounds=None):
    tap(serial, x, y, bounds, pre=True, post=False)
    _sleep_ms(80, 180)                              # реальный межтаповый зазор
    # вторая точка чуть смещена — палец не попадает идеально
    tap(serial, x + random.randint(-8, 8), y + random.randint(-8, 8), pre=False, post=True)


# --- 3. long_press ---

def long_press(serial, x, y, duration_ms=None, bounds=None):
    duration_ms = duration_ms or random.randint(500, 900)
    px, py = _gauss_point(x, y, bounds)
    time.sleep(_u(0.3, 1.0))
    seq = [f"input motionevent DOWN {px} {py}"]
    held = 0
    step = 60
    while held < duration_ms:                       # тремор ±1-2px каждые ~50-60мс
        seq.append(f"sleep 0.0{random.randint(4, 6)}")
        seq.append(f"input motionevent MOVE {px+random.randint(-2,2)} {py+random.randint(-2,2)}")
        held += step
    seq.append(f"input motionevent UP {px} {py}")
    _sh(serial, " ; ".join(seq), timeout=max(20, duration_ms // 100 + 10))
    time.sleep(_u(0.4, 0.9))


# --- 4. swipe ---

def swipe(serial, x1, y1, x2, y2, n=None, overshoot=True):
    n = n or random.randint(12, 18)
    pts = _bezier(x1, y1, x2, y2, n)
    cmds = [f"input motionevent DOWN {pts[0][0]} {pts[0][1]}"]
    for (x, y) in pts[1:]:
        cmds.append(f"input motionevent MOVE {x} {y}")
        if random.random() < 0.2:                   # переменный темп
            cmds.append(f"sleep 0.0{random.randint(1, 4)}")
    if overshoot and random.random() < 0.25:        # лёгкий проскок + доводка
        ox, oy = pts[-1]
        cmds.append(f"input motionevent MOVE {ox+random.randint(-12,12)} {oy+random.randint(8,20)}")
        cmds.append("sleep 0.03")
        cmds.append(f"input motionevent MOVE {pts[-1][0]} {pts[-1][1]}")
    cmds.append(f"input motionevent UP {pts[-1][0]} {pts[-1][1]}")
    _sh(serial, " ; ".join(cmds))


# --- 5. fling (резкий отрыв на скорости -> ОС докручивает по инерции) ---

def fling(serial, x1, y1, x2, y2):
    n = random.randint(5, 8)                         # мало точек = быстро
    pts = _bezier(x1, y1, x2, y2, n, bow=0.04)
    cmds = [f"input motionevent DOWN {pts[0][0]} {pts[0][1]}"]
    for (x, y) in pts[1:]:
        cmds.append(f"input motionevent MOVE {x} {y}")
    # UP пока палец ещё «движется» (без торможения) -> инерция
    cmds.append(f"input motionevent UP {pts[-1][0]} {pts[-1][1]}")
    _sh(serial, " ; ".join(cmds))


# --- 6. scroll (свайп + дуэлл/наблюдение, изредка откат) ---

def scroll(serial, direction="up", cx=540, cy=1200, amount=0.5, h=2340, w=1080):
    dy = int(h * 0.32 * amount)
    if direction == "up":
        swipe(serial, cx, cy + dy // 2, cx, cy - dy)
    elif direction == "down":
        swipe(serial, cx, cy - dy // 2, cx, cy + dy)
    elif direction == "left":
        dx = int(w * 0.32 * amount); swipe(serial, cx + dx // 2, cy, cx - dx, cy)
    else:
        dx = int(w * 0.32 * amount); swipe(serial, cx - dx // 2, cy, cx + dx, cy)
    if random.random() < 0.12:                       # изредка короткий откат «перечитал»
        swipe(serial, cx, cy - dy // 4, cx, cy + dy // 4)
    time.sleep(_u(0.6, 2.2) if random.random() < 0.85 else _u(4, 12))  # дуэлл бимодально


# --- 7. drag (взять и перенести) ---

def drag(serial, x1, y1, x2, y2):
    time.sleep(_u(0.3, 0.8))
    pts = _bezier(x1, y1, x2, y2, random.randint(16, 24))
    cmds = [f"input motionevent DOWN {pts[0][0]} {pts[0][1]}"]
    cmds.append(f"sleep 0.{random.randint(3, 5)}")   # захват long-press 300-500мс
    for (x, y) in pts[1:]:
        cmds.append(f"input motionevent MOVE {x} {y}")
        cmds.append(f"sleep 0.0{random.randint(2, 5)}")  # медленно, осознанно
    cmds.append("sleep 0.2")                         # пауза перед сбросом
    cmds.append(f"input motionevent UP {pts[-1][0]} {pts[-1][1]}")
    _sh(serial, " ; ".join(cmds), timeout=30)
    time.sleep(_u(0.4, 0.9))


# --- 8/9. pinch / rotate — мультитач, без рута/minitouch недоступно ---

def pinch(serial, *a, **k):
    raise NotImplementedError("pinch требует мультитач (root/minitouch); non-root input не умеет")


def rotate(serial, *a, **k):
    raise NotImplementedError("rotate требует мультитач (root/minitouch); non-root input не умеет")


# --- 10. type ---

_LAT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 @._-!#$%&*")


def _is_ascii_typable(text):
    return all(c in _LAT for c in text)


def type(serial, text, typo_chance=0.0, use_adbkb_for_unicode=True):
    """Types characters with random delays, no typos by default.
    Cyrillic/unicode -> ADBKeyboard (am broadcast ADB_INPUT_TEXT), Latin -> input text."""
    if not _is_ascii_typable(text) and use_adbkb_for_unicode:
        import shlex
        msg = shlex.quote(text)   # каноничное экранирование ($ ` \ ; и апострофы внутри юникод-имён/био)
        _sh(serial, f"am broadcast -a ADB_INPUT_TEXT --es msg {msg}")  # нужен ADBKeyboard IME
        time.sleep(_u(0.3, 0.8))
        return
    for i, ch in enumerate(text):
        if random.random() < 0.04:                   # «думающая» пауза
            time.sleep(_u(0.5, 1.5))
        if ch.isalnum() and random.random() < typo_chance:   # опечатка + backspace
            wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
            _sh(serial, f"input text '{wrong}'"); _sleep_ms(150, 400)
            _sh(serial, "input keyevent 67"); _sleep_ms(100, 250)
        if ch == " ":
            _sh(serial, "input keyevent 62")
        elif ch == "'":
            _sh(serial, "input text \"'\"")
        else:
            _sh(serial, f"input text '{ch}'")
        _sleep_ms(50, 220)                           # межклавишно, не константа


# --- 11. key ---

def key(serial, keycode):
    """Системная клавиша с пред/пост-задержкой (не мгновенно)."""
    time.sleep(_u(0.2, 0.8))
    _sh(serial, f"input keyevent {keycode}")
    time.sleep(_u(0.2, 0.6))


# --- 12. wait (наблюдение, бимодально) ---

def wait(seconds=None):
    if seconds is not None:
        time.sleep(seconds); return
    r = random.random()
    if r < 0.60:
        time.sleep(_u(1, 3))                         # быстрый взгляд
    elif r < 0.96:
        time.sleep(_u(3, 8))                         # полный просмотр
    else:
        time.sleep(_u(12, 30))                       # «отвлёкся»


# флот: рассинхрон старта между телефонами
def desync():
    time.sleep(_u(0, 3.5))
