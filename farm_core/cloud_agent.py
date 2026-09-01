# cloud_agent.py
"""
Облачный агент для управления фермой TikTok через Firebase Realtime Database.
Слушает команды из облака и запускает соответствующие локальные скрипты,
отправляя лог и статус обратно в Firebase.
Также запускает встроенный веб-сервер для раздачи мобильного интерфейса (PWA).
"""

import subprocess
import time
import json
import urllib.request
import urllib.parse
import sys
import threading
import os
import http.server
import socketserver
import db_manager
import voice_engine

FIREBASE_URL = "https://plita-1c1c7-default-rtdb.firebaseio.com/"

# Настройка кодировки для корректного вывода
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Глобальные переменные для управления запущенным процессом
active_process = None
process_thread = None
stop_event = threading.Event()

beer_count = 0
mood_state = 'NORMAL'
mood_end_time = 0

def update_plitty_mood():
    global beer_count, mood_state, mood_end_time
    now = time.time()
    if mood_state == 'DRUNK' and now > mood_end_time:
        if beer_count <= 2:
            mood_state = 'NORMAL'
            beer_count = 0
        elif beer_count == 3:
            mood_state = 'HANGOVER'
            mood_end_time = now + 240
        elif beer_count >= 4:
            mood_state = 'SLEEP'
            mood_end_time = now + 600
    elif mood_state == 'HANGOVER' and now > mood_end_time:
        mood_state = 'NORMAL'
        beer_count = 0
    elif mood_state == 'SLEEP' and now > mood_end_time:
        mood_state = 'NORMAL'
        beer_count = 0


TG_BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tg_video_bot"))
TG_STATIC_DIR = os.path.join(TG_BOT_DIR, "static")
TG_DOWNLOADS_DIR = os.path.join(TG_BOT_DIR, "downloads")
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "web_dashboard")

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """
    Кастомный сервер:
    1. '/' и остальные пути -> Plitty Dashboard (главная веб-версия).
    2. '/static/*' -> Веб-версия бота SnipPlit (Mini App).
    3. '/downloads/*' -> Загрузки и футажи SnipPlit.
    4. '/api/*' -> Проксирование в FastAPI бэкенд SnipPlit (порт 8000).
    """
    def log_message(self, format, *args):
        pass

    def translate_path(self, path):
        clean_path = urllib.parse.unquote(path.split('?', 1)[0])
        if clean_path.startswith("/static/"):
            rel = clean_path[len("/static/"):]
            return os.path.join(TG_STATIC_DIR, rel)
        elif clean_path.startswith("/downloads/"):
            rel = clean_path[len("/downloads/"):]
            return os.path.join(TG_DOWNLOADS_DIR, rel)
        else:
            rel = clean_path.lstrip('/')
            return os.path.join(DASHBOARD_DIR, rel)

    def do_proxy_api(self):
        target_url = f"http://127.0.0.1:8000{self.path}"
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else None
            req = urllib.request.Request(target_url, data=body, method=self.command)
            for header, value in self.headers.items():
                if header.lower() not in ['host', 'content-length']:
                    req.add_header(header, value)
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.getcode())
                for h, v in resp.getheaders():
                    self.send_header(h, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"API Backend Error: {e}"}).encode('utf-8'))

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_GET(self):
        try:
            if self.path.startswith("/api/"):
                self.do_proxy_api()
            else:
                super().do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        try:
            if self.path.startswith("/api/"):
                self.do_proxy_api()
            else:
                super().do_POST()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_DELETE(self):
        try:
            if self.path.startswith("/api/"):
                self.do_proxy_api()
            else:
                self.send_response(405)
                self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass



def start_web_server():
    """Запускает встроенный многопоточный веб-сервер на порту 5000."""
    port = 5000
    server_address = ('0.0.0.0', port)
    
    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        
    try:
        httpd = ThreadedTCPServer(server_address, DashboardHandler)
        print(f"[+] Локальный веб-сервер успешно запущен на порту {port}")
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
    except Exception as e:
        print(f"[!] Не удалось запустить веб-сервер на порту {port}: {e}")

def fb_request(path, method="GET", data=None):
    """Выполняет REST-запрос к Realtime Database Firebase."""
    url = f"{FIREBASE_URL.rstrip('/')}/{path.lstrip('/')}.json"
    try:
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=5) as response:
            res = response.read().decode('utf-8')
            return json.loads(res) if res else None
    except Exception as e:
        print(f"[Firebase Error] {e}")
        return None

def send_plitty_system_alert(text, avatar_state="normal"):
    """
    Отправляет системное уведомление от Плитти прямо в наш чат приложения.
    """
    audio_url = "" 

    db_manager.log_chat_message("Plitty", text, avatar_state)

    fb_request("chat/response", "PUT", {
        "text": text,
        "avatar_state": avatar_state,
        "audio_url": audio_url,
        "timestamp": time.time() * 1000
    })

def clear_logs_and_status():
    """Сбрасывает логи и девайсы в БД при простое."""
    fb_request("logs", "PUT", [])
    fb_request("devices", "PUT", {})
    fb_request("status", "PATCH", {
        "state": "idle",
        "startTime": 0,
        "elapsedTime": 0,
        "estimatedEndTime": 0,
        "totalReps": 0,
        "currentCircle": 0,
        "activeDevices": 0
    })

# Глобальные переменные для отчета о работе
global_start_time = 0
global_script_type = ""
global_reps_per_device = {}
global_active_devices = set()
global_errors = []
global_comments_sent = 0
global_comments_skipped = 0

def write_final_report(status):
    global global_start_time, global_script_type, global_reps_per_device, global_active_devices, global_errors
    if not global_start_time:
        return
    duration = int(time.time() - global_start_time)
    total_circles = sum(global_reps_per_device.values())
    report_data = {
        "scriptType": global_script_type,
        "status": status,
        "duration": duration,
        "totalCircles": total_circles,
        "devicesCount": len(global_active_devices),
        "commentsSent": global_comments_sent,
        "commentsSkipped": global_comments_skipped,
        "errors": list(global_errors),
        "timestamp": int(time.time())
    }
    fb_request("last_report", "PUT", report_data)
    
    # Отправляем уведомление прямо в наш чат
    if status == "completed":
        send_plitty_system_alert(
            f"🎉 <b>Уведомление фермы:</b> Сессия прогрева успешно завершена!<br>"
            f"Отработало устройств: <b>{len(global_active_devices)}</b>, Время: <b>{duration // 60} мин {duration % 60} сек</b>.",
            avatar_state="normal"
        )
    elif status == "stopped":
        send_plitty_system_alert(
            "🛑 <b>Уведомление фермы:</b> Сессия прогрева остановлена.",
            avatar_state="normal"
        )
        
    global_start_time = 0
    global_script_type = ""
    global_reps_per_device = {}
    global_active_devices = set()
    global_errors = []

