# telegram_bridge.py
"""
Модуль интеграции Telegram-бота (SnipPlit / Plitty Bridge).
Обеспечивает двустороннюю связь между Telegram и Плитти:
1. Отправка сгенерированных изображений, отчетов и голосовых реплик в Telegram.
2. Прием команд и промптов на генерацию прямо из Telegram с ответом от Плитти.
"""

import os
import sys
import time
import json
import threading
import urllib.request
import urllib.parse
import mimetypes
import uuid

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "telegram_state.json")

def load_telegram_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"chat_ids": [], "last_update_id": 0}

def save_telegram_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Telegram State Save Error] {e}")

def get_bot_token():
    import config
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "").strip()
    return token

def register_chat_id(chat_id):
    state = load_telegram_state()
    chat_ids = state.get("chat_ids", [])
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
        state["chat_ids"] = chat_ids
        save_telegram_state(state)
        print(f"[Telegram Bridge] 📱 Зарегистрирован новый Chat ID: {chat_id}")

def get_target_chat_ids():
    import config
    cfg_id = getattr(config, "TELEGRAM_CHAT_ID", "").strip()
    state = load_telegram_state()
    saved_ids = list(state.get("chat_ids", []))
    if cfg_id and cfg_id not in saved_ids:
        saved_ids.append(cfg_id)
    return saved_ids

