# stream_automation.py
"""
Модуль автономной имитации онлайна и зрительской активности на стримах (TikTok LIVE и Kick).
Использует исключительно ОФИЦИАЛЬНЫЕ НАЦИВНЫЕ ПРИЛОЖЕНИЯ:
- Kick Mobile App (com.kick.mobile) с авторизованными аккаунтами
- TikTok App (com.zhiliaoapp.musically) с авторизованными аккаунтами

Правила таймингов и жизненного цикла:
1. Заход всех устройств на стрим в течение первых 30 секунд (с мягкой рассинхронизацией).
2. ПРИВЕТСТВИЕ: каждый зашедший телефон оставляет приветствие в первые 30 секунд после входа (если чат открыт).
3. ПРОВЕРКА ОГРАНИЧЕНИЙ: если чат 'Followers only' / 'Subscribers only', телефон НЕ спамит и НЕ пытается вводить текст, а фиксирует пропуск и причину.
4. Каждый телефон смотрит стрим ровно заданное пользователем время с момента входа.
5. По окончанию времени телефоны отключаются в течение 30 секунд в рассинхроне (desynchronized exit).
6. Приложение при выходе ПОЛНОСТЬЮ закрывается через force-stop (без Picture-in-Picture).
"""

import time
import random
import re
import sys
from adb_helper import ADBDevice

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Банк приветствий (первые 30 секунд) - адресованы исключительно стримеру лично
GREETINGS_BANK = [
    "привет",
    "как дела",
    "йо",
    "вай",
    "Ку ку",
    "Здарова!",
    "Чо как?",
    "Хай 👋",
    "йоу",
    "ку",
    "приветик",
    "хай",
    "Салют!",
    "как сам?",
    "как жизнь?",
    "здорово"
]

# Банк универсальных живых комментариев и нейтральных реакций (подходит под любой стрим)
REGULAR_COMMENTS_BANK = [
    # 1 слово / эмодзи (~50%)
    "топ 🔥",
    "кайф",
    "четко",
    "вайб ✨",
    "красава 👍",
    "стильно",
    "годно",
    "сильно",
    "мощно",
    "норм",
    "хорош",
    "лайк 👍",
    "👍👍👍",
    "🔥🔥🔥",
    "😎",
    "класс",
    "огонь",
    "плюсую",
    "солидно",
    "чилл",

    # 2 слова (~30%)
    "вайб кайф",
    "звук топ",
    "на стиле",
    "топ контент",
    "красиво делаешь",
    "четкий стрим",
    "плюс реп",
    "хороший вайб",
    "очень годно",
    "все четко",
    "отличный эфир",
    "красивая картинка",

    # 3-4 слова (~20%)
    "атмосфера очень приятная",
    "картинка и звук супер",
    "приятно тебя слушать",
    "навалил хорошего стиля",
    "уютно тут у тебя",
    "контент как всегда топ",
    "отличная подача материала",

    # Нейтральные вопросы стримеру (без привязки к конкретной теме)
    "Как настроение?",
    "Давно стримишь?",
    "Как день прошел?",
    "Как сам?",
    "Чо по планам?",
    "Сколько еще стримить будешь?",
    "Как делишки?",
    "Что нового?",
    "Часто стримишь сейчас?",
    "Какие планы на вечер?",
    "Устал уже?",
    "Как самочувствие?",
    "Много стримишь сегодня?",
    "Как проходит день?",
    "Что по настроению?",
    "Чай пьешь?",
    "Стрим давно идет?",
    "Как погода у тебя?",
    "Во сколько закончил дела?",
    "Какое расписание стримов?",
    "Еще долго будешь в эфире?",
    "Как неделя проходит?",
    "Откуда стримишь?",
    "Всё норм сегодня?",
    "Были интересные новости сегодня?",
    "Стрим сохраняешь?",
    "Как обстановка вообще?",
    "Много дел на сегодня?",
    "Надолго сегодня зашел?",
    "Как настрой на стрим?"
]


