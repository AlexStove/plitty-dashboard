# adb_helper.py
"""
Модуль для взаимодействия с Android-устройствами через ADB.
Предоставляет класс ADBDevice для выполнения команд, жестов,
получения параметров экрана и парсинга UI.
"""

import subprocess
import re
import os
import time
import xml.etree.ElementTree as ET
from config import TIKTOK_PACKAGES

try:
    from brain import a11y_transport
except ImportError:
    a11y_transport = None


import concurrent.futures

# Path to local adb
ADB_PATH = os.path.join(os.path.dirname(__file__), "platform-tools", "adb.exe")
if not os.path.exists(ADB_PATH):
    ADB_PATH = "adb"

def get_connected_devices_with_ports():
    """
    Returns list of tuples (device_id, port) for all connected devices on ports 5037 and 5038.
    """
    dev_map = {}
    for port in ["5037", "5038"]:
        try:
            output = subprocess.check_output([ADB_PATH, "-P", port, "devices"], text=True, encoding="utf-8", errors="ignore")
            for line in output.strip().split("\n")[1:]:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    dev_map[parts[0]] = port
        except Exception:
            pass
    return list(dev_map.items())

def get_connected_devices():
    """
    Returns list of connected Android device IDs from both ports 5037 and 5038.
    """
    return [dev_id for dev_id, _ in get_connected_devices_with_ports()]

def get_device_lock_state(device_id, port="5037"):
    """
    Быстрая проверка состояния блокировки и экрана отдельного устройства.
    Возвращает кортеж: (is_unlocked: bool, status_code: str, status_text: str)
    """
    try:
        cmd = [ADB_PATH, "-P", str(port), "-s", device_id, "shell", "dumpsys window policy; dumpsys power"]
        res = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore", timeout=4)
        
        is_awake = "mWakefulness=Awake" in res
        is_locked_screen = any(k in res for k in [
            "mDreamingLockscreen=true",
            "mShowingLockscreen=true",
            "mKeyguardShowing=true",
            "isStatusBarKeyguard=true",
            "mShowingDream=true"
        ])
        
        if not is_awake:
            return False, "asleep", "Экран выключен / Спит"
        elif is_locked_screen:
            return False, "locked", "Экран включен (Заблокирован)"
        else:
            return True, "unlocked", "Разблокирован (Готов к работе)"
    except Exception as e:
        return False, "error", f"Ошибка проверки: {e}"

def get_devices_with_lock_status():
    """
    Параллельный опрос всех подключенных устройств с определением их статуса блокировки.
    Возвращает список словарей с полной информацией по каждому смартфону.
    """
    dev_pairs = get_connected_devices_with_ports()
    if not dev_pairs:
        return []

    def _check(pair):
        dev_id, port = pair
        is_unlocked, status_code, status_text = get_device_lock_state(dev_id, port)
        return {
            "device_id": dev_id,
            "port": port,
            "is_unlocked": is_unlocked,
            "status_code": status_code,
            "status_text": status_text
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(dev_pairs), 4)) as executor:
        results = list(executor.map(_check, dev_pairs))
    
    # Сортируем: сначала разблокированные, затем по ID
    results.sort(key=lambda x: (not x["is_unlocked"], x["device_id"]))
    return results

def get_unlocked_devices():
    """
    Возвращает список ID только тех устройств, которые разблокированы и готовы к автоматизации.
    """
    all_devs = get_devices_with_lock_status()
    return [d["device_id"] for d in all_devs if d["is_unlocked"]]