def get_main_reply_keyboard(chat_id=None):
    base_url = get_current_public_url()
    dashboard_url = f"{base_url}/"
    snipplit_url = f"{base_url}/static/index.html"
    
    rows = [
        [
            {"text": "🐾 Plitty Пульт", "web_app": {"url": dashboard_url}},
            {"text": "🎬 SnipPlit Studio", "web_app": {"url": snipplit_url}}
        ],
        [
            {"text": "📊 Статус фермы"},
            {"text": "🍺 Налить пива"}
        ]
    ]
    if chat_id and int(chat_id) == 234658540:
        rows.append([{"text": "🛸 Мост с Antigravity IDE"}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "persistent": True
    }

def get_current_public_url():
    """
    Динамически определяет актуальный рабочий URL туннеля.
    Сначала проверяет Firebase RTDB, затем локальный файл или актуальный Cloudflare URL.
    """
    # 1. Проверяем Firebase
    try:
        req = urllib.request.Request("https://plita-1c1c7-default-rtdb.firebaseio.com/status/public_url.json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = resp.read().decode("utf-8").strip(' "\n\r')
            if data and data.startswith("https://"):
                return data.rstrip('/')
    except Exception:
        pass
        
    # 2. Проверяем локальный файл tunnel_url.txt
    url_file = os.path.join(os.path.dirname(__file__), "tunnel_url.txt")
    if os.path.exists(url_file):
        try:
            with open(url_file, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved.startswith("https://"):
                    return saved.rstrip('/')
        except Exception:
            pass

    # 3. Дефолтный актуальный Cloudflare URL
    return "https://supporters-jam-msgid-defense.trycloudflare.com"

def get_snipplit_inline_keyboard(chat_id=None):
    base_url = get_current_public_url()
    snipplit_url = f"{base_url}/static/index.html"
    dashboard_url = f"{base_url}/"
    rows = [
        [
            {"text": "🐾 Plitty Пульт", "web_app": {"url": dashboard_url}}
        ],
        [
            {"text": "🎬 SnipPlit Studio (Mini App)", "web_app": {"url": snipplit_url}}
        ],
        [
            {"text": "🍺 Налить Плитти пива", "callback_data": "menu_beer"}
        ]
    ]
    # Секретная кнопка только для Алексея
    if chat_id and int(chat_id) == 234658540:
        import antigravity_bridge
        is_act = antigravity_bridge.is_antigravity_mode(chat_id)
        status_tag = "ВКЛЮЧЕН ✅" if is_act else "ВЫКЛЮЧЕН ⚪"
        rows.append([
            {"text": f"🛸 Antigravity IDE [{status_tag}]", "callback_data": "menu_antigravity_toggle"}
        ])
        
    return {
        "inline_keyboard": rows
    }




def send_chat_action(chat_id, action="typing"):
    """
    Отправляет статус действия в Telegram ('typing', 'upload_photo', и т.д.)
    """
    token = get_bot_token()
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        body = {"chat_id": chat_id, "action": action}
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

class TypingHeartbeat:
    """
    Фоновый контекстный менеджер, который шлет статус 'typing' каждые 4 секунды, пока идет генерация.
    """
    def __init__(self, chat_id, action="typing"):
        self.chat_id = chat_id
        self.action = action
        self._stop_event = threading.Event()
        self._thread = None

    def __enter__(self):
        send_chat_action(self.chat_id, self.action)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop_event.wait(3.8):
            send_chat_action(self.chat_id, self.action)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)


def send_message(text, chat_id=None, parse_mode="HTML", reply_markup=None):
    token = get_bot_token()
    if not token:
        print("[Telegram Bridge] ⚠️ TELEGRAM_BOT_TOKEN не задан в config.py")
        return False

    target_ids = [chat_id] if chat_id else get_target_chat_ids()
    if not target_ids:
        print("[Telegram Bridge] ⚠️ Нет активных Chat ID. Напишите боту /start в Telegram.")
        return False

    if reply_markup is None:
        reply_markup = get_main_reply_keyboard()

    success = False
    for cid in target_ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            body = {
                "chat_id": cid,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.getcode() == 200:
                    success = True
        except Exception as e:
            print(f"[Telegram SendMessage Error] cid={cid}: {e}")
    return success

def send_photo(photo_path, caption="", chat_id=None, parse_mode="HTML", reply_markup=None):
    """
    Отправляет изображение в Telegram через multipart/form-data с кнопками.
    """
    token = get_bot_token()
    if not token:
        print("[Telegram Bridge] ⚠️ TELEGRAM_BOT_TOKEN не задан в config.py")
        return False

    if not os.path.exists(photo_path):
        print(f"[Telegram Bridge] ❌ Файл не найден: {photo_path}")
        return False

    target_ids = [chat_id] if chat_id else get_target_chat_ids()
    if not target_ids:
        print("[Telegram Bridge] ⚠️ Нет активных Chat ID. Напишите боту /start в Telegram.")
        return False

    if reply_markup is None:
        base_url = get_current_public_url()
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "🎬 Открыть Studio", "web_app": {"url": f"{base_url}/static/index.html"}},
                    {"text": "🍺 Налить пива", "callback_data": "menu_beer"}
                ]
            ]
        }

    success = False
    for cid in target_ids:
        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body_bytes = bytearray()

            # chat_id
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{cid}\r\n'.encode("utf-8"))

            # caption
            if caption:
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n{parse_mode}\r\n'.encode("utf-8"))

            # reply_markup
            if reply_markup:
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="reply_markup"\r\n\r\n{json.dumps(reply_markup)}\r\n'.encode("utf-8"))

            # photo file
            filename = os.path.basename(photo_path)
            mime_type = mimetypes.guess_type(photo_path)[0] or "application/octet-stream"
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode("utf-8"))
            body_bytes.extend(f'Content-Type: {mime_type}\r\n\r\n'.encode("utf-8"))
            with open(photo_path, "rb") as f:
                body_bytes.extend(f.read())
            body_bytes.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            req = urllib.request.Request(
                url,
                data=bytes(body_bytes),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.getcode() == 200:
                    print(f"[Telegram Bridge] 📸 Арт успешно отправлен в Telegram (cid: {cid})!")
                    success = True
        except Exception as e:
            print(f"[Telegram SendPhoto Error] cid={cid}: {e}")

    return success


def send_document(doc_path, caption="", chat_id=None, parse_mode="HTML", reply_markup=None):
    """
    Отправляет документ/файл любого формата в Telegram через multipart/form-data.
    """
    token = get_bot_token()
    if not token or not os.path.exists(doc_path):
        return False

    target_ids = [chat_id] if chat_id else get_target_chat_ids()
    if not target_ids:
        return False

    success = False
    for cid in target_ids:
        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body_bytes = bytearray()

            # chat_id
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{cid}\r\n'.encode("utf-8"))

            # caption
            if caption:
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n{parse_mode}\r\n'.encode("utf-8"))

            # reply_markup
            if reply_markup:
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="reply_markup"\r\n\r\n{json.dumps(reply_markup)}\r\n'.encode("utf-8"))

            # document file
            filename = os.path.basename(doc_path)
            mime_type = mimetypes.guess_type(doc_path)[0] or "application/octet-stream"
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8"))
            body_bytes.extend(f'Content-Type: {mime_type}\r\n\r\n'.encode("utf-8"))
            with open(doc_path, "rb") as f:
                body_bytes.extend(f.read())
            body_bytes.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

            url = f"https://api.telegram.org/bot{token}/sendDocument"
            req = urllib.request.Request(
                url,
                data=bytes(body_bytes),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.getcode() == 200:
                    print(f"[Telegram Bridge] 📄 Документ {filename} успешно отправлен в Telegram (cid: {cid})!")
                    success = True
        except Exception as e:
            print(f"[Telegram SendDocument Error] cid={cid}: {e}")

    return success

def send_voice(voice_path, caption="", chat_id=None):
    token = get_bot_token()
    if not token or not os.path.exists(voice_path):
        return False

    target_ids = [chat_id] if chat_id else get_target_chat_ids()
    if not target_ids:
        return False

    for cid in target_ids:
        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body_bytes = bytearray()
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{cid}\r\n'.encode("utf-8"))
            if caption:
                body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
                body_bytes.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))

            filename = os.path.basename(voice_path)
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="voice"; filename="{filename}"\r\n'.encode("utf-8"))
            body_bytes.extend(b'Content-Type: audio/ogg\r\n\r\n')
            with open(voice_path, "rb") as f:
                body_bytes.extend(f.read())
            body_bytes.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

            url = f"https://api.telegram.org/bot{token}/sendVoice"
            req = urllib.request.Request(
                url,
                data=bytes(body_bytes),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=20)
        except Exception as e:
            print(f"[Telegram SendVoice Error] cid={cid}: {e}")