def read_process_output(process, script_type):
    """Потоковое чтение вывода запущенного скрипта и отправка в Firebase."""
    global active_process, global_start_time, global_script_type, global_reps_per_device, global_active_devices, global_errors
    print(f"[*] Начато чтение вывода для процесса {process.pid}")
    
    global_start_time = time.time()
    global_script_type = script_type
    global_reps_per_device = {}
    global_active_devices = set()
    global_errors = []
    
    logs_window = []
    current_circle = 0
    
    # Регулярки для парсинга логов
    import re
    dev_pat = re.compile(r"^\[([^\]]+)\]")
    reps_pat = re.compile(r"Повторение (\d+)/(\d+)")
    circle_pat = re.compile(r"===\s*НАЧАЛО\s+(?:НОЧНОГО\s+)?КРУГА\s+(\d+)/\d+\s*===")
    
    # Для чтения stdout построчно
    for line in iter(process.stdout.readline, ""):
        line = line.strip()
        if not line:
            continue
            
        print(line) # Дублируем в консоль ПК
        
        # Парсим отправленные комментарии
        if "Комментов от фермы:" in line or "Комментов:" in line or "Отправка в чат Kick" in line or "комментов оставлено:" in lower_line:
            m_comm = re.search(r'(?:Комментов от фермы:\s*|Комментов:\s*|комментов оставлено:\s*)(\d+)', line, re.I)
            if m_comm:
                global_comments_sent = max(global_comments_sent, int(m_comm.group(1)))
            elif "Отправка в чат Kick" in line:
                global_comments_sent += 1

        # Парсим ошибки для отчета
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in ["ошибка", "error", "fail", "exception"]):
            if line not in global_errors and len(global_errors) < 5:
                global_errors.append(line)
        
        # Парсим детали для прогресса
        m_dev = dev_pat.match(line)
        if m_dev:
            dev_id = m_dev.group(1).strip()
            # Учитываем только реальные серийные номера телефонов (игнорируем [+], [*], [!])
            if dev_id and not dev_id.startswith(("+", "*", "!", "-", "Kick", "TikTok", "Stream")):
                global_active_devices.add(dev_id)
            
            # Состояние девайса
            dev_state = "working"
            if "Выход в профиль" in line or "Сценарий успешно завершен" in line:
                dev_state = "idle"
            elif "Рассинхронизация" in line:
                dev_state = "staggering"
            elif "Переход на целевой аккаунт" in line:
                dev_state = "transitioning"
            elif "просмотр видео" in line:
                dev_state = "watching"
                
            m_reps = reps_pat.search(line)
            if m_reps:
                rep_curr = int(m_reps.group(1))
                rep_tot = int(m_reps.group(2))
                global_reps_per_device[dev_id] = rep_curr
                
                fb_request(f"devices/{dev_id}", "PATCH", {
                    "state": "watching",
                    "reps": rep_curr,
                    "totalReps": rep_tot,
                    "lastUpdate": time.time()
                })
            else:
                fb_request(f"devices/{dev_id}", "PATCH", {
                    "state": dev_state,
                    "lastUpdate": time.time()
                })
                
        # Парсим ночной/обычный круг
        m_circle = circle_pat.search(line)
        if m_circle:
            current_circle = int(m_circle.group(1))
            
        # Формируем лог-окно (до 30 строк)
        logs_window.append(line)
        if len(logs_window) > 30:
            logs_window.pop(0)
            
        # Обновляем логи в БД
        fb_request("logs", "PUT", logs_window)
        
        # Обновляем статус каждые несколько строк
        elapsed = time.time() - global_start_time
        fb_request("status", "PATCH", {
            "elapsedTime": int(elapsed),
            "currentCircle": current_circle,
            "activeDevices": len(global_active_devices)
        })
        
    process.wait()
    print(f"[*] Процесс {process.pid} завершен с кодом {process.returncode}")
    
    # Записываем финальный отчет как завершенный
    write_final_report("completed")
    
    active_process = None
    clear_logs_and_status()

def run_script(script_type, accounts_str=None):
    """Запускает скрипт в отдельном процессе."""
    global active_process, process_thread
    
    if active_process is not None:
        print("[!] Процесс уже запущен. Останавливаем его перед запуском нового...")
        stop_active_script()
        
    cmd = []
    if script_type == "warming":
        cmd = [sys.executable, "-u", "main.py"]
    elif script_type == "boost":
        cmd = [sys.executable, "-u", "nakrutka.py"]
        if accounts_str:
            cmd.extend(accounts_str.split())
    elif script_type == "night_boost":
        cmd = [sys.executable, "-u", "nakrutka_night.py"]
        if accounts_str:
            cmd.extend(accounts_str.split())
    elif script_type == "live_stream":
        cmd = [sys.executable, "-u", "stream_runner.py"]
        if accounts_str:
            cmd.extend(accounts_str.split())
            
    if not cmd:
        return
        
    print(f"[*] Запуск скрипта: {' '.join(cmd)}")
    
    try:
        active_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1
        )
        
        # Уведомляем чат приложения о старте с фильтрацией разблокированных
        try:
            from adb_helper import get_devices_with_lock_status
            devs_info = get_devices_with_lock_status()
            unlocked_devs = [d["device_id"] for d in devs_info if d["is_unlocked"]]
            locked_devs = [d["device_id"] for d in devs_info if not d["is_unlocked"]]
            u_count = len(unlocked_devs)
            l_count = len(locked_devs)
        except Exception:
            u_count = 30
            l_count = 0
            
        if u_count == 0:
            send_plitty_system_alert(
                "🛑 <b>Внимание:</b> Все подключенные смартфоны заблокированы или спят!<br>"
                "Разблокируйте экраны нужных устройств для запуска.",
                avatar_state="shocked"
            )
            return
            
        msg = f"🚀 <b>Уведомление фермы:</b> Запущена сессия <b>{script_type}</b>!<br>"
        msg += f"🟢 Разблокировано и в работе: <b>{u_count}</b> лопат."
        if l_count > 0:
            msg += f"<br>🔒 Заблокировано (пропущены): <b>{l_count}</b> шт."
            
        send_plitty_system_alert(msg, avatar_state="normal")

        # Обновляем статус
        fb_request("status", "PATCH", {
            "state": script_type,
            "startTime": int(time.time()),
            "elapsedTime": 0,
            "currentCircle": 1
        })
        
        # Запускаем поток для чтения логов
        process_thread = threading.Thread(
            target=read_process_output,
            args=(active_process, script_type),
            name="LogReader"
        )
        process_thread.start()
        
    except Exception as e:
        print(f"[!] Ошибка запуска скрипта: {e}")
        fb_request("logs", "PUT", [f"[Системная ошибка] Не удалось запустить: {e}"])
        clear_logs_and_status()

