#!/usr/bin/env python3
"""
a11y_transport.py — dual-mode транспорт телефон↔ПК.

Быстрый путь: A11Y Companion APK (companion_apk/) слушает 127.0.0.1:7070 на
устройстве, ПК ходит к нему через `adb forward`. Даёт мгновенное дерево a11y,
клики по resource_id (без промахов по координатам) и ввод текста через
ACTION_SET_TEXT (эмодзи/кириллица без глюков `input text`).

Медленный путь (fallback): классический ADB — `uiautomator dump` + `input tap/text`.

Правило дома: при ЛЮБОМ сбое APK молча падаем на ADB и логируем warning. Транспорт
никогда не должен ронять вызывающий код из-за APK. Сигнатуры _screen/_tap/_type
в scripts/* НЕ меняются — это отдельный слой поверх.

Флаг принудительного ADB: env APK_DISABLED=true  ИЛИ  устройства нет в
config/devices.json (или a11y_apk=false).
"""
import json
import logging
import os
import subprocess
import time
from pathlib import Path

try:
    import requests
    # класс обрыва связываем ЗДЕСЬ (при импорте): в тестах requests подменяют заглушкой без
    # .exceptions -> ссылка requests.exceptions.* в except упала бы AttributeError.
    from requests.exceptions import ConnectionError as _RequestsConnError
    _CONN_ERRORS = (_RequestsConnError, ConnectionError)   # requests-обрыв + встроенный RemoteDisconnected
except Exception:  # requests может отсутствовать — тогда только ADB
    requests = None
    _CONN_ERRORS = (ConnectionError,)

log = logging.getLogger("a11y_transport")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "devices.json"

DEVICE_PORT = 7070          # порт, который APK слушает ВНУТРИ устройства (фиксирован)
DEFAULT_HOST_PORT = 7070    # host-порт по умолчанию (переопределяется apk_port в конфиге)
PING_TTL = 60.0             # сек — кэш is_apk_available
HTTP_TIMEOUT = 4.0

# serial -> (monotonic_ts, bool)
_ping_cache: dict[str, tuple[float, bool]] = {}
# serial -> set(host_port) уже проброшенных (идемпотентность в рамках процесса)
_forwarded: dict[str, set] = {}
_config_cache: dict | None = None


# ==================== config ====================

def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        _config_cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _config_cache = {}
    return _config_cache


def _device_conf(serial: str) -> dict:
    conf = _load_config().get(serial)
    return conf if isinstance(conf, dict) else {}


def _apk_disabled_env() -> bool:
    return str(os.environ.get("APK_DISABLED", "")).strip().lower() in ("1", "true", "yes")


def _apk_enabled(serial: str) -> bool:
    """APK разрешён для устройства: не выключен глобально И включён в конфиге."""
    if _apk_disabled_env():
        return False
    conf = _device_conf(serial)
    return bool(conf.get("a11y_apk"))


def _host_port(serial: str) -> int:
    return int(_device_conf(serial).get("apk_port", DEFAULT_HOST_PORT))


def reset_cache():
    """Сброс кэшей (для тестов и после смены конфига)."""
    _ping_cache.clear()
    _forwarded.clear()
    global _config_cache
    _config_cache = None


# ==================== ADB primitives ====================

def _adb(serial: str, *args, timeout=15) -> str:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return out.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        log.debug("adb fail %s: %s", args, e)
        return ""


def _adb_shell(serial: str, command: str, timeout=15) -> str:
    return _adb(serial, "shell", command, timeout=timeout)


def _escape_input_text(text: str) -> str:
    """Экранирование для device-shell `input text` (как в scripts/publish_video._type):
    срезаем не-BMP (adb на эмодзи падает), пробел -> %s, спецсимволы sh -> \\x."""
    text = "".join(c for c in text if ord(c) < 0x2190 or c in "—–’")
    text = text.replace("’", "'")
    out = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        elif ch in "\\\"'`$&<>()|;*?~![]{}#":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _adb_dump_xml(serial: str) -> str:
    safe = "".join(c for c in serial if c.isalnum()) or "x"
    path = f"/sdcard/a11y_{safe}.xml"
    _adb_shell(serial, f"rm -f {path}")
    _adb_shell(serial, f"uiautomator dump {path} > /dev/null 2>&1")
    xml = _adb_shell(serial, f"cat {path}") or ""
    return xml if ("<hierarchy" in xml or xml.strip().startswith("<?xml")) else ""