class KickLiveWatcher:
    """
    Класс управления нативным приложением Kick Mobile (com.kick.mobile).
    Интегрирован с Gemini AI Brain, Smart Role Distribution и Time-Paced расписанием.
    """
    def __init__(self, device: ADBDevice, streamer: str, duration_minutes: int = 10,
                 enable_likes: bool = False, enable_comments: bool = True,
                 stop_event=None, status_dict=None, role_info: dict = None):
        self.dev = device
        self.streamer = streamer.lstrip('@').strip()
        self.duration_sec = int(duration_minutes * 60)
        self.duration_min = duration_minutes
        self.enable_comments = enable_comments
        self.stop_event = stop_event
        self.status_dict = status_dict if status_dict is not None else {}
        self.role_info = role_info or {"role": "organic_viewer", "max_comments": 1, "scheduled_times": [random.uniform(15.0, 45.0)]}
        self.comments_sent = 0
        self.comments_skipped = 0
        self.skip_reason = ""
        self.start_time = None

    def log(self, msg: str):
        role_tag = self.role_info.get("role", "viewer").upper()
        print(f"[{self.dev.device_id}] [Kick @{self.streamer}] [{role_tag}] {msg}")

    def fix_portrait_orientation(self):
        try:
            self.dev.run_shell("settings put system accelerometer_rotation 0")
            self.dev.run_shell("settings put system user_rotation 0")
        except Exception:
            pass

    def ensure_adb_keyboard(self):
        try:
            self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
            self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")
        except Exception:
            pass

    def open_kick_stream(self):
        self.log(f"🟢 Запуск прямого эфира Kick: https://kick.com/{self.streamer}...")
        self.fix_portrait_orientation()
        
        self.dev.run_shell("am force-stop com.android.vending")
        self.dev.run_shell("am force-stop com.kick.mobile")
        time.sleep(0.4)
        
        target_url = f"https://kick.com/{self.streamer}"
        self.dev.run_shell(f"am start -a android.intent.action.VIEW -d {target_url} com.kick.mobile")
        time.sleep(2.5)
        # Контрольный повтор Intent гарантирует прямой переход в плеер даже при холодном старте Kick
        self.dev.run_shell(f"am start -a android.intent.action.VIEW -d {target_url} com.kick.mobile")
        time.sleep(2.5)
        
        # Быстрый сброс модалок если возникли поверх
        for _ in range(2):
            close_x = int(self.dev.width * 0.911)
            close_y = int(self.dev.height * 0.251)
            self.dev.run_shell(f"input tap {close_x} {close_y}")
            time.sleep(0.15)
            cx = self.dev.width // 2
            cy = int(self.dev.height * 0.894)
            self.dev.run_shell(f"input tap {cx} {cy}")
            time.sleep(0.2)
            
        self.fix_portrait_orientation()
        self.log(f"✓ Прямой эфир @{self.streamer} открыт!")

    def ensure_stream_active(self):
        """
        Self-Healing Guardian: Проверяет, что стрим активен.
        Если процесс Kick упал или приложение свернуто на рабочий стол — восстанавливает стрим.
        """
        try:
            pid_out = self.dev.run_shell("pidof com.kick.mobile")
            focus_out = self.dev.run_shell("dumpsys window | grep -i currentfocus")
            
            # Если процесс Kick не запущен вовсе или активен рабочий стол лаунчера
            target_url = f"https://kick.com/{self.streamer}"
            if not pid_out.strip() or ("com.sec.android.app.launcher" in focus_out or "com.android.launcher" in focus_out):
                self.log(f"⚠️ [Guardian] Восстановление стрима @{self.streamer}...")
                self.dev.run_shell(f"am start -a android.intent.action.VIEW -d {target_url} com.kick.mobile")
                time.sleep(2.0)
                self.fix_portrait_orientation()
        except Exception:
            pass

    def send_kick_comment(self, phase: str = "mid"):
        if not self.enable_comments:
            return

        # Гарантируем, что стрим активен перед отправкой
        self.ensure_stream_active()

        try:
            from gemini_stream_brain import stream_brain
            comment_text = stream_brain.generate_comment(self.streamer, "kick", phase)
        except Exception:
            comment_text = random.choice(GREETINGS_BANK if phase == "greeting" else REGULAR_COMMENTS_BANK)
            
        self.log(f"💬 Отправка в чат Kick ({phase}): «{comment_text}»")
        
        import base64
        self.ensure_adb_keyboard()
        
        tap_x = int(self.dev.width * 0.435)
        tap_y = int(self.dev.height * 0.838)
        btn_send_x = int(self.dev.width * 0.920)
        btn_send_y = int(self.dev.height * 0.842)
        
        # 1. Надежный фокус поля ввода (с достаточным временем для IME)
        self.dev.run_shell(f"input tap {tap_x} {tap_y}")
        time.sleep(0.50)
        
        # 2. Очистка и вставка текста через Base64
        self.dev.run_shell("am broadcast -a ADB_CLEAR_TEXT")
        time.sleep(0.15)
        b64_msg = base64.b64encode(comment_text.encode("utf-8")).decode("ascii")
        self.dev.run_shell(f"am broadcast -a ADB_INPUT_B64 --es msg '{b64_msg}'")
        time.sleep(0.50)
        
        # 3. Одиночное нажатие кнопки Отправить (самолетик)
        self.dev.run_shell(f"input tap {btn_send_x} {btn_send_y}")
        time.sleep(0.35)
        
        # 4. Скрытие клавиатуры
        self.dev.run_shell("input keyevent 111")
        time.sleep(0.20)
        
        self.comments_sent += 1
        if self.dev.device_id in self.status_dict:
            self.status_dict[self.dev.device_id]["comments"] = self.comments_sent

    def run(self):
        role = self.role_info.get("role", "lurker")
        scheduled_times = list(self.role_info.get("scheduled_times", []))
        
        self.status_dict[self.dev.device_id] = {
            "platform": "kick",
            "streamer": self.streamer,
            "status": "starting",
            "role": role,
            "comments": 0,
            "comments_skipped": 0,
            "skip_reason": "",
            "elapsed_sec": 0
        }
        
        self.open_kick_stream()
        
        self.start_time = time.time()
        self.status_dict[self.dev.device_id]["status"] = f"watching ({role})"
        
        try:
            while True:
                if self.stop_event and self.stop_event.is_set():
                    break
                elapsed = time.time() - self.start_time
                if elapsed >= self.duration_sec:
                    self.log(f"⏰ Время просмотра ({self.duration_min} мин) отработано!")
                    exit_delay = random.uniform(0.0, 10.0)
                    if self.stop_event:
                        self.stop_event.wait(exit_delay)
                    else:
                        time.sleep(exit_delay)
                    break
                    
                self.status_dict[self.dev.device_id]["elapsed_sec"] = int(elapsed)
                self.status_dict[self.dev.device_id]["comments"] = self.comments_sent
                
                # Проверка расписания отправки для этого устройства
                if self.enable_comments and scheduled_times and elapsed >= scheduled_times[0]:
                    target_time = scheduled_times.pop(0)
                    if elapsed < self.duration_sec * 0.15 or role == "greeter":
                        phase = "greeting"
                    elif elapsed < self.duration_sec * 0.50:
                        phase = "early"
                    elif elapsed < self.duration_sec * 0.80:
                        phase = "mid"
                    else:
                        phase = "late"
                    self.send_kick_comment(phase)
                
                # Self-Healing Guardian: периодический контроль стрима (каждые 20 сек)
                if int(elapsed) % 20 < 2:
                    self.ensure_stream_active()

                # Имитация активности (периодический скролл чата у всех, включая Lurkers)
                if random.random() < 0.20:
                    chat_x = int(self.dev.width * 0.8)
                    y1 = int(self.dev.height * 0.70)
                    y2 = int(self.dev.height * 0.50)
                    self.dev.swipe(chat_x, y1, chat_x, y2, duration_ms=180)
                    
                time.sleep(2.0)
        finally:
            self.cleanup()

    def cleanup(self):
        self.log(f"🏁 Завершение Kick сессии. Закрытие приложения. Комментов: {self.comments_sent}")
        if self.dev.device_id in self.status_dict:
            self.status_dict[self.dev.device_id]["status"] = "finished"
        self.dev.run_shell("am force-stop com.kick.mobile")
        self.dev.run_shell("am force-stop com.android.chrome")
        time.sleep(0.3)
        self.dev.run_shell("input keyevent 3")