def answer_callback_query(callback_query_id, text=None):
    token = get_bot_token()
    if not token:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
        body = {"callback_query_id": callback_query_id}
        if text:
            body["text"] = text
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Answer Callback Error] {e}")


def download_telegram_file(file_id, save_dir=None):
    """
    Скачивает изображение или файл из Telegram и сохраняет в артефакты IDE и папку скриншотов.
    """
    token = get_bot_token()
    if not token or not file_id:
        return None
    try:
        if not save_dir:
            save_dir = os.path.join(BASE_DIR, "screenshots")
        os.makedirs(save_dir, exist_ok=True)
        
        # 1. Получаем путь к файлу
        url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "PlittyBridge/3.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            return None
        file_path_tg = data["result"]["file_path"]
        
        # 2. Скачиваем файл
        ext = os.path.splitext(file_path_tg)[1] or ".png"
        filename = f"screenshot_{int(time.time()*1000)}{ext}"
        local_path = os.path.join(save_dir, filename)
        
        # Сохраняем копию в артефакты IDE для мгновенного визуального отображения агенту
        user_uploaded_dir = r"C:\Users\a.feoktistov\.gemini\antigravity-ide\brain\177c2099-6aa9-4f4f-bac3-ae6bcc059efe\.user_uploaded"
        os.makedirs(user_uploaded_dir, exist_ok=True)
        artifact_path = os.path.join(user_uploaded_dir, filename)
        
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path_tg}"
        dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "PlittyBridge/3.0"})
        with urllib.request.urlopen(dl_req, timeout=15) as resp:
            content = resp.read()
            with open(local_path, "wb") as f:
                f.write(content)
            try:
                with open(artifact_path, "wb") as f:
                    f.write(content)
            except Exception:
                pass
                
        print(f"[Telegram Bridge] 📸 Скриншот успешно скачан: {local_path} -> {artifact_path}")
        return artifact_path
    except Exception as e:
        print(f"[Download Photo Error] {e}")
        return None


