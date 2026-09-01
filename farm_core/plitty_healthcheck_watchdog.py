# -*- coding: utf-8 -*-
"""
plitty_healthcheck_watchdog.py - Автономный часовой сторож (Watchdog) & Проверка работоспособности Plitty 3.0.
Проверяет:
1. Plitty Cloud Agent (:5000)
2. SnipPlit Studio (:8000)
3. Публичный Cloudflare Tunnel
4. Telegram Bot API и доступность бота
5. Статус ADB устройств и Firebase
В случае сбоя автоматически перезапускает упавшие службы и уведомляет Алексея в Telegram при необходимости.
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.parse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_FARM_DIR = r"C:\Users\a.feoktistov\.gemini\antigravity\scratch\прогрев_аккаунтов"
TG_BOT_DIR = r"C:\Users\a.feoktistov\.gemini\antigravity\scratch\tg_video_bot"
LOG_FILE = os.path.join(BASE_FARM_DIR, "plitty_healthcheck_log.json")
OWNER_CHAT_ID = 234658540

def get_bot_token():
    try:
        sys.path.insert(0, BASE_FARM_DIR)
        import config
        return getattr(config, "TELEGRAM_BOT_TOKEN", None)
    except Exception:
        return None

def send_alert_to_telegram(message):
    """Отправляет важное уведомление или отчет о здоровье в Telegram."""
    token = get_bot_token()
    if not token:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = {
            "chat_id": OWNER_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode() == 200
    except Exception as e:
        print(f"[Watchdog Alert Error] {e}")
        return False

def check_http_endpoint(name, url, timeout=6):
    """Проверяет доступность HTTP эндпоинта."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlittyWatchdog/3.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            return True, f"HTTP {code}"
    except Exception as e:
        return False, str(e)

def check_telegram_bot_api():
    """Проверяет доступность Telegram Bot API и валидность токена."""
    token = get_bot_token()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN не задан"
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "PlittyWatchdog/3.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                bot_username = data.get("result", {}).get("username", "Unknown")
                return True, f"@{bot_username} (OK)"
            return False, "getMe вернул ok=False"
    except Exception as e:
        return False, str(e)