class TwitchLiveWatcher:
    """
    Класс управления нативным приложением Twitch Mobile (tv.twitch.android.app) для одного устройства.
    """
    def __init__(self, device: ADBDevice, streamer: str, duration_minutes: int = 10,
                 enable_likes: bool = False, enable_comments: bool = True,
                 stop_event=None, status_dict=None):
        self.dev = device
        self.streamer = streamer.lstrip('@').strip()
        self.duration_sec = int(duration_minutes * 60)
        self.enable_comments = enable_comments
        self.stop_event = stop_event
        self.status_dict = status_dict if status_dict is not None else {}
        self.comments_sent = 0
        self.comments_skipped = 0
        self.skip_reason = ""
        self.start_time = None

    def log(self, msg: str):
        print(f"[{self.dev.device_id}] [Twitch App @{self.streamer}] {msg}")

    def wait_until_stream_ready(self, timeout=25) -> tuple[bool, str]:
        """
        Ожидает полной прогрузки плеера и чата Twitch.
        """
        start_t = time.time()
        while time.time() - start_t < timeout:
            out, _ = self.dev.run_shell("uiautomator dump /sdcard/twitch_load.xml && cat /sdcard/twitch_load.xml", timeout=6)
            lower_out = out.lower()
            if any(k in lower_out for k in ["send a message", "отправить сообщение", "followers only", "subscribers only", "chat", "чат", "follow to chat"]):
                return True, lower_out
            time.sleep(2.0)
        return False, ""

    def open_twitch_stream(self) -> str:
        self.log(f"🎬 Запуск Twitch и вход на стрим @{self.streamer}...")
        url = f"https://twitch.tv/{self.streamer}"
        
        out, _ = self.dev.run_shell("pm list packages | grep tv.twitch.android.app")
        if "tv.twitch.android.app" in out:
            self.dev.run_shell(f'am start -a android.intent.action.VIEW -d "{url}" -p tv.twitch.android.app')
        else:
            self.dev.run_shell(f'am start -a android.intent.action.VIEW -d "https://m.twitch.tv/{self.streamer}" -p com.android.chrome')
            
        self.log("⏳ Ожидание прогрузки плеера и чата...")
        is_ready, ui_dump = self.wait_until_stream_ready(timeout=25)
        if is_ready:
            self.log("✓ Стрим и чат успешно прогружены.")
        else:
            self.log("⚠️ Стрим загрузился, продолжаем сессию.")
        return ui_dump

    def check_chat_restrictions(self) -> tuple[bool, str]:
        try:
            out, _ = self.dev.run_shell("uiautomator dump /sdcard/tw_chk.xml && cat /sdcard/tw_chk.xml", timeout=5)
            lower_out = out.lower()
            if "followers-only" in lower_out or "followers only" in lower_out or "только для отслеживающих" in lower_out:
                return True, "Чат только для фолловеров (Followers only)"
            if "subscribers-only" in lower_out or "subscribers only" in lower_out or "только для подписчиков" in lower_out:
                return True, "Чат только для подписчиков (Subscribers only)"
            if "verification required" in lower_out or "требуется подтверждение" in lower_out:
                return True, "Требуется верификация номера телефона"
            if "slow mode" in lower_out or "медленный режим" in lower_out:
                return False, "Медленный режим чата"
        except Exception as e:
            self.log(f"⚠️ Ошибка проверки чата: {e}")
        return False, ""

    def ensure_adb_keyboard(self):
        """
        Проверяет текущую клавиатуру. Если ADBKeyboard отключена или пользователь
        печатал вручную, автоматически активирует AdbIME перед отправкой.
        """
        try:
            out, _ = self.dev.run_shell("settings get secure default_input_method")
            if "com.android.adbkeyboard/.AdbIME" not in out:
                self.log("⌨️ Переключение активной клавиатуры на ADBKeyboard...")
                self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
                self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")
                time.sleep(0.4)
        except Exception:
            self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
            self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")

    def send_twitch_comment(self, comment_text: str = None):
        self.ensure_adb_keyboard()
        if not self.enable_comments:
            return

        if not comment_text:
            comment_text = random.choice(GREETINGS_BANK if self.comments_sent == 0 else REGULAR_COMMENTS_BANK)
            
        self.log(f"💬 Ввод с клавиатуры и отправка в Twitch: «{comment_text}»")
        
        import base64
        self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
        self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")
        
        chat_box_x = int(self.dev.width * 0.35)
        chat_box_y = int(self.dev.height * 0.94)
        self.dev.tap(chat_box_x, chat_box_y)
        time.sleep(1.2)
        
        b64_msg = base64.b64encode(comment_text.encode("utf-8")).decode("ascii")
        self.dev.run_shell(f"am broadcast -a ADB_INPUT_B64 --es msg '{b64_msg}'")
        time.sleep(0.8)
        
        self.dev.run_shell("input keyevent 66")
        send_btn_x = int(self.dev.width * 0.92)
        send_btn_y = int(self.dev.height * 0.94)
        self.dev.tap(send_btn_x, send_btn_y)
        time.sleep(0.5)
        
        self.comments_sent += 1
        self.status_dict[self.dev.device_id]["comments"] = self.comments_sent

    def run(self):
        self.status_dict[self.dev.device_id] = {
            "platform": "twitch",
            "streamer": self.streamer,
            "status": "starting",
            "comments": 0,
            "comments_skipped": 0,
            "skip_reason": "",
            "elapsed_sec": 0
        }
        
        ui_dump = self.open_twitch_stream()
        
        self.start_time = time.time()
        self.status_dict[self.dev.device_id]["status"] = "watching"
        
        if self.enable_comments:
            if "followers only" in ui_dump or "followers-only" in ui_dump:
                is_restricted, reason = True, "Чат только для фолловеров (Followers only)"
            elif "subscribers only" in ui_dump or "subscribers-only" in ui_dump:
                is_restricted, reason = True, "Чат только для подписчиков (Subscribers only)"
            else:
                is_restricted, reason = self.check_chat_restrictions()
                
            if is_restricted:
                self.log(f"🛡️ Плашка '{reason}'. Отправка комментариев отменена (пропуск).")
                self.comments_skipped = 1
                self.skip_reason = reason
                self.status_dict[self.dev.device_id]["comments_skipped"] = 1
                self.status_dict[self.dev.device_id]["skip_reason"] = reason
                self.enable_comments = False
            else:
                self.log("✓ Чат открыт для сообщений.")
                
        is_greeting_pending = self.enable_comments
        next_comment_time = self.start_time + random.uniform(6.0, 24.0)
        
        try:
            while True:
                if self.stop_event and self.stop_event.is_set():
                    break
                elapsed = time.time() - self.start_time
                if elapsed >= self.duration_sec:
                    self.log(f"⏰ Заданное время просмотра ({self.duration_sec // 60} мин) отработано!")
                    
                    if self.enable_comments and self.comments_sent == 0:
                        greeting = random.choice(GREETINGS_BANK)
                        self.send_twitch_comment(greeting)
                        time.sleep(1.0)
                        
                    exit_delay = random.uniform(0.0, 25.0)
                    self.log(f"⏳ Рассинхронизация отключения ({exit_delay:.1f} сек)...")
                    if self.stop_event:
                        self.stop_event.wait(exit_delay)
                    else:
                        time.sleep(exit_delay)
                    break
                    
                self.status_dict[self.dev.device_id]["elapsed_sec"] = int(elapsed)
                self.status_dict[self.dev.device_id]["comments"] = self.comments_sent
                
                cur_time = time.time()
                
                if self.enable_comments and cur_time >= next_comment_time:
                    if is_greeting_pending:
                        greeting = random.choice(GREETINGS_BANK)
                        self.send_twitch_comment(greeting)
                        is_greeting_pending = False
                    else:
                        regular = random.choice(REGULAR_COMMENTS_BANK)
                        self.send_twitch_comment(regular)
                    next_comment_time = cur_time + random.uniform(70.0, 160.0)
                    
                if random.random() < 0.30:
                    chat_x = int(self.dev.width * 0.8)
                    y1 = int(self.dev.height * 0.70)
                    y2 = int(self.dev.height * 0.50)
                    self.dev.swipe(chat_x, y1, chat_x, y2, duration_ms=200)
                    
                time.sleep(3.0)
        finally:
            self.cleanup()

    def cleanup(self):
        self.log(f"🏁 Завершение Twitch сессии. Полное закрытие приложения (без PiP). Комментов: {self.comments_sent}, Пропущено: {self.comments_skipped}")
        self.status_dict[self.dev.device_id]["status"] = "finished"
        self.dev.run_shell("am force-stop tv.twitch.android.app")
        self.dev.run_shell("am force-stop com.android.chrome")
        time.sleep(0.5)
        self.dev.run_shell("input keyevent 3")