def telegram_polling_loop():
    """
    Фоновый процесс долгого опроса (Long Polling) Telegram.
    Принимает команды, кнопки и сообщения, передает их Плитти и отправляет ответы.
    """
    print("[Telegram Bridge] 🤖 Запуск интерактивного обработчика Telegram...")
    while True:
        token = get_bot_token()
        if not token:
            time.sleep(10)
            continue

        state = load_telegram_state()
        offset = state.get("last_update_id", 0) + 1

        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(url, headers={"User-Agent": "PlittyBridge/3.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            updates = data.get("result", [])
            for upd in updates:
                upd_id = upd.get("update_id", 0)
                state["last_update_id"] = upd_id

                # Обработка нажатий на инлайн-кнопки (Callback Queries)
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    cb_chat = cb.get("message", {}).get("chat", {})
                    cb_cid = cb_chat.get("id")
                    cb_user = cb.get("from", {}).get("first_name", "Хозяин")

                    if cb_data == "menu_beer":
                        answer_callback_query(cb_id, "🍺 Наливаем пивко...")
                        import cloud_agent
                        reply, _ = cloud_agent.process_chat_message("/give_beer", cb_user, session_id="unified_chat")
                        send_message(reply.replace("<br>", "\n"), chat_id=cb_cid)
                    elif cb_data == "menu_status":
                        answer_callback_query(cb_id, "📊 Опрашиваю устройства...")
                        import cloud_agent
                        reply, _ = cloud_agent.process_chat_message("статус", cb_user)
                        send_message(reply.replace("<br>", "\n"), chat_id=cb_cid)
                    elif cb_data == "menu_consilium":
                        answer_callback_query(cb_id, "🏛️ Запуск консилиума...")
                        import ai_consilium
                        c_res = ai_consilium.run_consilium("Как создать вирусный сниппет для трека?", "general", cb_user)
                        send_message(c_res["verdict"].replace("<br>", "\n"), chat_id=cb_cid)
                    elif cb_data == "menu_trends":
                        answer_callback_query(cb_id, "🕷️ Веб-паук собирает тренды...")
                        import trend_spider
                        t_res = trend_spider.analyze_algorithm_and_trends("музыка", cb_user)
                        send_message(t_res["report"].replace("<br>", "\n"), chat_id=cb_cid)
                    elif cb_data == "menu_heal":
                        answer_callback_query(cb_id, "🛡️ Запуск самолечения...")
                        import terminal_autonomy
                        h_res = terminal_autonomy.diagnose_and_heal_farm()
                        send_message(h_res["report"].replace("<br>", "\n"), chat_id=cb_cid)
                    elif cb_data == "menu_logs":
                        answer_callback_query(cb_id, "📋 Читаю логи...")
                        import terminal_autonomy
                        logs = terminal_autonomy.get_live_farm_logs()
                        send_message(f"📋 <b>Живые логи фермы:</b>\n\n{logs}", chat_id=cb_cid)
                    elif cb_data == "menu_antigravity_toggle":
                        import antigravity_bridge
                        is_act = antigravity_bridge.is_antigravity_mode(cb_cid)
                        new_mode = not is_act
                        antigravity_bridge.set_antigravity_mode(cb_cid, new_mode)
                        if new_mode:
                            answer_callback_query(cb_id, "🛸 Мост с Antigravity IDE АКТИВИРОВАН!")
                            msg_text = (
                                "🛸 <b>РЕЖИМ ПРЯМОГО МОСТА С ANTIGRAVITY IDE АКТИВИРОВАН!</b> ⚡💻\n\n"
                                "Все твои следующие сообщения напрямую транслируются в рабочий терминал разработчика Antigravity на твоём ПК.\n\n"
                                "• Ставь любые задачи по коду, архитектуре, скриптам и управлению файлами прямо с телефона.\n"
                                "• Чтобы выйти из режима и вернуться к Плитти, напиши <code>/exit_ide</code> или нажми кнопку меню."
                            )
                        else:
                            answer_callback_query(cb_id, "🐾 Возврат к обычной Плитти...")
                            msg_text = "🐾 <b>Режим моста с IDE выключен.</b> С возвращением к Плитти! 😼🍺"
                        send_message(msg_text, chat_id=cb_cid, reply_markup=get_snipplit_inline_keyboard(chat_id=cb_cid))
                    elif cb_data.startswith("redraw:"):
                        prompt = cb_data.split(":", 1)[1]
                        answer_callback_query(cb_id, "🔄 Рисую новый вариант...")
                        import cloud_agent
                        reply, _ = cloud_agent.process_chat_message(f"нарисуй {prompt}", cb_user)
                    else:
                        answer_callback_query(cb_id)
                    continue

                msg = upd.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                from_user = msg.get("from", {})
                username = from_user.get("first_name") or from_user.get("username") or "Хозяин"
                raw_text = (msg.get("text") or msg.get("caption") or "").strip()
                
                # Захват скриншотов / фотографий / изображений
                photo_path = None
                if msg.get("photo"):
                    file_id = msg["photo"][-1]["file_id"]
                    photo_path = download_telegram_file(file_id)
                elif msg.get("document"):
                    doc = msg["document"]
                    mime = doc.get("mime_type", "")
                    if "image" in mime or doc.get("file_name", "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        photo_path = download_telegram_file(doc["file_id"])
                
                # Извлекаем метаданные пересланных сообщений и ответов (Reply/Forward)
                header_parts = []
                if "forward_from" in msg:
                    f_u = msg["forward_from"]
                    f_n = f_u.get("first_name", "") + (" " + f_u.get("last_name", "") if f_u.get("last_name") else "")
                    f_uname = f" (@{f_u['username']})" if f_u.get("username") else ""
                    header_parts.append(f"📩 [Пересланное сообщение от пользователя: {f_n}{f_uname}]")
                elif "forward_from_chat" in msg:
                    header_parts.append(f"📩 [Переслано из канала/чата: {msg['forward_from_chat'].get('title', '')}]")
                elif "forward_sender_name" in msg:
                    header_parts.append(f"📩 [Пересланное сообщение от: {msg['forward_sender_name']}]")
                    
                if "reply_to_message" in msg:
                    r_m = msg["reply_to_message"]
                    r_n = r_m.get("from", {}).get("first_name", "Собеседник")
                    r_t = r_m.get("text") or r_m.get("caption") or "[Медиа/Файл]"
                    header_parts.append(f"💬 [В ответ на сообщение от {r_n}: «{r_t[:150]}»]")

                if header_parts:
                    text = "\n".join(header_parts) + "\n" + raw_text
                else:
                    text = raw_text

                if not text:
                    continue

                print(f"[Telegram Message] [{username}]: '{text}'")

                if text in ["/start", "/menu", "меню", "start"]:
                    welcome_text = (
                        f"🐾 <b>Йо, {username}!</b>\n\n"
                        "Я — <b>Plitty</b>, твой персональный сверхразумный компаньон и хозяйка этой экосистемы.\n\n"
                        "💬 <b>Мы можем говорить абсолютно обо всём:</b>\n"
                        "• Любые темы: программирование, автоматизация, сценарии, музыка, фильмы или просто беседа по душам.\n"
                        "• 🐾 <b>Plitty Dashboard</b> — управление мобильной фермой и стрим-онлайном.\n"
                        "• 🎬 <b>SnipPlit Studio</b> — открытие видео-конструктора по кнопке ниже.\n\n"
                        "Каждый мой ответ проходит через высший сверхинтеллект. Спрашивай что угодно! 😼✨"
                    )
                    send_message(welcome_text, chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                    continue


                if text in ["/snipplit", "🎬 SnipPlit Studio", "снипплит", "конструктор"]:
                    snip_text = (
                        "🎬 <b>SnipPlit Studio (Конструктор сниппетов & субтитров):</b>\n\n"
                        "Нажми на кнопку ниже, чтобы открыть интерактивное окно прямо внутри Telegram 👇"
                    )
                    send_message(snip_text, chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                    continue

                if any(k in text.lower() for k in ["пульт", "dashboard", "дашборд", "ферма"]):
                    send_message(
                        "🐾 <b>Главная веб-панель управления Plitty:</b>\n\n"
                        "Открывай по кнопке ниже 👇",
                        chat_id=chat_id,
                        reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id)
                    )
                    continue

                if text in ["/ide", "/antigravity", "🛸 Мост с Antigravity IDE", "🛸 Режим Antigravity IDE"]:
                    if int(chat_id) == 234658540:
                        import antigravity_bridge
                        is_act = antigravity_bridge.is_antigravity_mode(chat_id)
                        new_mode = not is_act
                        antigravity_bridge.set_antigravity_mode(chat_id, new_mode)
                        if new_mode:
                            msg_text = (
                                "🛸 <b>РЕЖИМ ПРЯМОГО МОСТА С ANTIGRAVITY IDE АКТИВИРОВАН!</b> ⚡💻\n\n"
                                "Все твои следующие сообщения напрямую транслируются в рабочий терминал разработчика Antigravity на твоём ПК.\n\n"
                                "• Ставь любые задачи по коду, архитектуре, скриптам и управлению файлами прямо с телефона.\n"
                                "• Чтобы выйти из режима и вернуться к Плитти, напиши <code>/exit_ide</code>"
                            )
                        else:
                            msg_text = "🐾 <b>Режим моста с IDE выключен.</b> С возвращением к Плитти! 😼🍺"
                        send_message(msg_text, chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                        continue

                if text in ["/exit_ide", "выйти из ide", "exit ide"]:
                    if int(chat_id) == 234658540:
                        import antigravity_bridge
                        antigravity_bridge.set_antigravity_mode(chat_id, False)
                        send_message("🐾 <b>Режим моста с IDE выключен.</b> С возвращением к Плитти! 😼🍺", chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                        continue

                if text in ["🏛️ Консилиум ИИ", "/consilium"]:
                    text = "консилиум Как взорвать рекомендации TikTok?"

                if text in ["🕷️ Тренды соцсетей", "/trends"]:
                    text = "тренды"

                if text in ["🛡️ Самолечение", "/heal"]:
                    text = "самолечение"

                if text in ["🎨 Сделать арт", "/draw", "арт"]:
                    send_message(
                        "🎨 Напиши мне: <i>«Нарисуй [любой объект или сцену]»</i> (например: <i>«Нарисуй киберпанк кота в капюшоне»</i>), и я сразу сгенерирую арт! 😼",
                        chat_id=chat_id
                    )
                    continue

                if text in ["🍺 Налить пива", "/beer"]:
                    text = "/give_beer"

                if text in ["📊 Статус устройств", "/status"]:
                    text = "статус"

                if any(k in text.lower() for k in ["/botfather", "ботфазер", "ссылка для ботфазера", "ссылка на пульт", "новая ссылка", "где пульт"]):
                    cur_url = get_current_public_url()
                    bf_msg = (
                        "🐾 <b>[Ссылка для BotFather в 1 клик]</b> 📱✨\n\n"
                        "Нажми на адрес ниже, чтобы скопировать его:\n"
                        f"<code>{cur_url}</code>\n\n"
                        "📋 <b>Инструкция для BotFather:</b>\n"
                        "1. Открой диалог с @BotFather\n"
                        "2. Отправь команду <code>/setmenubutton</code>\n"
                        "3. Выбери бота <code>@SnipPlit_bot</code>\n"
                        "4. Вставь скопированную ссылку выше!\n\n"
                        "👇 <i>Или открывай пульт прямо кнопкой ниже:</i>"
                    )
                    send_message(bf_msg, chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                    continue

                # Проверяем: если включен режим моста с Antigravity IDE — обрабатываем напрямую через IDE мост
                import antigravity_bridge
                if antigravity_bridge.is_antigravity_mode(chat_id):
                    with TypingHeartbeat(chat_id, action="typing"):
                        ide_reply = antigravity_bridge.process_ide_request(chat_id, username, text)
                    send_message(ide_reply.replace("<br>", "\n"), chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))
                    save_telegram_state(state)
                    continue

                # Обычный режим Плитти
                action_type = "upload_photo" if any(k in text.lower() for k in ["нарисуй", "сгенерируй", "создай арт", "сделай картинку", "/draw"]) else "typing"

                session_id = "unified_chat"  # Единая сквозная память между Telegram и Веб-приложением
                with TypingHeartbeat(chat_id, action=action_type):
                    import cloud_agent
                    reply_text, avatar_state = cloud_agent.process_chat_message(text, username, session_id=session_id)
                
                clean_reply = reply_text.replace("<br>", "\n")

                if not any(k in text.lower() for k in ["нарисуй", "сгенерируй", "создай арт", "сделай картинку"]):
                    send_message(clean_reply, chat_id=chat_id, reply_markup=get_snipplit_inline_keyboard(chat_id=chat_id))




            save_telegram_state(state)
        except Exception as e:
            # print(f"[Telegram Poll Error] {e}")
            time.sleep(5)

        time.sleep(1)

def start_telegram_bridge():
    """Запускает опрос Telegram в отдельном потоке."""
    t = threading.Thread(target=telegram_polling_loop, daemon=True, name="TelegramBridge")
    t.start()
    return t

if __name__ == "__main__":
    print("[+] Тест Telegram Bridge...")
    start_telegram_bridge()
    while True:
        time.sleep(1)


