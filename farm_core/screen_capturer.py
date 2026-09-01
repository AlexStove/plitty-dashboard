# screen_capturer.py
"""
Модуль захвата живых скриншотов с 30 смартфонов в реальном времени.
Делает быструю оптимизированную съемку активных девайсов через ADB,
сжимает их в небольшие JPEG миниатюры (180x320 px) и сохраняет в web_dashboard/screens/.
"""

import threading
import time
import os
import subprocess
from PIL import Image
import io

SCREENS_DIR = os.path.join(os.path.dirname(__file__), "web_dashboard", "screens")
os.makedirs(SCREENS_DIR, exist_ok=True)

capture_running = False
capture_thread = None

def capture_single_device(device_id, adb_port=5037):
    """
    Делает оптимизированный скриншот с устройства, сжимает и сохраняет в JPEG.
    """
    from adb_helper import ADB_PATH
    try:
        cmd = [ADB_PATH, "-P", str(adb_port), "-s", device_id, "exec-out", "screencap", "-p"]
        result = subprocess.run(cmd, capture_output=True, timeout=5)
        
        if result.returncode == 0 and result.stdout:
            # Сжимаем изображение через PIL
            img = Image.open(io.BytesIO(result.stdout))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((240, 420), Image.Resampling.LANCZOS)
            
            output_file = os.path.join(SCREENS_DIR, f"{device_id}.jpg")
            img.save(output_file, "JPEG", quality=55, optimize=True)
            return True
    except Exception as e:
        print(f"[Screen Capture Error] [{device_id}] {e}")
    return False

def screen_capture_loop():
    global capture_running
    print("[+] Фоновый модуль Live Screen Capture запущен...")
    
    from adb_helper import get_connected_devices
    
    while capture_running:
        try:
            connected = get_connected_devices()
            if not connected:
                time.sleep(5)
                continue
                
            # Захватываем скриншоты со всех подключенных девайсов параллельно (группами по 6)
            batch_size = 6
            for i in range(0, len(connected), batch_size):
                if not capture_running:
                    break
                batch = connected[i:i+batch_size]
                threads = []
                for dev_id in batch:
                    # Определяем порт
                    port = 5038 if "R5GYB" in dev_id or "R5CY" in dev_id else 5037
                    t = threading.Thread(target=capture_single_device, args=(dev_id, port), daemon=True)
                    t.start()
                    threads.append(t)
                    
                for t in threads:
                    t.join(timeout=3)
                    
                time.sleep(0.5)
                
            time.sleep(2.0)
        except Exception as e:
            print(f"[Capture Loop Error] {e}")
            time.sleep(4.0)

def start_screen_capturer():
    global capture_running, capture_thread
    if capture_running:
        return
        
    capture_running = True
    capture_thread = threading.Thread(target=screen_capture_loop, daemon=True, name="ScreenCapturer")
    capture_thread.start()

def stop_screen_capturer():
    global capture_running
    capture_running = False

if __name__ == "__main__":
    start_screen_capturer()
    time.sleep(10)
    stop_screen_capturer()