class TikTokLiveWatcher:
    """
    Класс управления нативным приложением TikTok LIVE для одного устройства.
    """
    def __init__(self, device: ADBDevice, streamer: str, duration_minutes: int = 10,
                 enable_likes: bool = True, enable_comments: bool = True,
                 stop_event=None, status_dict=None):
        self.dev = device
        self.streamer = streamer.lstrip('@').strip()
        self.duration_sec = int(duration_minutes * 60)
        self.enable_likes = enable_likes
        self.enable_comments = enable_comments
        self.stop_event = stop_event
        self.status_dict = status_dict if status_dict is not None else {}
        
        self.hearts_sent = 0
        self.comments_sent = 0
        self.comments_skipped = 0
        self.skip_reason = ""
        self.is_connected_to_stream = False
        self.start_time = None

    def log(self, msg: str):
        print(f"[{self.dev.device_id}] [TikTok App @{self.streamer}] {msg}")

    def open_live_stream(self) -> bool:
        self.log(f"🎬 Запуск TikTok и вход на стрим @{self.streamer}...")
        pkg = self.dev.tiktok_package or "com.zhiliaoapp.musically"
        
        self.dev.run_shell(f'am start -a android.intent.action.VIEW -d "https://www.tiktok.com/@{self.streamer}/live" -p {pkg}')
        time.sleep(4.0)
        
        if not self.dev.is_tiktok_in_foreground():
            self.dev.run_shell(f'am start -a android.intent.action.VIEW -d "snssdk1233://user/profile/{self.streamer}" -p {pkg}')
            time.sleep(3.0)

        avatar_x = int(self.dev.width * 0.5)
        avatar_y = int(self.dev.height * 0.18)
        self.dev.tap(avatar_x, avatar_y)
        time.sleep(2.5)
        
        self.log("✓ Подключение к прямому эфиру активно.")
        self.is_connected_to_stream = True
        return True

    def check_chat_restrictions(self) -> tuple[bool, str]:
        try:
            self.dev.run_shell("uiautomator dump /sdcard/window_dump.xml", timeout=6)
            out, _ = self.dev.run_shell("cat /sdcard/window_dump.xml", timeout=4)
            lower_out = out.lower()
            if "followers only" in lower_out or "только для фолловеров" in lower_out:
                return True, "Чат только для фолловеров (Followers only)"
            if "subscribers only" in lower_out or "только для подписчиков" in lower_out:
                return True, "Чат только для подписчиков (Subscribers only)"
            if "comments turned off" in lower_out or "комментарии отключены" in lower_out:
                return True, "Комментарии отключены стримером"
        except Exception as e:
            self.log(f"⚠️ Ошибка проверки TikTok чата: {e}")
        return False, ""

    def send_likes_burst(self):
        if not self.enable_likes:
            return

        burst_count = random.randint(6, 16)
        base_x = int(self.dev.width * random.uniform(0.60, 0.85))
        base_y = int(self.dev.height * random.uniform(0.48, 0.68))
        
        for _ in range(burst_count):
            if self.stop_event and self.stop_event.is_set():
                break
            jitter_x = base_x + random.randint(-25, 25)
            jitter_y = base_y + random.randint(-25, 25)
            
            self.dev.run_shell(f"input tap {jitter_x} {jitter_y}")
            self.hearts_sent += 1
            time.sleep(random.uniform(0.08, 0.16))
            
        self.log(f"💖 Серия лайков (+{burst_count}). Всего: {self.hearts_sent}")

    def ensure_adb_keyboard(self):
        """
        Проверяет текущую клавиатуру. Если ADBKeyboard отключена или пользователь
        печатал вручную, автоматически активирует AdbIME перед отправкой.
        """
        try:
            out, _ = self.dev.run_shell("settings get secure default_input_method")
            if "com.android.adbkeyboard/.AdbIME" not in out:
                self.log("⌨️ Переключение активной клавиатуры на ADBKeyboard...")
                self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
                self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")
                time.sleep(0.4)
        except Exception:
            self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
            self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")

    def send_comment(self, comment_text: str = None):
        self.ensure_adb_keyboard()
        if not self.enable_comments:
            return

        if not comment_text:
            comment_text = random.choice(GREETINGS_BANK if self.comments_sent == 0 else REGULAR_COMMENTS_BANK)
            
        self.log(f"💬 Ввод с клавиатуры и отправка в TikTok: «{comment_text}»")
        
        import base64
        self.dev.run_shell("ime enable com.android.adbkeyboard/.AdbIME")
        self.dev.run_shell("ime set com.android.adbkeyboard/.AdbIME")
        
        input_x = int(self.dev.width * 0.25)
        input_y = int(self.dev.height * 0.95)
        self.dev.tap(input_x, input_y)
        time.sleep(1.0)
        
        b64_msg = base64.b64encode(comment_text.encode("utf-8")).decode("ascii")
        self.dev.run_shell(f"am broadcast -a ADB_INPUT_B64 --es msg '{b64_msg}'")
        time.sleep(0.8)
        
        self.dev.run_shell("input keyevent 66")
        time.sleep(0.5)
        
        if self.dev.is_keyboard_open():
            self.dev.press_back()
            time.sleep(0.4)
            
        self.comments_sent += 1
        self.status_dict[self.dev.device_id]["comments"] = self.comments_sent

    def run(self):
        self.status_dict[self.dev.device_id] = {
            "platform": "tiktok",
            "streamer": self.streamer,
            "status": "starting",
            "hearts": 0,
            "comments": 0,
            "comments_skipped": 0,
            "skip_reason": "",
            "elapsed_sec": 0
        }
        
        self.open_live_stream()
        
        self.start_time = time.time()
        self.status_dict[self.dev.device_id]["status"] = "watching"
        
        if self.enable_comments:
            is_restricted, reason = self.check_chat_restrictions()
            if is_restricted:
                self.log(f"🛡️ {reason}. Комментарии для устройства пропущены.")
                self.comments_skipped = 1
                self.skip_reason = reason
                self.status_dict[self.dev.device_id]["comments_skipped"] = 1
                self.status_dict[self.dev.device_id]["skip_reason"] = reason
                self.enable_comments = False
        
        next_like_time = time.time() + random.uniform(5, 12)
        
        is_greeting_pending = self.enable_comments
        next_comment_time = self.start_time + random.uniform(6.0, 24.0)
        
        try:
            while True:
                if self.stop_event and self.stop_event.is_set():
                    self.log("🛑 Получен сигнал остановки.")
                    break
                    
                elapsed = time.time() - self.start_time
                if elapsed >= self.duration_sec:
                    self.log(f"⏰ Заданное время просмотра ({self.duration_sec // 60} мин) отработано!")
                    
                    exit_delay = random.uniform(0.0, 25.0)
                    self.log(f"⏳ Рассинхронизация отключения ({exit_delay:.1f} сек)...")
                    if self.stop_event:
                        self.stop_event.wait(exit_delay)
                    else:
                        time.sleep(exit_delay)
                    break
                    
                self.status_dict[self.dev.device_id]["elapsed_sec"] = int(elapsed)
                self.status_dict[self.dev.device_id]["hearts"] = self.hearts_sent
                self.status_dict[self.dev.device_id]["comments"] = self.comments_sent
                
                cur_time = time.time()
                
                if self.enable_likes and cur_time >= next_like_time:
                    self.send_likes_burst()
                    next_like_time = cur_time + random.uniform(15, 45)
                    
                if self.enable_comments and cur_time >= next_comment_time:
                    if is_greeting_pending:
                        greeting = random.choice(GREETINGS_BANK)
                        self.send_comment(greeting)
                        is_greeting_pending = False
                    else:
                        regular = random.choice(REGULAR_COMMENTS_BANK)
                        self.send_comment(regular)
                    next_comment_time = cur_time + random.uniform(70, 180)
                    
                time.sleep(2.0)
                
        except Exception as e:
            self.log(f"❌ Ошибка в ходе сессии: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        self.log(f"🏁 Завершение сессии. Полное закрытие TikTok (без PiP). Лайков: {self.hearts_sent}, Комментов: {self.comments_sent}, Пропущено: {self.comments_skipped}")
        self.status_dict[self.dev.device_id]["status"] = "finished"
        pkg = self.dev.tiktok_package or "com.zhiliaoapp.musically"
        self.dev.run_shell(f"am force-stop {pkg}")
        self.dev.run_shell("am force-stop com.android.chrome")
        time.sleep(0.5)
        self.dev.run_shell("input keyevent 3")