def _adb_find_center(serial: str, node_id: str):
    """Резолвим resource_id в координаты центра через ADB-дамп (для tap по id без APK)."""
    import re
    import xml.etree.ElementTree as ET
    xml = _adb_dump_xml(serial)
    if not xml.strip().startswith("<"):
        return None
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError:
        return None
    for n in root.iter("node"):
        rid = n.attrib.get("resource-id", "")
        if rid == node_id or rid.endswith("/" + node_id):
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.attrib.get("bounds", ""))
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                return (x1 + x2) // 2, (y1 + y2) // 2
    return None


# ==================== APK / forward ====================

def ensure_forward(serial: str, port: int = None) -> bool:
    """`adb -s serial forward tcp:<host> tcp:7070`. Идемпотентно (проверяет --list)."""
    host_port = port if port is not None else _host_port(serial)
    done = _forwarded.setdefault(serial, set())
    if host_port in done:
        return True
    try:
        listing = _adb(serial, "forward", "--list") or ""
        spec = f"tcp:{host_port} tcp:{DEVICE_PORT}"
        if spec in listing:
            done.add(host_port)
            return True
        out = subprocess.run(
            ["adb", "-s", serial, "forward", f"tcp:{host_port}", f"tcp:{DEVICE_PORT}"],
            capture_output=True, timeout=15)
        if out.returncode == 0:
            done.add(host_port)
            return True
        log.warning("adb forward failed %s: %s", serial,
                    out.stderr.decode("utf-8", errors="replace").strip())
        return False
    except Exception as e:
        log.warning("adb forward error %s: %s", serial, e)
        return False


def _base_url(serial: str) -> str:
    return f"http://127.0.0.1:{_host_port(serial)}"


# NanoHTTPD рвёт keep-alive соединение -> requests из пула ловит RemoteDisconnected.
# Просим сервер закрывать соединение (Connection: close) + 1 ретрай на свежем сокете с
# задержкой 100мс ТОЛЬКО при обрыве keep-alive (RemoteDisconnected/ConnectionError) — мгновенный
# повтор бился о тот же протухший сокет; пауза даёт APK восстановиться.
# Замер (Чат 4): было 4 обрыва на 40 тапов (95%) -> с ретраем ~100%.
_HTTP_HEADERS = {"Connection": "close"}
_RETRY_DELAY = 0.1          # сек — пауза перед единственным ретраем после обрыва соединения


def _http_get(serial: str, path: str, timeout=HTTP_TIMEOUT):
    url = _base_url(serial) + path
    try:
        return requests.get(url, timeout=timeout, headers=_HTTP_HEADERS)
    except _CONN_ERRORS:                         # обрыв keep-alive (RemoteDisconnected) -> 1 ретрай
        log.warning("a11y retry serial=%s url=%s attempt=2", serial, url)   # видимость обрывов в проде
        time.sleep(_RETRY_DELAY)                 # пауза: свежий сокет, APK ожил
        try:
            return requests.get(url, timeout=timeout, headers=_HTTP_HEADERS)
        except _CONN_ERRORS as e:                # оба упали -> лог + проброс (caller делает ADB fallback)
            log.error("a11y fallback serial=%s url=%s reason=%s", serial, url, e)
            raise


def _http_post(serial: str, path: str, body: dict, timeout=HTTP_TIMEOUT):
    url = _base_url(serial) + path
    try:
        return requests.post(url, json=body, timeout=timeout, headers=_HTTP_HEADERS)
    except _CONN_ERRORS:
        log.warning("a11y retry serial=%s url=%s attempt=2", serial, url)
        time.sleep(_RETRY_DELAY)
        try:
            return requests.post(url, json=body, timeout=timeout, headers=_HTTP_HEADERS)
        except _CONN_ERRORS as e:
            log.error("a11y fallback serial=%s url=%s reason=%s", serial, url, e)
            raise


def is_apk_available(serial: str) -> bool:
    """adb forward встал + GET /ping вернул ok=true. Кэш 60с. Любая ошибка -> False."""
    if not _apk_enabled(serial) or requests is None:
        return False
    cached = _ping_cache.get(serial)
    if cached and (time.monotonic() - cached[0]) < PING_TTL:
        return cached[1]
    ok = False
    try:
        if ensure_forward(serial):
            r = _http_get(serial, "/ping")
            ok = bool(r.status_code == 200 and r.json().get("ok") is True)
    except Exception as e:
        log.warning("APK ping failed %s -> ADB fallback: %s", serial, e)
        ok = False
    _ping_cache[serial] = (time.monotonic(), ok)
    return ok


# ==================== public API ====================