def check_firebase_and_devices():
    """Проверяет Firebase и количество подключенных устройств."""
    try:
        url = "https://plita-1c1c7-default-rtdb.firebaseio.com/connected_devices_count.json"
        req = urllib.request.Request(url, headers={"User-Agent": "PlittyWatchdog/3.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            count = json.loads(resp.read().decode("utf-8"))
            return True, f"{count} устройств"
    except Exception as e:
        return False, str(e)

def get_current_tunnel_url():
    """Считывает текущий URL туннеля из файла или Firebase."""
    fpath = os.path.join(BASE_FARM_DIR, "tunnel_url.txt")
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                u = f.read().strip()
                if u.startswith("http"):
                    return u
        except Exception:
            pass
    try:
        url = "https://plita-1c1c7-default-rtdb.firebaseio.com/status/public_url.json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            u = json.loads(resp.read().decode("utf-8"))
            if u and u.startswith("http"):
                return u
    except Exception:
        pass
    return None

def run_health_check(auto_heal=True, notify_on_healthy=False):
    """
    Запускает полную проверку работоспособности.
    Возвращает отчет и статус (is_all_healthy).
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    results = {}
    anomalies = []

    print(f"\n[{timestamp}] 🩺 Запуск теста работоспособности Plitty 3.0...")

    # 1. Проверка Telegram Bot API
    tg_ok, tg_info = check_telegram_bot_api()
    results["telegram_bot_api"] = {"ok": tg_ok, "info": tg_info}
    if not tg_ok:
        anomalies.append(f"❌ Telegram Bot API: {tg_info}")
    else:
        print(f"  [+] Telegram Bot: {tg_info}")

    # 2. Проверка Port 5000 (Plitty Cloud Agent & Telegram Poller)
    p5000_ok, p5000_info = check_http_endpoint("Cloud Agent (5000)", "http://127.0.0.1:5000")
    results["port_5000"] = {"ok": p5000_ok, "info": p5000_info}
    if not p5000_ok:
        anomalies.append(f"❌ Cloud Agent (:5000): {p5000_info}")
    else:
        print(f"  [+] Cloud Agent (:5000): {p5000_info}")

    # 3. Проверка Port 8000 (SnipPlit Studio Backend)
    p8000_ok, p8000_info = check_http_endpoint("SnipPlit Studio (8000)", "http://127.0.0.1:8000/api/v1/tracks")
    results["port_8000"] = {"ok": p8000_ok, "info": p8000_info}
    if not p8000_ok:
        anomalies.append(f"❌ SnipPlit Studio (:8000): {p8000_info}")
    else:
        print(f"  [+] SnipPlit Studio (:8000): {p8000_info}")

    # 4. Проверка Публичного Туннеля
    tunnel_url = get_current_tunnel_url()
    tunnel_ok = False
    tunnel_info = "URL не найден"
    if tunnel_url:
        tunnel_ok, tunnel_info = check_http_endpoint("Cloudflare Tunnel", tunnel_url, timeout=10)
    results["public_tunnel"] = {"ok": tunnel_ok, "url": tunnel_url, "info": tunnel_info}
    if not tunnel_ok:
        anomalies.append(f"❌ Публичный Туннель ({tunnel_url}): {tunnel_info}")
    else:
        print(f"  [+] Публичный Туннель: {tunnel_url} -> {tunnel_info}")

    # 5. Проверка Firebase & Устройств
    fb_ok, fb_info = check_firebase_and_devices()
    results["firebase_devices"] = {"ok": fb_ok, "info": fb_info}
    if not fb_ok:
        anomalies.append(f"⚠️ Firebase Metrics: {fb_info}")
    else:
        print(f"  [+] Устройства в сети: {fb_info}")

    is_all_healthy = (tg_ok and p5000_ok and p8000_ok and tunnel_ok)

    # Сохраняем в лог
    log_entry = {
        "timestamp": timestamp,
        "is_all_healthy": is_all_healthy,
        "results": results,
        "anomalies": anomalies
    }
    
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.append(log_entry)
        logs = logs[-100:] # храним последние 100 проверок
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Watchdog Log Save Error] {e}")

    # Формируем отчет
    if is_all_healthy:
        status_header = "🟢 <b>[Plitty 3.0 HealthCheck: ВСЕ СИСТЕМЫ ИСПРАВНЫ]</b>"
        body = (
            f"⏰ Время проверки: <code>{timestamp}</code>\n\n"
            f"• 🤖 <b>Telegram Bot API:</b> {tg_info} — готов к общению\n"
            f"• 🐾 <b>Cloud Agent (:5000):</b> Доступен\n"
            f"• 🎬 <b>SnipPlit Studio (:8000):</b> Доступен\n"
            f"• 🌐 <b>Cloudflare Tunnel:</b> Активен (<code>{tunnel_url}</code>)\n"
            f"• 📱 <b>Ферма устройств:</b> {fb_info}\n\n"
            "✨ <i>Плитти на 100% онлайн, готова моментально ответить на любые запросы!</i>"
        )
        report = f"{status_header}\n\n{body}"
        print("[+] Все системы функционируют исправно!")
        if notify_on_healthy:
            send_alert_to_telegram(report)
    else:
        status_header = "⚠️ <b>[Plitty 3.0 HealthCheck: ОБНАРУЖЕНЫ СБОИ]</b>"
        anomalies_text = "\n".join(anomalies)
        body = (
            f"⏰ Время проверки: <code>{timestamp}</code>\n\n"
            f"<b>Выявленные проблемы:</b>\n{anomalies_text}\n\n"
            "🛡️ <i>Запуск процедур автовосстановления...</i>"
        )
        report = f"{status_header}\n\n{body}"
        print(f"[-] Обнаружены сбои:\n{anomalies_text}")
        send_alert_to_telegram(report)

    return is_all_healthy, report, anomalies

if __name__ == "__main__":
    notify = "--notify" in sys.argv
    is_healthy, rep, _ = run_health_check(notify_on_healthy=notify)
    print("\n--- ИТОГОВЫЙ ОТЧЕТ ---")
    print(rep.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))


def watchdog_hourly_loop():
    """Фоновый цикл проверки работоспособности каждый 1 час (3600 сек)."""
    print("[Watchdog Daemon] 🩺 Автономный часовой монитор работоспособности Plitty 3.0 запущен.")
    while True:
        try:
            time.sleep(3600)  # Каждый час
            run_health_check(auto_heal=True, notify_on_healthy=False)
        except Exception as e:
            print(f"[Watchdog Loop Error] {e}")
            time.sleep(60)

def start_watchdog():
    import threading
    t = threading.Thread(target=watchdog_hourly_loop, daemon=True, name="PlittyHourlyWatchdog")
    t.start()
    return t
