# tunnel_watchdog.py
"""
Автоматический сторож за зашифрованным туннелем Plitty 3.0.
Удерживает постоянный адрес https://leshaplita.serveousercontent.com.
Если Serveo временно недоступен — автоматически запускает резервный туннель localhost.run
и обновляет актуальную ссылку в БД Firebase.
"""

import subprocess
import time
import os
import sys
import re
import urllib.request
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

FIREBASE_URL = "https://plita-1c1c7-default-rtdb.firebaseio.com/"
FIXED_SERVEO_URL = "https://leshaplita.serveousercontent.com"

current_process = None
active_provider = "serveo"
active_url = FIXED_SERVEO_URL

def fb_update_url(url_val):
    try:
        req = urllib.request.Request(
            f"{FIREBASE_URL}status/public_url.json",
            data=json.dumps(url_val).encode('utf-8'),
            method="PUT",
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def check_url_alive(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Watchdog"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.getcode() == 200
    except Exception:
        return False

def start_serveo():
    global current_process, active_provider, active_url
    active_provider = "serveo"
    active_url = FIXED_SERVEO_URL
    if current_process is not None:
        try:
            current_process.terminate()
        except Exception:
            pass
            
    print(f"[Watchdog] 🔄 Подключение к постоянной ссылке {FIXED_SERVEO_URL}...")
    current_process = subprocess.Popen(
        [
            "ssh",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=no",
            "-R", "leshaplita:80:127.0.0.1:5000",
            "serveo.net"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    fb_update_url(FIXED_SERVEO_URL)

def start_localhost_run():
    global current_process, active_provider, active_url
    active_provider = "localhost_run"
    if current_process is not None:
        try:
            current_process.terminate()
        except Exception:
            pass
            
    print("[Watchdog] 🔄 Запуск резервного туннеля localhost.run...")
    current_process = subprocess.Popen(
        [
            "ssh",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=no",
            "-R", "80:127.0.0.1:5000",
            "nokey@localhost.run"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Читаем вывод localhost.run для получения сгенерированного URL
    for line in iter(current_process.stdout.readline, ''):
        m = re.search(r"https://[a-zA-Z0-9-]+\.lhr\.life", line)
        if m:
            active_url = m.group(0)
            print(f"[Watchdog] 🟢 Резервная ссылка активна: {active_url}")
            fb_update_url(active_url)
            break

def watchdog_loop():
    print("[Watchdog] 🛡️ Сторож постоянной ссылки Plitty запущен.")
    start_serveo()
    time.sleep(6)
    
    fail_count = 0
    
    while True:
        try:
            if check_url_alive(active_url):
                fail_count = 0
                time.sleep(10)
            else:
                fail_count += 1
                print(f"[Watchdog] ⚠️ Ссылка {active_url} недоступна (проверка {fail_count}/2)...")
                
                if fail_count >= 2:
                    if active_provider == "serveo":
                        print("[Watchdog] Serveo временно недоступен. Переключаемся на резервный localhost.run...")
                        start_localhost_run()
                    else:
                        print("[Watchdog] Возвращаемся к постоянной ссылке Serveo...")
                        start_serveo()
                    fail_count = 0
                    time.sleep(6)
                else:
                    time.sleep(4)
        except Exception as e:
            print(f"[Watchdog Loop Error] {e}")
            time.sleep(5)

if __name__ == "__main__":
    watchdog_loop()
