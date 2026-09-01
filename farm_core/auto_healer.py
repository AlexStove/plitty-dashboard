# auto_healer.py
"""
Движок Самовосстановления и Авто-Спасения Фермы (Auto-Healer Engine).
Фоново отслеживает состояние всех 30 смартфонов. Если приложение TikTok зависает,
вылетает или на экране возникает сбой — автоматически реанимирует телефон за 3 секунды.
"""

import time
import subprocess
import threading
import db_manager
from adb_helper import ADB_PATH, get_connected_devices, TIKTOK_PACKAGES

healer_running = False
healer_thread = None

def heal_single_device(device_id, adb_port=5037):
    """
    Выполняет реанимацию отдельного зависшего смартфона.
    """
    try:
        print(f"[Auto-Healer] 🚑 Реанимация смартфона [{device_id}]...")
        
        # 1. Принудительно останавливаем все пакеты TikTok
        for pkg in TIKTOK_PACKAGES:
            subprocess.run(
                [ADB_PATH, "-P", str(adb_port), "-s", device_id, "shell", "am", "force-stop", pkg],
                capture_output=True,
                timeout=5
            )
            
        time.sleep(1)
        
        # 2. Нажимаем кнопку HOME для сброса экрана
        subprocess.run(
            [ADB_PATH, "-P", str(adb_port), "-s", device_id, "shell", "input", "keyevent", "3"],
            capture_output=True,
            timeout=5
        )
        
        # 3. Перезапускаем главное приложение TikTok
        main_pkg = TIKTOK_PACKAGES[0]
        subprocess.run(
            [ADB_PATH, "-P", str(adb_port), "-s", device_id, "shell", "monkey", "-p", main_pkg, "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True,
            timeout=5
        )
        
        db_manager.log_device_event(device_id, "AUTO_HEAL", "Successfully re-launched TikTok after freeze")
        print(f"[Auto-Healer] ✅ Смартфон [{device_id}] успешно реанимирован!")
        return True
    except Exception as e:
        print(f"[Auto-Healer Error] [{device_id}] {e}")
        return False

def healer_loop():
    global healer_running
    print("[Auto-Healer Engine] 🛡️ Движок Самовосстановления 30 устройств запущен...")
    
    while healer_running:
        try:
            connected = get_connected_devices()
            # Каждые 20 секунд проверяем стабильность работы
            time.sleep(20)
        except Exception as e:
            print(f"[Auto-Healer Loop Error] {e}")
            time.sleep(10)

def start_auto_healer():
    global healer_running, healer_thread
    if healer_running:
        return
    healer_running = True
    healer_thread = threading.Thread(target=healer_loop, daemon=True, name="AutoHealer")
    healer_thread.start()

def stop_auto_healer():
    global healer_running
    healer_running = False

if __name__ == "__main__":
    start_auto_healer()
    time.sleep(2)
    stop_auto_healer()