def get_tree(serial: str) -> str:
    """JSON-строка дерева от APK (если доступен), иначе XML от `uiautomator dump`."""
    if is_apk_available(serial):
        try:
            r = _http_get(serial, "/tree")
            if r.status_code == 200:
                return r.text
            log.warning("APK /tree HTTP %s %s -> ADB fallback", serial, r.status_code)
        except Exception as e:
            log.warning("APK /tree failed %s -> ADB fallback: %s", serial, e)
    return _adb_dump_xml(serial)


def tree_nodes(serial: str):
    """Узлы от APK, нормализованные в формат phone_state.parse_nodes
    (text/desc/rid/rid_full/cls/cx/cy/en/clk/bounds/sel/chk/editable).
    None при недоступности/сбое APK -> вызывающий делает fallback на ADB."""
    if not is_apk_available(serial):
        return None
    try:
        r = _http_get(serial, "/tree")
        if r.status_code != 200:
            return None
        raw = r.json().get("nodes", [])
    except Exception as e:
        log.warning("APK tree_nodes failed %s -> None (ADB fallback): %s", serial, e)
        return None
    out = []
    for n in raw:
        b = n.get("bounds") or {}
        rid_full = n.get("resource_id") or ""
        cls_full = n.get("class_name") or ""
        try:
            cx = (b["left"] + b["right"]) // 2
            cy = (b["top"] + b["bottom"]) // 2
        except Exception:
            cx = cy = None
        out.append({
            "text": n.get("text") or "", "desc": n.get("content_desc") or "",
            "rid": rid_full.split("/")[-1] if rid_full else "", "rid_full": rid_full,
            "cls": cls_full.split(".")[-1] if cls_full else "",
            "bounds": f"[{b.get('left',0)},{b.get('top',0)}][{b.get('right',0)},{b.get('bottom',0)}]" if b else "",
            "cx": cx, "cy": cy,
            "en": bool(n.get("enabled", True)), "clk": bool(n.get("clickable", False)),
            "sel": False, "chk": False, "editable": bool(n.get("editable", False)),
        })
    return out


def tap(serial: str, x: int = None, y: int = None, node_id: str = None) -> bool:
    """Тап. APK+node_id -> ACTION_CLICK; APK+координаты -> жест; иначе ADB input tap."""
    node_id = node_id or None          # пустая строка = нет id (иначе int(None) на координатах)
    if is_apk_available(serial):
        try:
            body = {"node_id": node_id} if node_id else {"x": int(x), "y": int(y)}
            r = _http_post(serial, "/tap", body)
            if r.status_code == 200:
                return bool(r.json().get("ok"))
            log.warning("APK /tap HTTP %s %s -> ADB fallback", serial, r.status_code)
        except Exception as e:
            log.warning("APK /tap failed %s -> ADB fallback: %s", serial, e)
    # ADB fallback
    if x is None or y is None:
        if node_id:
            c = _adb_find_center(serial, node_id)
            if not c:
                return False
            x, y = c
        else:
            return False
    _adb_shell(serial, f"input tap {int(x)} {int(y)}")
    return True


def type_text(serial: str, text: str, node_id: str = None) -> bool:
    """Ввод текста. APK+node_id -> ACTION_SET_TEXT; иначе ADB input text (с экранированием)."""
    node_id = node_id or None
    if node_id and is_apk_available(serial):
        try:
            r = _http_post(serial, "/type", {"node_id": node_id, "text": text})
            if r.status_code == 200:
                return bool(r.json().get("ok"))
            log.warning("APK /type HTTP %s %s -> ADB fallback", serial, r.status_code)
        except Exception as e:
            log.warning("APK /type failed %s -> ADB fallback: %s", serial, e)
    # ADB fallback: при node_id тапнем поле, затем печатаем
    if node_id:
        c = _adb_find_center(serial, node_id)
        if c:
            _adb_shell(serial, f"input tap {c[0]} {c[1]}")
            time.sleep(0.3)
    _adb_shell(serial, f"input text {_escape_input_text(text)}")
    return True


def swipe(serial: str, x1, y1, x2, y2, duration_ms=300) -> bool:
    """Свайп. APK -> жест dispatchGesture; иначе ADB input swipe."""
    if is_apk_available(serial):
        try:
            r = _http_post(serial, "/swipe", {
                "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                "duration_ms": int(duration_ms)})
            if r.status_code == 200:
                return bool(r.json().get("ok"))
            log.warning("APK /swipe HTTP %s %s -> ADB fallback", serial, r.status_code)
        except Exception as e:
            log.warning("APK /swipe failed %s -> ADB fallback: %s", serial, e)
    _adb_shell(serial, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")
    return True
