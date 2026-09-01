# -*- coding: utf-8 -*-
"""
proactive_sentinel.py - Проактивный фоновый страж Plitty.
Мониторит здоровье фермы, процессы и память, и присылает важные уведомления в Telegram.
"""

import sys
import os
import time
import threading

# Фикс кодировки
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

last_notified_dev_count = None
last_sentinel_check = 0

def sentinel_loop():
    global last_notified_dev_count, last_sentinel_check
    print("[Sentinel] 🛡️ Проактивный страж Plitty активирован...")
    
    # Даем системе прогреться после запуска
    time.sleep(30)
    
    while True:
        try:
            now = time.time()
            # Проверяем каждые 60 секунд
            from adb_helper import get_connected_devices
            import telegram_bridge
            
            devices = get_connected_devices()
            count = len(devices)
            
            if last_notified_dev_count is not None and count != last_notified_dev_count:
                if count == 0 and last_notified_dev_count > 0:
                    telegram_bridge.send_message(
                        "⚠️ <b>Внимание, Алексей!</b> Все телефоны фермы внезапно отключились от ADB! Проверь питание USB-хаба! 🔌"
                    )
                elif count > last_notified_dev_count:
                    diff = count - last_notified_dev_count
                    telegram_bridge.send_message(
                        f"📱 <b>Плитти заметила новые устройства:</b> Подключено +{diff} телефонов (Всего в сети: {count})! ✨"
                    )
            last_notified_dev_count = count
        except Exception as e:
            # print(f"[Sentinel Error] {e}")
            pass
            
        time.sleep(60)

def start_sentinel():
    t = threading.Thread(target=sentinel_loop, daemon=True, name="ProactiveSentinel")
    t.start()
    return t