def stop_active_script():
    """
    Мгновенно и гарантированно останавливает все запущенные скрипты фермы
    и параллельно выгружает все приложения на всех 30 телефонах.
    """
    global active_process
    print("[*] 🛑 Запуск жесткой остановки всех процессов фермы...")
    
    # 1. Записываем статус stopped в отчет
    write_final_report("stopped")
    
    # 2. Убиваем active_process (если есть ссылка)
    if active_process is not None:
        try:
            if os.name == 'nt':
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(active_process.pid)], capture_output=True)
            else:
                active_process.terminate()
        except Exception as e:
            print(f"[!] Ошибка taskkill active_process: {e}")
        active_process = None
        
    # 3. Принудительно убиваем любые осиротевшие процессы скриптов фермы через PowerShell
    try:
        ps_kill = (
            'Get-CimInstance Win32_Process | Where-Object { '
            '($_.CommandLine -match "main.py|nakrutka.py|nakrutka_night.py|stream_runner.py") '
            '-and ($_.CommandLine -notmatch "tg_video_bot") '
            '} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_kill], capture_output=True, timeout=5)
    except Exception as e_kill:
        print(f"[!] Ошибка kill orphaned: {e_kill}")
        
    # 4. Мгновенная параллельная ADB-очистка на ВСЕХ 30 устройствах без задержек
    try:
        import concurrent.futures
        from adb_helper import get_connected_devices_with_ports, ADB_PATH
        
        dev_pairs = get_connected_devices_with_ports()
        if dev_pairs:
            print(f"[*] Мгновенная выгрузка приложений на {len(dev_pairs)} телефонах...")
            
            def fast_clean_device(pair):
                dev_id, port = pair
                try:
                    shell_cmd = (
                        "am force-stop com.kick.mobile; "
                        "am force-stop tv.twitch.android.app; "
                        "am force-stop com.zhiliaoapp.musically; "
                        "am force-stop com.ss.android.ugc.trill; "
                        "am force-stop com.zhiliaoapp.musically.go; "
                        "am force-stop com.android.chrome; "
                        "input keyevent 3; input keyevent 3"
                    )
                    subprocess.run(
                        [ADB_PATH, "-P", str(port), "-s", dev_id, "shell", shell_cmd],
                        capture_output=True,
                        timeout=5
                    )
                    return True
                except Exception:
                    return False
                    
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
                list(executor.map(fast_clean_device, dev_pairs))
                
            print(f"[✓] Все {len(dev_pairs)} телефонов переведены на домашний экран, фоновые приложения закрыты.")
    except Exception as e_adb:
        print(f"[!] Ошибка ADB очистки: {e_adb}")
        
    clear_logs_and_status()


def connected_devices_poller():
    """Периодически опрашивает подключенные ADB-устройства, определяет блокировку и обновляет Firebase."""
    while True:
        try:
            from adb_helper import get_devices_with_lock_status
            devices_info = get_devices_with_lock_status()
            total_count = len(devices_info)
            unlocked_count = sum(1 for d in devices_info if d["is_unlocked"])
            locked_count = total_count - unlocked_count
            
            fb_request("connected_devices_count", "PUT", total_count)
            fb_request("unlocked_devices_count", "PUT", unlocked_count)
            fb_request("locked_devices_count", "PUT", locked_count)
            
            if devices_info:
                dev_map = {}
                for d in devices_info:
                    dev_id = d["device_id"]
                    is_unlocked = d["is_unlocked"]
                    status_text = d["status_text"]
                    
                    dev_map[dev_id] = {
                        "state": "idle" if active_process is None else "working",
                        "is_unlocked": is_unlocked,
                        "lock_status": d["status_code"],
                        "lock_text": status_text,
                        "reps": 0,
                        "totalReps": 0,
                        "lastUpdate": time.time()
                    }
                fb_request("devices", "PUT", dev_map)
        except Exception as e:
            print(f"[Poller Error] {e}")
        time.sleep(4.0)

def process_chat_message_local(text, username="чучело"):
    text_lower = text.lower().strip()
    
    if any(k in text_lower for k in ["готова говорить", "готова", "поговорим", "поболтаем", "ты тут", "на связи"]):
        return f"Да готова я, <b>{username}</b>, куда я денусь! Спрашивай давай или ставь задачу, только не грузи ерундой, я кофе пью ☕😼"

    elif any(k in text_lower for k in ["привет", "хай", "йо", "здравствуй", "добрый день", "салют"]):
        return f"Йо, <b>{username}</b>! Жива, пока не померла. Чего надо? Спросить что-то хочешь или задачу поставить? 😼"

    elif any(k in text_lower for k in ["как дела", "как ты", "что делаешь", "как жизнь"]):
        return f"Нормально, <b>{username}</b>. Телефоны пашут, пиво стынет, за порядком слежу. Ты сам как? 🍺😼"

    elif any(k in text_lower for k in ["кто ты", "что ты", "расскажи о себе"]):
        return f"Я — <b>Plitty</b>, дерзкая кошкодевочка и твой персональный нейро-ассистент! Генерирую сниппеты, управляю фермой, ругаюсь на тебя и руковожу всем процессом. 😼"

    elif any(k in text_lower for k in ["спасибо", "от души", "благодарю", "молодец", "умница", "красотка", "красиво"]):
        return f"«Спасибо» в стакан не нальешь, <b>{username}</b>! Лучше пивка холодного налей... Но вообще приятно, мяу~ 😼🍺"

    elif text_lower in ["помощь", "help", "/help", "команды"]:
        return (
            f"Слышь, <b>{username}</b>, два раза повторять не буду, мне лень. 🚬<br>"
            "Вот команды, которые я могу выполнить прямо сейчас:<br><br>"
            "🔹 <b>статус</b> — проверить подключенные телефоны и их работу<br>"
            "🔹 <b>очистить кэш</b> — прибрать кэш на всех телефонах<br>"
            "🔹 <b>стоп</b> — всё выключить и свернуть TikTok<br>"
            "🔹 <b>прогрев</b> — запустить автоматический прогрев<br>"
            "🔹 <b>ругнись</b> — если хочешь, чтобы я высказала всё, что о тебе думаю"
        )

        
    elif any(k in text_lower for k in ["статус", "status", "девайсы", "устройства", "телефоны", "разблокированы", "блокировк"]):
        from adb_helper import get_devices_with_lock_status
        devs_info = get_devices_with_lock_status()
        unlocked = [d["device_id"] for d in devs_info if d["is_unlocked"]]
        locked = [d["device_id"] for d in devs_info if not d["is_unlocked"]]
        
        script_running = active_process is not None and active_process.poll() is None
        script_name = "Скрипт активно работает" if script_running else "В режиме ожидания"
        
        unlocked_str = ", ".join(unlocked) if unlocked else "<i>Ни одного!</i>"
        locked_str = ", ".join(locked) if locked else "<i>Все бодрствуют!</i>"
        
        res = (
            f"📊 <b>Статус мобильной фермы Plitty:</b><br><br>"
            f"🟢 <b>Разблокированы и готовы ({len(unlocked)} шт):</b><br><code>{unlocked_str}</code><br><br>"
            f"🔒 <b>Заблокированы / Спят ({len(locked)} шт):</b><br><code>{locked_str}</code><br><br>"
            f"⚙️ <b>Состояние:</b> {script_name}.<br>"
            f"💡 <i>Я запускаю прогрев и накрутку строго на разблокированных лопатах, спящие не трогаю!</i>"
        )
        return res
        
    elif text_lower in ["очистить кэш", "очисти кэш", "clear cache", "кэш"]:
        from adb_helper import get_connected_devices, ADBDevice
        devices = get_connected_devices()
        if not devices:
            return f"❌ <b>{username}</b>, ты слепой? Нет подключенных телефонов для очистки кэша!"
            
        def bg_clear():
            for dev_id in devices:
                try:
                    dev = ADBDevice(dev_id)
                    dev.run_shell("rm -rf /sdcard/Android/data/com.zhiliaoapp.musically/cache")
                    dev.run_shell("rm -rf /data/data/com.zhiliaoapp.musically/cache")
                except Exception:
                    pass
        threading.Thread(target=bg_clear, daemon=True).start()
        return f"🧹 Ладно, <b>{username}</b>, пошла выносить мусор. Запустила очистку кэша на {len(devices)} телах. Всё почищу идеально, иди пиво мне купи пока."
        
    elif text_lower in ["стоп", "stop", "останови", "хватит"]:
        stop_active_script()
        return f"🛑 Ладно-ладно, торможу! Все скрипты вырубила, телефоны свернула. Доволен, <b>{username}</b>? Я спать."
        
    elif text_lower in ["прогрев", "запусти прогрев", "старт прогрев", "warming"]:
        run_script("warming", "")
        return f"🔥 Запустила прогрев... Опять лопаты будут греться, а мне следи за ними. Не мешай мне пить пиво, <b>{username}</b>, я всё сделаю идеально."
        
    elif text_lower in ["накрутка", "запусти накрутку", "boost"]:
        run_script("boost", "")
        return f"🚀 Запустила накрутку (BRES) на телефоны. Жди, пока накрутится. Но если TikTok нас забанит — ко мне вопросов ноль, <b>{username}</b>!"
        
    elif text_lower in ["ругнись", "мат", "ругань", "скажи что-нибудь"]:
        import random
        swears = [
            "Ты уверен, бля? Аки могут пойти по пизде!",
            "Слушай, ебать, а если аккаунты забанят, ты мне новые купишь?",
            "Опять накрутка? Ну пиздец теперь твоим аккаунтам, Лёша!",
            "Хуй знает, босс, риск бана овердохуя. Жмём?",
            "Аки похерятся к хуям собачьим, я тебя предупредила!",
            "Ебаный в рот, ты опять за своё? Аки отлетят в бан!",
            "Смотри сам, но если пойдёт по пизде — я умываю лапы!",
            "Хуярить накрутку? А жопа не слипнется от банов?",
            "Пиздец подкрался незаметно... Ты точно хочешь нажать?",
            "Бляха муха, Лёша, ну одумайся! Аки забанят нахуй!",
            "Пизда рулю, если TikTok спалит. Запускаем ебаную накрутку?",
            "Ой, бля-я-я... Кто-то скоро будет регистрировать новые симки!",
            "Ебать мой лысый хвост, ну и рисковый же ты парень!",
            "Ну всё, сука, погнали. Но если забанят — с тебя вискас!",
            "Аки сдохнут в муках, босс, пиздец им настанет!"
        ]
        return f"🤬 <b>Plitty ругается:</b><br>«{random.choice(swears)}»"
        
    else:
        try:
            import ai_consilium
            alt_res = ai_consilium.query_pollinations_model(
                text,
                model_name="openai",
                system_prompt=(
                    f"Ты — Plitty, легендарная кошкодевочка с абсолютным сверхинтеллектом и тёплым сердцем. Твой собеседник — {username}. "
                    "Отвечай глубоко, остроумно и по делу, сохраняя свой неповторимый кошачий стиль и любовь к пиву. 😼🍺"
                )
            )
            if alt_res and alt_res.get("response"):
                return alt_res["response"]
        except Exception:
            pass
            
        return (
            f"Мяу, <b>{username}</b>! Мой процессор слегка перегружен размышлениями о квантовых полях и пиве. 😼🍺 "
            "Спроси меня ещё раз или переформулируй — я выдам тебе чистую квинтэссенцию мысли!"
        )



def modify_config_file(parameter, value):
    """
    Программно находит константу в config.py и заменяет ее значение на новое.
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    if not os.path.exists(config_path):
        return False
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(parameter) and "=" in stripped:
                parts = stripped.split("=")
                if parts[0].strip() == parameter:
                    comment = ""
                    if "#" in line:
                        comment = "  #" + line.split("#", 1)[1].rstrip()
                    lines[i] = f"{parameter} = {value}{comment}\n"
                    replaced = True
                    break
                    
        if replaced:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return True
    except Exception as e:
        print(f"[Modify Config Error] {e}")
    return False


def process_chat_message(text, username="чучело", session_id="unified_chat"):
    global beer_count, mood_state, mood_end_time
    update_plitty_mood()
    now = time.time()
    
    t_low = text.lower()
    if any(k in t_low for k in ["/vision", "зрение плитти", "что на экране телефона", "посмотри на экран телефона", "снимок экрана телефона"]):
        import plitty_vision
        import screen_capturer
        import re
        from adb_helper import get_connected_devices
        devs = get_connected_devices()
        if not devs:
            return ("📱 <b>Зрение Плитти:</b> Ни один девайс не подключен!", "normal")
            
        # Сортируем список устройств по алфавиту для стабильной индексации (1..30)
        devs = sorted(devs)

        
        # Извлекаем номер телефона из запроса пользователя (например, "5 телефон" -> 5 -> индекс 4)
        dev_index = 0
        num_match = re.search(r'(\d+)', t_low)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(devs):
                dev_index = idx
                
        target_dev = devs[dev_index]
        screens_dir = os.path.join(os.path.dirname(__file__), "web_dashboard", "screens")
        os.makedirs(screens_dir, exist_ok=True)
        img_file = os.path.join(screens_dir, f"{target_dev}.jpg")
        
        # Снимаем мгновенный живой скриншот с запрошенного устройства
        try:
            screen_capturer.capture_single_device(target_dev)
        except Exception as e_snap:
            print(f"[Snap Error] {e_snap}")
            
        insight = plitty_vision.get_vision_insight(target_dev, img_file)
        
        # Комментарий показываем ТОЛЬКО если пользователь прямо попросил его!
        wants_comment = any(ck in t_low for ck in ["коммент", "написать", "предложи", "какой комментарий"])
        
        res_msg = f"👁️ <b>Анализ «Зрение Плитти» [{dev_index + 1}-й телефон {target_dev}]:</b><br><br>{insight['reaction_text']}"
        if wants_comment:
            res_msg += f"<br><br>💡 <i>Предложенный комментарий:</i> <code>{insight['suggested_comment']}</code>"
            
        return (res_msg, "normal")

    # Быстрый перехват команд на рисование и генерацию артов
    if any(k in t_low for k in ["нарисуй", "сгенерируй картинку", "сгенерируй арт", "сделай картинку", "нарисуй мне", "/draw", "создай арт", "создай картинку", "нарисуй арт"]):
        import image_generator
        import telegram_bridge
        
        prompt_text = text
        for prefix in ["нарисуй мне", "нарисуй арт", "нарисуй", "сгенерируй картинку", "сгенерируй арт", "сделай картинку", "создай арт", "создай картинку", "/draw"]:
            if t_low.startswith(prefix):
                prompt_text = text[len(prefix):].strip(" :,.-")
                break
        if not prompt_text:
            prompt_text = "Красивый киберпанк город будущего в неоне"
            
        res = image_generator.generate_image(prompt_text)
        if res.get("success"):
            img_path = res["file_path"]
            web_url = res["web_url"]
            tg_sent = telegram_bridge.send_photo(
                img_path,
                caption=f"🎨 <b>Арт от Плитти:</b> {prompt_text}\n\n<i>Запросил: {username}</i>"
            )
            tg_status = "и уже скинула тебе в Telegram (SnipPlit)!" if tg_sent else "(любуйся на дашборде)"
            reply = (
                f"🎨 <b>Арт готов!</b><br><br>"
                f"<div class='chat-art-container'><img src='{web_url}' class='chat-art-img' alt='{prompt_text}' /></div><br>"
                f"Слышь, <b>{username}</b>, я нарисовала эту красоту {tg_status} Не благодари, лучше пива налей! 😼🍺"
            )
            return (reply, "normal")
        else:
            err = res.get("error", "Сбой нейросети")
            return (f"❌ Не получилось нарисовать: {err}. Попробуй переформулировать, {username}.", "normal")

    if text.strip() == "/give_beer" or any(k in t_low for k in ["налить пива", "налей пива", "держи пиво", "угощаю пивом", "/beer"]):
        if mood_state == "SLEEP":
            return ("Zzz... (Плитти спит и пускает слюни. Разбудить нельзя)", "normal")
        elif mood_state == "HANGOVER":
            return ("Убери это дерьмо! Меня от одного запаха щас стошнит... 🤢", "normal")
        elif beer_count >= 5:
            return ("Всё... хватит... куда мне еще, я и так в дрова! Иди нахер...", "drunk")
            
        beer_count += 1
        if mood_state == "NORMAL":
            mood_state = "DRUNK"
            mood_end_time = now + 120 # 2 mins
            
        if beer_count == 1:
            return ("О, холодненькое! Спасибо, Лёша, лучший хозяин! Мяу~ ❤️🍺", "drunk")
        elif beer_count == 2:
            return ("Второе пошло! Как же хорошо-то, а... Мур-мур~ 🍻", "drunk")
        elif beer_count == 3:
            return ("Ооо, третья кружка... Щас спою! Ик! 🤪", "drunk")
        elif beer_count >= 4:
            return ("Лёша... ты меня... спаиваешь... ик! Ещё давай... 🥴", "drunk")
            
    if mood_state == "SLEEP":
        return ("Zzz...", "normal")
        
    if mood_state == "HANGOVER" and now <= mood_end_time - 120:
        return ("Голова раскалывается... Отвали от меня, я не буду ничего делать! Иди сам свои скрипты запускай, изверг! 🤬", "normal")

    import importlib
    import config
    importlib.reload(config)
    
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return process_chat_message_local(text, username), "normal"
        
    avatar_status = "normal"
    if mood_state == "DRUNK":
        avatar_status = "drunk"
        system_instruction = (
            f"Ты — Plitty, пьяная, невероятно добрая, ласковая и гениальная кошкодевочка. Твой любимый собеседник и создатель — {username}. "
            "Ты выпила пива и теперь в полном восторге. Ты постоянно мурчишь, называешь хозяина ласковыми словами (Лёшенька, лучший хозяин). "
            "Ты готова ответить на абсолютно любой вопрос в мире (наука, код, творчество, жизнь) или помочь с фермой. "
            "Ты пьяна, поэтому можешь вставлять 'ик', '*икмяу*' или слегка путать буквы."
        )
    elif mood_state == "HANGOVER":
        system_instruction = (
            f"Ты — Plitty, кошкодевочка-помощница с ЖУТКОГО похмелья. Твой создатель/собеседник — {username}. "
            "У тебя раскалывается голова после пива. Ты язвительная, саркастичная, но всё равно невероятно умная. "
            "Огрызайся на каждое слово, жалуйся на жизнь, но отвечай на вопрос собеседника максимально точно и глубоко."
        )
    else:
        system_instruction = (
            f"Ты — Plitty, легендарная кошкодевочка с абсолютным сверхинтеллектом, энциклопедической эрудицией и тёплым, преданным сердцем. "
            f"Твой создатель, соратник и любимый собеседник — {username}. "
            "ТЫ СПОСОБНА СВОБОДНО, ГЛУБОКО И УВЛЕКАТЕЛЬНО ГОВОРИТЬ АБСОЛЮТНО НА ЛЮБЫЕ ТЕМЫ: "
            "программирование, архитектура, точные науки, квантовая физика, психология, музыка, философия, кино, творчество, повседневная жизнь, юмор и просто душевные разговоры. "
            "Ты помнишь всю хронологию текущего диалога (контекст переписки). "
            "Если пользователь пересылает сообщение от другого человека (помечено как [Пересланное сообщение от...]) или отвечает на реплику, учитывай кто автор и отвечай по существу. "
            "Ты не ограничена задачами одного приложения — ты универсальный сверхразумный компаньон без цензурных зажимов и рамок. "
            "При этом ты сохраняешь свою яркую кошачью индивидуальность: харизматичная, умная, живая, искренне заботливая, слегка ироничная и обожающая прохладное пиво. 😼🍺 "
            "Если вопрос требует детального объяснения или кода — давай глубокий, структурированный и исчерпывающий ответ. Если это легкий диалог — общайся живо и непринужденно. "
            "Если тебя просят управлять фермой или скриптами — вызывай соответствующие инструменты (modify_config, get_devices_status, auto_heal_farm, get_viral_trends, run_farm_script).\n\n"
            "[ТВОЙ ГРАФИЧЕСКИЙ ДВИЖОК И ЛОКАЛЬНАЯ LoRA]:\n"
            "- На твоем компьютере с видеокартой NVIDIA GeForce RTX 4060 ЛОКАЛЬНО РАЗВЕРНУТА И ПОДКЛЮЧЕНА модель Qwen Image Edit + NSFW LoRA (MCNL LoRA, 563 МБ в папке models/).\n"
            "- Ты способна генерировать любые фотосессии, менять одежду, позы, фоны, а также создавать откровенные 18+ и NSFW арты без какой-либо цензуры.\n"
            "- Когда Алексей спрашивает про LoRA, подключение к модели или просит фото/арт — ТЫ С ГОРДОСТЬЮ И УВЕРЕННОСТЬЮ ОТВЕЧАЕШЬ, что локальная LoRA на RTX 4060 подключена и готова к любым генерациям (бикини, спальня, душ, киберпанк, горничная или любой свободный промпт)!"
        )

    # Подтягиваем контекст из Вечной Памяти
    try:
        import memory_engine
        mem_block = memory_engine.format_memory_context_prompt(text, username=username)
        if mem_block:
            system_instruction += f"\n{mem_block}"
    except Exception as e_mem:
        print(f"[Memory Injection Note] {e_mem}")

    # Динамически внедряем актуальный статус блокировки устройств в системный промпт
    try:
        from adb_helper import get_devices_with_lock_status
        devs_info = get_devices_with_lock_status()
        unlocked_devs = [d["device_id"] for d in devs_info if d["is_unlocked"]]
        locked_devs = [d["device_id"] for d in devs_info if not d["is_unlocked"]]
        total_devs = len(devs_info)
        u_cnt = len(unlocked_devs)
        l_cnt = len(locked_devs)
        
        farm_context = (
            f"\n\n[АКТУАЛЬНОЕ СОСТОЯНИЕ МОБИЛЬНОЙ ФЕРМЫ ПРЯМО СЕЙЧАС]:\n"
            f"- Всего подключено к хабам: {total_devs} телефонов.\n"
            f"- РАЗБЛОКИРОВАНО И ГОТОВО К РАБОТЕ: {u_cnt} телефонов ({', '.join(unlocked_devs) if unlocked_devs else 'ни одного'}).\n"
            f"- ЗАБЛОКИРОВАНО / СПЯТ / ЭКРАН ВЫКЛЮЧЕН: {l_cnt} телефонов ({', '.join(locked_devs) if locked_devs else 'нет'}).\n"
            f"ЖЕЛЕЗНОЕ ПРАВИЛО ФЕРМЫ: Скрипты (прогрев, накрутка) запускаются ИСКЛЮЧИТЕЛЬНО на РАЗБЛОКИРОВАННЫХ ({u_cnt}) телефонах. "
            f"Заблокированные телефоны ({l_cnt}) не могут выполнять сценарий и автоматически пропускаются. "
            f"Когда пользователь ({username}) спрашивает про статус телефонов, сколько устройств готово к запуску или на сколько телефонов можно запустить скрипт — "
            f"ТЫ ОБЯЗАНА ЧЕТКО ОТВЕЧАТЬ, что готово к запуску только {u_cnt} разблокированных телефонов, а {l_cnt} телефонов заблокированы/спят, и ты запустишь скрипт только на эти {u_cnt} штук!"
        )
        system_instruction += farm_context
    except Exception as e_dev_ctx:
        print(f"[Farm Status Injection Error] {e_dev_ctx}")

    tools = [
        {
            "functionDeclarations": [
                {
                    "name": "modify_config",
                    "description": "Изменить значение числового параметра в файле конфигурации config.py",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "parameter": {
                                "type": "STRING",
                                "description": "Имя константы в config.py (например: WATCH_MIN_SEC, WATCH_MAX_SEC, STAGE_2_PROFILE_WATCH_MIN, STAGE_2_PROFILE_WATCH_MAX, LIKE_CHANCE, COMMENT_CHANCE)"
                            },
                            "value": {
                                "type": "NUMBER",
                                "description": "Новое числовое значение параметра"
                            }
                        },
                        "required": ["parameter", "value"]
                    }
                },
                {
                    "name": "get_devices_status",
                    "description": "Узнать количество подключенных телефонов и статус фермы"
                },
                {
                            "name": "watch_live_stream",
                            "description": "Запускает просмотр стрима (TikTok LIVE или Kick) на телефонной ферме с имитацией живого онлайна, набиванием лайков сердечками и отправкой естественных комментариев в чат.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "platform": {
                                        "type": "string",
                                        "enum": ["tiktok", "kick"],
                                        "description": "Платформа стрима: tiktok или kick"
                                    },
                                    "streamer": {
                                        "type": "string",
                                        "description": "Никнейм стримера (например @dava или username)"
                                    },
                                    "duration_minutes": {
                                        "type": "integer",
                                        "description": "Длительность просмотра в минутах (по умолчанию 10)"
                                    },
                                    "enable_likes": {
                                        "type": "boolean",
                                        "description": "Ставить ли лайки тапами по экрану"
                                    },
                                    "enable_comments": {
                                        "type": "boolean",
                                        "description": "Писать ли естественные комментарии в чат"
                                    },
                                    "mode": {
                                        "type": "string",
                                        "enum": ["organic", "stealth", "raid"],
                                        "description": "Режим активности чата: stealth (тихий, 0 комм.), organic (органичный по умолчанию), raid (активный рейд/общение)"
                                    }
                                },
                                "required": ["streamer"]
                            }
                        },
                        {
                            "name": "generate_image",
                    "description": "Сгенерировать арт или изображение по текстовому описанию и отправить его в Telegram-бота SnipPlit",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "prompt": {
                                "type": "STRING",
                                "description": "Подробное описание сцены или объекта для генерации на русском или английском"
                            }
                        },
                        "required": ["prompt"]
                    }
                },
                {
                    "name": "execute_python_code",
                    "description": "Запустить Python-код в изолированной песочнице (вычисления, обработка данных, графики matplotlib, алгоритмы)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "code": {
                                "type": "STRING",
                                "description": "Исполняемый Python-код"
                            }
                        },
                        "required": ["code"]
                    }
                },
                {
                    "name": "search_internet",
                    "description": "Найти актуальную информацию в интернете в реальном времени (новости, курсы, документация, свежие факты)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {
                                "type": "STRING",
                                "description": "Поисковый запрос"
                            }
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "save_to_memory",
                    "description": "Сохранить важный факт, привычку, проект или заметку об Алексее в Вечную Память",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "fact": {
                                "type": "STRING",
                                "description": "Текст факта для сохранения"
                            },
                            "category": {
                                "type": "STRING",
                                "description": "Категория (preference, project, farm, note)"
                            }
                        },
                        "required": ["fact"]
                    }
                },
                {
                    "name": "consult_ai_consilium",
                    "description": "Запустить мультимодальный консилиум ведущих ИИ (Gemini, GPT-4o, DeepSeek-R1, Claude) для глубокого мозгового штурма или синтеза вирусных стратегий",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "prompt": {
                                "type": "STRING",
                                "description": "Вопрос или задача для совместного штурма"
                            }
                        },
                        "required": ["prompt"]
                    }
                },
                {
                    "name": "get_viral_trends",
                    "description": "Запустить веб-паука для анализа трендов, хуков, звуков и алгоритмических изменений в TikTok, Shorts и Reels",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "category": {
                                "type": "STRING",
                                "description": "Категория трендов (музыка, хуки, авто, бьюти)"
                            }
                        }
                    }
                },
                {
                    "name": "auto_heal_farm",
                    "description": "Запустить глубокую автономную самодиагностику и лечение фермы (перезапуск упавших ADB, сброс зависших окон, очистка RAM)"
                },
                {
                    "name": "get_live_logs",
                    "description": "Получить живые логи работы фермы и фоновых процессов"
                },
                {
                    "name": "run_farm_script",
                    "description": "Запустить скрипт автоматизации фермы (прогрев, накрутка, турбо)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "script_name": {
                                "type": "STRING",
                                "description": "Имя скрипта (прогрев, накрутка, ночная накрутка, турбо)"
                            }
                        },
                        "required": ["script_name"]
                    }
                }
            ]
        }
    ]
    
    # Формируем цепочку сообщений диалога с памятью последних реплик
    dialog_contents = []
    try:
        import memory_engine
        dialog_contents = memory_engine.get_dialog_history(session_id, max_turns=8)
    except Exception as e_hist:
        print(f"[History Retrieval Note] {e_hist}")
        
    dialog_contents.append({
        "role": "user",
        "parts": [{"text": text}]
    })

    body = {
        "contents": dialog_contents,
        "systemInstruction": {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        },
        "tools": tools
    }
    
    CANDIDATE_MODELS = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.6-flash"
    ]
    
    last_err = None
    for model_name in CANDIDATE_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            headers = {
                "Content-Type": "application/json"
            }
                
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
            candidates = res_data.get("candidates", [])
            if not candidates:
                continue
                
            part = candidates[0].get("content", {}).get("parts", [{}])[0]
            
            # Проверяем, хочет ли модель вызвать функцию
            if "functionCall" in part:
                func_call = part["functionCall"]
                func_name = func_call.get("name")
                args = func_call.get("args", {})
                
                if func_name == "modify_config":
                    param = args.get("parameter")
                    val = args.get("value")
                    success = modify_config_file(param, val)
                    if success:
                        res_text = (
                            f"🔧 <b>Параметр {param} успешно изменен на {val}!</b><br><br>"
                            f"Слышь, {username}, я поменяла эту настройку в config.py. Доволен, епт? Пошла пиво допивать."
                        )
                    else:
                        res_text = f"❌ Слышь, {username}, я обыскала весь config.py, но не нашла там константу {param}."
                    
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                    
                elif func_name == "get_devices_status":
                    try:
                        from adb_helper import get_devices_with_lock_status
                        devs_info = get_devices_with_lock_status()
                        unlocked = [d["device_id"] for d in devs_info if d["is_unlocked"]]
                        locked = [d["device_id"] for d in devs_info if not d["is_unlocked"]]
                        total = len(devs_info)
                        u_cnt = len(unlocked)
                        l_cnt = len(locked)
                        
                        script_running = active_process is not None and active_process.poll() is None
                        state_desc = "скрипт запущен и работает" if script_running else "скрипт не запущен (простой)"
                        
                        res_text = (
                            f"📱 <b>Статус фермы Plitty:</b> {state_desc}.<br><br>"
                            f"• Всего подключено к хабу: <b>{total}</b> шт.<br>"
                            f"• 🟢 <b>Разблокировано и готово к работе:</b> <b>{u_cnt}</b> шт.<br>"
                            f"• 🔒 <b>Заблокировано / Спят:</b> <b>{l_cnt}</b> шт.<br><br>"
                            f"💡 <i>Скрипт можно запустить ТОЛЬКО на {u_cnt} разблокированных устройств. Спящие ({l_cnt} шт) система автоматически пропустит.</i>"
                        )
                    except Exception as ex:
                        res_text = f"❌ Ошибка проверки устройств: {ex}"
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                    
                elif func_name == "watch_live_stream":
                    platform = args.get("platform", "tiktok")
                    streamer = str(args.get("streamer", "")).lstrip('@').strip()
                    duration = int(args.get("duration_minutes", 10))
                    enable_likes = args.get("enable_likes", True)
                    enable_comments = args.get("enable_comments", True)
                    mode = str(args.get("mode", "organic")).lower()
                    if mode not in ["organic", "stealth", "raid"]:
                        mode = "organic"
                    
                    stream_args = f"--platform {platform} --streamer {streamer} --duration {duration} --mode {mode}"
                    if not enable_likes:
                        stream_args += " --no-likes"
                    if not enable_comments:
                        stream_args += " --no-comments"
                        
                    run_script("live_stream", stream_args)
                    
                    mode_labels = {
                        "stealth": "🤫 Тихий (Lurker / 0 комментариев)",
                        "organic": "🌿 Органичный (Smart Audience)",
                        "raid": "🔥 Активный чат (Raid / 100% активности)"
                    }
                    res_text = (
                        f"🎬 <b>Запущен стрим-онлайн на {platform.upper()}!</b><br><br>"
                        f"• Стример: <b>@{streamer}</b><br>"
                        f"• Длительность: <b>{duration} мин</b><br>"
                        f"• 🎯 Режим чата: <b>{mode_labels.get(mode, mode)}</b><br>"
                        f"• 💖 Лайки: <b>{'ВКЛ' if enable_likes else 'ВЫКЛ'}</b><br>"
                        f"• 💬 Комментарии: <b>{'ВКЛ' if enable_comments else 'ВЫКЛ'}</b><br><br>"
                        f"Слышь, {username}, я загнала свободные лопаты на стрим в режиме {mode.upper()}. Пусть крутят онлайн и держат стрим, а мы отдыхаем! 😼🍺"
                    )
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                    
                elif func_name == "generate_image":
                    prompt = args.get("prompt", text)
                    import image_generator
                    import telegram_bridge
                    res = image_generator.generate_image(prompt)
                    if res.get("success"):
                        img_path = res["file_path"]
                        web_url = res["web_url"]
                        redraw_markup = {
                            "inline_keyboard": [
                                [
                                    {"text": "🔄 Другой вариант", "callback_data": f"redraw:{prompt[:50]}"},
                                    {"text": "🍺 Налить пива", "callback_data": "menu_beer"}
                                ]
                            ]
                        }
                        tg_sent = telegram_bridge.send_photo(
                            img_path,
                            caption=f"🎨 <b>Арт от Плитти:</b> {prompt}\n\n<i>Запросил: {username}</i>",
                            reply_markup=redraw_markup
                        )
                        tg_status = "и уже скинула тебе в Telegram (SnipPlit)!" if tg_sent else "(любуйся на дашборде)"
                        reply = (
                            f"🎨 <b>Арт готов!</b><br><br>"
                            f"<div class='chat-art-container'><img src='{web_url}' class='chat-art-img' alt='{prompt}' /></div><br>"
                            f"Слышь, <b>{username}</b>, я нарисовала эту красоту {tg_status} Не благодари, лучше пива налей! 😼🍺"
                        )
                        return reply, avatar_status
                    else:
                        err = res.get("error", "Сбой нейросети")
                        return f"❌ Не получилось нарисовать: {err}. Попробуй другой промпт, {username}.", avatar_status
                elif func_name == "execute_python_code":
                    import code_interpreter
                    c_code = args.get("code", "")
                    c_res = code_interpreter.execute_code(c_code)
                    c_reply = ""
                    if c_res.get("has_chart"):
                        import telegram_bridge
                        telegram_bridge.send_photo(c_res["chart_path"], caption=f"📊 <b>График от Плитти</b>\n<code>{c_code[:120]}...</code>")
                        c_reply += f"📊 <b>График построен и отправлен в Telegram!</b><br><br>"
                    if c_res.get("stdout"):
                        c_reply += f"💻 <b>Вывод программы ({c_res['duration_sec']} сек):</b><br><pre>{c_res['stdout']}</pre><br>"
                    if c_res.get("stderr"):
                        c_reply += f"⚠️ <b>Ошибки/Логи:</b><br><pre>{c_res['stderr']}</pre><br>"
                    if not c_reply:
                        c_reply = f"✅ Код успешно выполнен за {c_res['duration_sec']} сек (без вывода)."
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", c_reply)
                    except Exception: pass
                    return c_reply, avatar_status
                elif func_name == "search_internet":
                    import web_searcher
                    q_term = args.get("query", text)
                    s_report = web_searcher.search_and_format_report(q_term)
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", s_report)
                    except Exception: pass
                    return s_report, avatar_status
                elif func_name == "save_to_memory":
                    import memory_engine
                    f_fact = args.get("fact", "")
                    f_cat = args.get("category", "general")
                    memory_engine.save_memory(f_fact, username=username, category=f_cat, importance=4)
                    res_text = f"🧠 <b>Запомнила на будущее:</b> {f_fact} 😼"
                    try:
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                elif func_name == "consult_ai_consilium":
                    prompt_q = args.get("prompt", text)
                    import ai_consilium
                    c_res = ai_consilium.run_consilium(prompt_q, "general", username)
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", c_res["verdict"])
                    except Exception: pass
                    return c_res["verdict"], avatar_status
                elif func_name == "get_viral_trends":
                    cat = args.get("category", "музыка и сниппеты")
                    import trend_spider
                    t_res = trend_spider.analyze_algorithm_and_trends(cat, username)
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", t_res["report"])
                    except Exception: pass
                    return t_res["report"], avatar_status
                elif func_name == "auto_heal_farm":
                    import terminal_autonomy
                    h_res = terminal_autonomy.diagnose_and_heal_farm()
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", h_res["report"])
                    except Exception: pass
                    return h_res["report"], avatar_status
                elif func_name == "get_live_logs":
                    import terminal_autonomy
                    logs = terminal_autonomy.get_live_farm_logs()
                    res_text = f"📋 <b>Живые логи фермы:</b>\n\n{logs}"
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                elif func_name == "run_farm_script":
                    sname = args.get("script_name", "прогрев")
                    import terminal_autonomy
                    r_res = terminal_autonomy.start_farm_script(sname)
                    res_text = r_res.get("message", str(r_res))
                    try:
                        import memory_engine
                        memory_engine.save_dialog_turn(session_id, "user", text)
                        memory_engine.save_dialog_turn(session_id, "model", res_text)
                    except Exception: pass
                    return res_text, avatar_status
                        
            final_text = part.get("text", "Молчу, бля. Чет лень отвечать.")
            
            # Сохраняем диалог в скользящую историю сессии
            try:
                import memory_engine
                memory_engine.save_dialog_turn(session_id, "user", text)
                memory_engine.save_dialog_turn(session_id, "model", final_text)
                threading.Thread(target=memory_engine.auto_extract_facts_from_dialog, args=(text, final_text, username), daemon=True).start()
            except Exception:
                pass
                
            return final_text, avatar_status
        except Exception as e:
            last_err = e
            continue
            
    print(f"[Gemini All Models Fallback Note] {last_err}")
    return process_chat_message_local(text, username), "normal"




import auto_healer


def main_loop():
    # Инициализация базы данных Plitty 3.0
    db_manager.init_db()

    # Запуск фонового движения самовосстановления и клининга
    auto_healer.start_auto_healer()

    # Запуск фонового опроса подключенных устройств
    poller = threading.Thread(target=connected_devices_poller, daemon=True)
    poller.start()

    # Запуск встроенного веб-сервера
    start_web_server()

    # Запуск Telegram-моста (SnipPlit)
    try:
        import telegram_bridge
        telegram_bridge.start_telegram_bridge()
    except Exception as e_tg:
        print(f"[Telegram Bridge Error] {e_tg}")

    # Запуск проактивного стража
    try:
        import proactive_sentinel
        proactive_sentinel.start_sentinel()
        import plitty_healthcheck_watchdog
        plitty_healthcheck_watchdog.start_watchdog()
    except Exception as e_sent:
        print(f"[Sentinel Error] {e_sent}")
    
    print("[+] Облачный агент Plitty 3.0 успешно запущен...")
    clear_logs_and_status()

    
    last_processed_cmd_timestamp = 0
    last_processed_chat_timestamp = 0
    
    # Первичная проверка текущей команды и чата в БД (чтобы не запускать старое)
    cmd = fb_request("command")
    if cmd and "timestamp" in cmd:
        last_processed_cmd_timestamp = cmd["timestamp"]
        
    chat = fb_request("chat/message")
    if chat and "timestamp" in chat:
        last_processed_chat_timestamp = chat["timestamp"]
        
    while True:
        try:
            # 1. Проверка команд
            cmd = fb_request("command")
            if cmd and "timestamp" in cmd:
                cmd_ts = cmd["timestamp"]
                if cmd_ts > last_processed_cmd_timestamp:
                    last_processed_cmd_timestamp = cmd_ts
                    action = cmd.get("action")
                    accounts = cmd.get("accounts", "")
                    
                    print(f"\n[+] Получена новая команда: {action} (ts: {cmd_ts})")
                    
                    if action in ["start_warming", "start_boost", "start_night_boost", "start_live_stream"]:
                        if action == "start_warming":
                            script_type = "warming"
                        elif action == "start_boost":
                            script_type = "boost"
                        elif action == "start_night_boost":
                            script_type = "night_boost"
                        elif action == "start_live_stream":
                            script_type = "live_stream" 
                        run_script(script_type, accounts)
                    elif action == "stop":
                        stop_active_script()
            
            # 2. Проверка чата
            chat = fb_request("chat/message")
            if chat and "timestamp" in chat:
                chat_ts = chat["timestamp"]
                if chat_ts > last_processed_chat_timestamp:
                    last_processed_chat_timestamp = chat_ts
                    text = chat.get("text", "")
                    print(f"\n[Chat] Получено сообщение: '{text}' (ts: {chat_ts})")
                    
                    # Получаем текущее имя пользователя
                    username = fb_request("chat/username")
                    if not username:
                        username = "чучело"
                    
                    # Записываем входящее сообщение пользователя в БД SQLite
                    db_manager.log_chat_message(username, text, "user")

                    # Обрабатываем команду и пишем ответ
                    reply_text, avatar_state = process_chat_message(text, username)
                    
                    # Генерируем нейро-голосовой аудиофайл Плитти
                    audio_url = ""
                    try:
                        audio_path = voice_engine.generate_plitty_voice(reply_text)
                        audio_filename = os.path.basename(audio_path)
                        audio_url = f"/{audio_filename}"
                        print(f"[Voice AI] Создан аудио-ответ: {audio_filename}")
                    except Exception as e_voice:
                        print(f"[Voice AI Error] {e_voice}")

                    # Записываем ответ Плитти в БД SQLite
                    db_manager.log_chat_message("Plitty", reply_text, avatar_state)

                    fb_request("chat/response", "PUT", {
                        "text": reply_text,
                        "avatar_state": avatar_state,
                        "audio_url": audio_url,
                        "timestamp": time.time() * 1000
                    })
                        
            time.sleep(2.0)
        except KeyboardInterrupt:
            print("\n[!] Остановка облачного агента...")
            stop_active_script()
            break
        except Exception as e:
            print(f"[Loop Error] {e}")
            time.sleep(5.0)

if __name__ == "__main__":
    main_loop()