class ADBDevice:
    def __init__(self, device_id):
        self.device_id = device_id
        # Determine which port this device is active on
        self.port = "5037"
        try:
            output = subprocess.check_output([ADB_PATH, "-P", "5038", "devices"], text=True, encoding="utf-8", errors="ignore")
            if device_id in output:
                self.port = "5038"
        except Exception:
            pass
        self.width = 1080
        self.height = 2400
        self.density = 400
        self.package_name = None
        self._initialize_device()

    def run_adb(self, args, timeout=15):
        """
        Runs ADB command with explicit port parameter.
        """
        full_args = [ADB_PATH, "-P", self.port, "-s", self.device_id] + args
        try:
            result = subprocess.run(
                full_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout
            )
            return result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return "", "timeout"
        except Exception as e:
            return "", str(e)

    def run_shell(self, cmd, timeout=15):
        """
        Выполняет команду в adb shell.
        """
        return self.run_adb(["shell", cmd], timeout)

    def is_unlocked(self):
        """
        Проверяет, разблокирован ли экран данного устройства.
        """
        unlocked, _, _ = get_device_lock_state(self.device_id, self.port)
        return unlocked

    def _initialize_device(self):
        """
        Инициализирует параметры экрана (разрешение, DPI) и находит установленный пакет TikTok.
        """
        print(f"[{self.device_id}] Инициализация устройства...")
        
        # 1. Получение разрешения экрана
        size_out, _ = self.run_shell("wm size")
        m_size = re.search(r'Physical size: (\d+)x(\d+)', size_out)
        if m_size:
            self.width = int(m_size.group(1))
            self.height = int(m_size.group(2))
        else:
            # Попробуем альтернативный парсинг (на некоторых устройствах может отличаться)
            m_size_override = re.search(r'Override size: (\d+)x(\d+)', size_out)
            if m_size_override:
                self.width = int(m_size_override.group(1))
                self.height = int(m_size_override.group(2))
        
        # 2. Получение плотности пикселей (density/dpi)
        density_out, _ = self.run_shell("wm density")
        m_dens = re.search(r'(Physical|Override) density: (\d+)', density_out)
        if m_dens:
            self.density = int(m_dens.group(2))
        
        print(f"[{self.device_id}] Разрешение: {self.width}x{self.height}, Плотность: {self.density} DPI")

        # 3. Отключение автоповорота экрана и фиксация портретного режима
        self.run_shell("settings put system accelerometer_rotation 0")
        self.run_shell("settings put system user_rotation 0")

        # 4. Поиск установленного пакета TikTok
        packages_out, _ = self.run_shell("pm list packages")
        for pkg in TIKTOK_PACKAGES:
            if pkg in packages_out:
                self.package_name = pkg
                print(f"[{self.device_id}] Найден пакет TikTok: {pkg}")
                break
        
        if not self.package_name:
            # Дефолтный fallback
            self.package_name = TIKTOK_PACKAGES[0]
            print(f"[{self.device_id}] Пакет TikTok не обнаружен. Используем по умолчанию: {self.package_name}")

    def mm_to_px(self, mm):
        """
        Конвертирует миллиметры в пиксели на основе плотности экрана.
        Формула: px = mm * (DPI / 25.4)
        """
        return int(mm * (self.density / 25.4))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        """
        Performs swipe gesture using human_touch bezier curve, falling back to standard input swipe on failure.
        """
        try:
            from brain import human_touch as ht
            ht.swipe(self.device_id, x1, y1, x2, y2)
        except Exception as e:
            print(f"[{self.device_id}] human_touch.swipe error: {e}. Falling back to standard swipe.")
            self.run_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def swipe_left(self):
        """
        Swipe left to open profile.
        """
        x_start = int(self.width * 0.90)
        x_end = int(self.width * 0.10)
        y = self.height // 2
        self.swipe(x_start, y, x_end, y, duration_ms=250)

    def tap(self, x, y):
        """
        Performs tap using human_touch comfort zones, falling back to standard input tap on failure.
        """
        try:
            from brain import human_touch as ht
            ht.tap(self.device_id, x, y)
        except Exception as e:
            print(f"[{self.device_id}] human_touch.tap error: {e}. Falling back to standard tap.")
            self.run_shell(f"input tap {x} {y}")

    def double_tap(self, x, y):
        """
        Performs double tap with human variation, falling back on failure.
        """
        try:
            from brain import human_gestures as hg
            hg.double_tap(self.device_id, x, y)
        except Exception as e:
            print(f"[{self.device_id}] human_gestures.double_tap error: {e}. Falling back to standard.")
            self.run_shell(f"input tap {x} {y} && sleep 0.15 && input tap {x} {y}")

    def press_back(self):
        """
        Нажимает кнопку НАЗАД.
        """
        self.run_shell("input keyevent 4")

    def is_tiktok_in_foreground(self):
        """
        Проверяет, находится ли TikTok на переднем плане.
        """
        stdout, _ = self.run_shell("dumpsys activity activities")
        if not stdout:
            stdout, _ = self.run_shell("dumpsys window windows")
        if not stdout:
            return True
        
        for line in stdout.splitlines():
            if ("mCurrentFocus" in line or "ResumedActivity" in line or "mFocusedApp" in line) and self.package_name in line:
                return True
        return False

    def ensure_tiktok_foreground(self):
        """
        Гарантирует, что TikTok запущен и находится на переднем плане.
        """
        if not self.is_tiktok_in_foreground():
            print(f"[{self.device_id}] TikTok не на переднем плане. Перезапуск...")
            self.start_tiktok()
            time.sleep(3.0)

    def is_keyboard_open(self):
        """
        Checks if the keyboard is open by verifying dumpsys.
        """
        stdout, _ = self.run_shell("dumpsys input_method")
        return "mInputShown=true" in stdout

    def input_text_safe(self, text, node_id=None):
        """
        Безопасно вводит текст. Если доступен Companion APK, использует ACTION_SET_TEXT (эмодзи/кириллица без ошибок).
        Иначе выполняет fallback на раздельную отправку слов через ADB input keyevent 62.
        """
        if a11y_transport and a11y_transport.is_apk_available(self.device_id):
            try:
                res = a11y_transport.type_text(self.device_id, text, node_id=node_id)
                if res:
                    print(f"[{self.device_id}] Текст успешно введен через Companion APK (ACTION_SET_TEXT): '{text}'")
                    return
            except Exception as e:
                print(f"[{self.device_id}] Ошибка ввода через Companion APK: {e}. Fallback на ADB...")

        words = text.split(" ")
        for i, word in enumerate(words):
            if i > 0:
                self.run_shell("input keyevent 62") # Пробел
            self.run_adb(["shell", "input", "text", word])


    def start_tiktok(self):
        """
        Запускает TikTok.
        """
        print(f"[{self.device_id}] Запуск TikTok...")
        # Пытаемся получить имя главной активности через cmd package resolve-activity
        stdout, _ = self.run_shell(f"cmd package resolve-activity --brief {self.package_name}")
        activity_name = None
        for line in stdout.strip().split('\n'):
            if "/" in line:
                activity_name = line.strip()
                break
        
        if activity_name:
            print(f"[{self.device_id}] Запуск активности: {activity_name}")
            self.run_shell(f"am start -n {activity_name}")
        else:
            # Fallback на monkey, если не удалось разрешить активность
            print(f"[{self.device_id}] Не удалось найти активность, запуск через monkey...")
            self.run_shell(f"monkey -p {self.package_name} -c android.intent.category.LAUNCHER 1")
            
        # Дадим приложению 12 секунд на запуск
        time.sleep(12)

    def stop_tiktok(self):
        """
        Закрывает TikTok и возвращает на главный экран.
        """
        print(f"[{self.device_id}] Закрытие TikTok...")
        self.run_shell(f"am force-stop {self.package_name}")
        time.sleep(0.5)
        self.run_shell("input keyevent 3")

    def comment_emoji(self):
        """
        Taps the first suggested emoji from the TikTok bar directly above the keyboard.
        Only runs if the keyboard is actually open to prevent misclicks.
        """
        # Give Gboard and the emoji bar 1 second to fully settle
        time.sleep(1.0)
        
        if not self.is_keyboard_open():
            print(f"[{self.device_id}] Keyboard is not open. Skipping suggested emoji click to prevent misclicks.")
            return

        offset_px = self.mm_to_px(8.35)
        emoji_x = int(self.width * 0.40)
        
        open_input = self.get_ui_dump_and_find_element(
            res_patterns=["comment_input", "input_comment", "comment_edit_text", "edit_text", r"/e9u$"]
        )
        if open_input:
            input_field_y = open_input[1]
            emoji_y = input_field_y - offset_px
            print(f"[{self.device_id}] Input field found at open y={input_field_y}. Tapping first suggested emoji at relative coordinates ({emoji_x}, {emoji_y})...")
            self.tap(emoji_x, emoji_y)
        else:
            input_field_y = int(self.height * 0.46)
            emoji_y = input_field_y - offset_px
            print(f"[{self.device_id}] Input field not found in dump (keyboard open). Tapping first suggested emoji at default y ({emoji_x}, {emoji_y})...")
            self.tap(emoji_x, emoji_y)
        time.sleep(1.5)

    def get_ui_dump_and_find_element(self, text_patterns=None, res_patterns=None, desc_patterns=None, randomize_bounds=True):
        """
        Снимает дамп UI экрана, парсит его и ищет координаты элемента.
        При доступном Companion APK считывает дерево за 5-15 мс напрямую из памяти.
        Иначе молча выполняет fallback на обычный uiautomator dump через ADB.
        """
        import random
        
        # 1. Быстрый путь: Companion APK
        if a11y_transport and a11y_transport.is_apk_available(self.device_id):
            try:
                nodes = a11y_transport.tree_nodes(self.device_id)
                if nodes:
                    for node in nodes:
                        text = node.get("text", "")
                        res_id = node.get("rid_full", "") or node.get("rid", "")
                        desc = node.get("desc", "")
                        bounds_str = node.get("bounds", "")

                        matched = False
                        if text_patterns and any(re.search(pat, text, re.IGNORECASE) for pat in text_patterns):
                            matched = True
                        if not matched and res_patterns and any(re.search(pat, res_id, re.IGNORECASE) for pat in res_patterns):
                            matched = True
                        if not matched and desc_patterns and any(re.search(pat, desc, re.IGNORECASE) for pat in desc_patterns):
                            matched = True

                        if matched and bounds_str:
                            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
                            if m:
                                x1, y1, x2, y2 = map(int, m.groups())
                                if randomize_bounds and (x2 - x1 > 10) and (y2 - y1 > 10):
                                    margin_x = int((x2 - x1) * 0.20)
                                    margin_y = int((y2 - y1) * 0.20)
                                    rx = random.randint(x1 + margin_x, x2 - margin_x)
                                    ry = random.randint(y1 + margin_y, y2 - margin_y)
                                    return (rx, ry)
                                else:
                                    return ((x1 + x2) // 2, (y1 + y2) // 2)
            except Exception as e:
                print(f"[{self.device_id}] Ошибка чтения через Companion APK: {e}. Fallback на uiautomator dump...")

        # 2. Медленный путь: uiautomator dump через ADB
        xml_device_path = f"/sdcard/window_dump_{self.device_id}.xml"
        xml_local_path = os.path.join(os.path.dirname(__file__), f"dump_{self.device_id}.xml")
        
        # Сброс старого локального файла, если остался
        if os.path.exists(xml_local_path):
            try:
                os.remove(xml_local_path)
            except OSError:
                pass

        # Делаем дамп на телефоне
        self.run_shell(f"uiautomator dump {xml_device_path}")

        
        # Скачиваем на ПК
        stdout, stderr = self.run_adb(["pull", xml_device_path, xml_local_path])
        if "error" in stderr.lower() or not os.path.exists(xml_local_path):
            # Попробуем альтернативный дамп (иногда путь по умолчанию /sdcard/window_dump.xml)
            self.run_shell("uiautomator dump")
            self.run_adb(["pull", "/sdcard/window_dump.xml", xml_local_path])
            self.run_shell("rm /sdcard/window_dump.xml")

        # Удаляем файл с телефона
        self.run_shell(f"rm {xml_device_path}")

        if not os.path.exists(xml_local_path):
            return None

        found_coords = None
        try:
            tree = ET.parse(xml_local_path)
            root = tree.getroot()

            # Обход дерева элементов
            for elem in root.iter("node"):
                text = elem.get("text", "")
                res_id = elem.get("resource-id", "")
                desc = elem.get("content-desc", "")
                bounds = elem.get("bounds", "")

                matched = False
                
                # Проверка по тексту
                if text_patterns and any(re.search(pat, text, re.IGNORECASE) for pat in text_patterns):
                    matched = True
                # Проверка по resource-id
                if not matched and res_patterns and any(re.search(pat, res_id, re.IGNORECASE) for pat in res_patterns):
                    matched = True
                # Проверка по content-desc
                if not matched and desc_patterns and any(re.search(pat, desc, re.IGNORECASE) for pat in desc_patterns):
                    matched = True

                if matched and bounds:
                    # Извлекаем bounds вида [x1,y1][x2,y2]
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        if randomize_bounds and (x2 - x1 > 10) and (y2 - y1 > 10):
                            # Случайная точка с отступом 20% от краев кнопки для естественно челокоподобного клика
                            margin_x = int((x2 - x1) * 0.20)
                            margin_y = int((y2 - y1) * 0.20)
                            rx = random.randint(x1 + margin_x, x2 - margin_x)
                            ry = random.randint(y1 + margin_y, y2 - margin_y)
                            found_coords = (rx, ry)
                        else:
                            # Рассчитываем строгий центр элемента
                            found_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                        break

        except Exception as e:
            print(f"[{self.device_id}] Ошибка парсинга XML-дампа: {e}")
        finally:
            # Очистка локального файла
            if os.path.exists(xml_local_path):
                try:
                    os.remove(xml_local_path)
                except OSError:
                    pass

        return found_coords

    def tap_element(self, text_patterns=None, res_patterns=None, desc_patterns=None, fallback_x=None, fallback_y=None):
        """
        Динамически находит элемент на экране через A11Y dump и совершает человекоподобный клик.
        Если элемент не найден, выполняет клик по fallback-координатам (если они переданы).
        """
        coords = self.get_ui_dump_and_find_element(text_patterns, res_patterns, desc_patterns, randomize_bounds=True)
        if coords:
            print(f"[{self.device_id}] Элемент UI динамически найден A11Y по координатам: {coords}. Выполняем клик...")
            self.tap(coords[0], coords[1])
            return True
        elif fallback_x is not None and fallback_y is not None:
            print(f"[{self.device_id}] Элемент UI не найден в дереве A11Y. Использование fallback-координат ({fallback_x}, {fallback_y})...")
            self.tap(fallback_x, fallback_y)
            return False
        else:
            print(f"[{self.device_id}] Элемент UI не найден в дереве A11Y и fallback не задан.")
            return False

