# automation.py
"""
Модуль, содержащий основную логику автоматизации для одного устройства.
Управляет жизненным циклом сессии просмотра TikTok на телефоне.
"""

import time
import random
import config
import threading
import os
import re
import xml.etree.ElementTree as ET
from adb_helper import ADBDevice

def ensure_comments_closed(device):
    """
    Гарантированно закрывает открытые клавиатуры, шторки комментариев, оверлеи Поделиться и поиск.
    """
    try:
        # 1. Если открыта клавиатура — скрываем
        if device.is_keyboard_open():
            device.press_back()
            time.sleep(0.5)
        # 2. Тапаем в верхнюю часть экрана (y=15%), чтобы сбросить открытую шторку комментариев
        device.tap(device.width // 2, int(device.height * 0.15))
        time.sleep(0.3)
    except Exception:
        pass

def dismiss_popups(device):
    """
    Автоматически закрывает назойливые всплывающие окна и диалоги TikTok.
    """
    popup_btn = device.get_ui_dump_and_find_element(
        text_patterns=[
            "don't allow", "don’t allow", "not now", "не разрешать", 
            "не сейчас", "позже", "пропустить", "skip", "cancel", "отмена", 
            "dismiss", "close", "закрыть"
        ],
        res_patterns=[r"btn_dismiss$", r"tv_dismiss$", r"cancel_button$"]
    )
    if popup_btn:
        print(f"[{device.device_id}] [Popup Handler] Найдено и автоматически закрыто всплывающее окно...")
        device.tap(*popup_btn)
        time.sleep(1.0)
        return True
    return False

def ensure_in_main_feed(device, force=False):
    """
    Guarantees the device is in the main recommendations feed.
    """
    device.ensure_tiktok_foreground()
    
    if not hasattr(device, "_feed_check_counter"):
        device._feed_check_counter = 0
    device._feed_check_counter += 1
    
    if not force and device._feed_check_counter % 25 != 1:
        return
        
    dismiss_popups(device)
    
    # Try up to 2 times to find main feed before relaunching
    for check_attempt in range(2):
        is_main = device.get_ui_dump_and_find_element(
            text_patterns=["главная", "home", "для вас", "for you", "inicio", "início", "para ti", "para você", "para voce"],
            res_patterns=["tab_home", "home_tab"]
        )
        if is_main:
            return
        
        if check_attempt < 1:
            time.sleep(2.0)
            
    print(f"[{device.device_id}] Out of main feed after retries. Relaunching to reset...")
    device.start_tiktok()
    time.sleep(10.0)

def is_live_stream(device):
    """
    Проверяет, является ли текущее видео трансляцией (LIVE).
    Ищет специфичные для стрима маркеры в XML-дампе, игнорируя текстовые поля описания.
    """
    xml_device_path = f"/sdcard/window_dump_live_{device.device_id}.xml"
    xml_local_path = os.path.join(os.path.dirname(__file__), f"dump_live_{device.device_id}.xml")
    
    if os.path.exists(xml_local_path):
        try:
            os.remove(xml_local_path)
        except OSError:
            pass

    device.run_shell(f"uiautomator dump {xml_device_path}")
    stdout, stderr = device.run_adb(["pull", xml_device_path, xml_local_path])
    if "error" in stderr.lower() or not os.path.exists(xml_local_path):
        device.run_shell("uiautomator dump")
        device.run_adb(["pull", "/sdcard/window_dump.xml", xml_local_path])
        device.run_shell("rm /sdcard/window_dump.xml")
    device.run_shell(f"rm {xml_device_path}")

    if not os.path.exists(xml_local_path):
        return False

    is_live = False
    try:
        import xml.etree.ElementTree as ET
        import re
        tree = ET.parse(xml_local_path)
        root = tree.getroot()
        
        # Регулярки для точного поиска
        live_res_pat = re.compile(
            r"live_room|live_play|live_viewer|live_lbl|live_title|live_chat|live_container|"
            r"live_message|live_bottom_right|live_btn|live_icon|live_view|live_gift|live_interact|"
            r"live_header|live_profile|live_gift_panel|rose_button|gift_button|btn_live|live_bottom_bar|"
            r"live_audience_layout|live_ad_layout|multi_guest|coplay", 
            re.IGNORECASE
        )
        
        # Специфические фразы (ищем полное совпадение или ключевые слова)
        live_text_pat = re.compile(
            r"^LIVE$|^Стрим$|^Ao vivo$|^En vivo$|^Directo$|^в эфире$|^трансляция$|^зрителей$|^эфир$|"
            r"поделиться трансляцией|отправить розу|роза|подарить|подарки|подарок|"
            r"совещание|соведущий|подписка на автора",
            re.IGNORECASE
        )

        for elem in root.iter("node"):
            res_id = elem.get("resource-id", "")
            text = elem.get("text", "")
            desc = elem.get("content-desc", "")
            
            # Пропускаем описания, хештеги и имя пользователя, чтобы исключить ложные срабатывания
            if any(k in res_id.lower() for k in ["desc", "title", "username", "user_name", "caption"]):
                continue
                
            if live_res_pat.search(res_id):
                is_live = True
                break
                
            if live_text_pat.search(text) or live_text_pat.search(desc):
                is_live = True
                break
                
    except Exception as e:
        print(f"[{device.device_id}] Ошибка при детальном анализе LIVE-стрима: {e}")
    finally:
        if os.path.exists(xml_local_path):
            try:
                os.remove(xml_local_path)
            except OSError:
                pass
                
    return is_live

def get_first_non_pinned_video(device):
    """
    Downloads UI dump and finds the first video card coordinate that does NOT contain a 'Pinned' or 'Закреплено' label.
    """
    xml_device_path = f"/sdcard/window_dump_{device.device_id}.xml"
    xml_local_path = os.path.join(os.path.dirname(__file__), f"dump_profile_{device.device_id}.xml")
    
    if os.path.exists(xml_local_path):
        try:
            os.remove(xml_local_path)
        except OSError:
            pass

    device.run_shell(f"uiautomator dump {xml_device_path}")
    stdout, stderr = device.run_adb(["pull", xml_device_path, xml_local_path])
    if "error" in stderr.lower() or not os.path.exists(xml_local_path):
        device.run_shell("uiautomator dump")
        device.run_adb(["pull", "/sdcard/window_dump.xml", xml_local_path])
        device.run_shell("rm /sdcard/window_dump.xml")

    device.run_shell(f"rm {xml_device_path}")

    if not os.path.exists(xml_local_path):
        return None

    try:
        tree = ET.parse(xml_local_path)
        root = tree.getroot()
        
        video_nodes = []
        for elem in root.iter("node"):
            res_id = elem.get("resource-id", "")
            bounds = elem.get("bounds", "")
            if bounds and any(pat in res_id for pat in ["cover", "grid", "post", "aweme_card"]):
                video_nodes.append(elem)

        for elem in video_nodes:
            is_pinned = False
            for child in elem.iter("node"):
                text = child.get("text", "")
                res_id = child.get("resource-id", "")
                desc = child.get("content-desc", "")
                if (any(pat in text.lower() for pat in ["pinned", "закреплено", "закрепленные"]) or
                        any(pat in desc.lower() for pat in ["pinned", "закреплено", "закрепленные"]) or
                        "pin_icon" in res_id or "pinned_tag" in res_id):
                    is_pinned = True
                    break
            
            if not is_pinned:
                bounds = elem.get("bounds", "")
                m = re.findall(r"\d+", bounds)
                if len(m) == 4:
                    x1, y1, x2, y2 = map(int, m)
                    return (x1 + x2) // 2, (y1 + y2) // 2

        if video_nodes:
            bounds = video_nodes[0].get("bounds", "")
            m = re.findall(r"\d+", bounds)
            if len(m) == 4:
                x1, y1, x2, y2 = map(int, m)
                return (x1 + x2) // 2, (y1 + y2) // 2

    except Exception as e:
        print(f"[{device.device_id}] Error parsing profile dump for pinned check: {e}")
    finally:
        if os.path.exists(xml_local_path):
            try:
                os.remove(xml_local_path)
            except OSError:
                pass
                
    return None

def watch_random_profile(device):
    """
    Goes to the author profile and watches 2-4 videos, then returns to feed.
    """
    if is_live_stream(device):
        print(f"[{device.device_id}] LIVE stream detected. Aborting profile entry.")
        return

    print(f"[{device.device_id}] >>> Вход в профиль автора видео (свайп влево)...")
    device.swipe_left()
    time.sleep(4.0) # wait for profile to load

    # Клик по первому не-закрепленному видео в профиле
    video_coords = get_first_non_pinned_video(device)
    
    if video_coords:
        print(f"[{device.device_id}] Первое видео в профиле найдено по координатам: {video_coords}")
        device.tap(*video_coords)
    else:
        fallback_x = int(device.width * 0.18)
        fallback_y = int(device.height * 0.55)
        print(f"[{device.device_id}] Видео не найдено. Используем fallback клик: {fallback_x}, {fallback_y}")
        device.tap(fallback_x, fallback_y)
        
    time.sleep(2.5) # Ждем загрузки видеоплеера

    # Просмотр 2-4 видео
    num_videos = random.randint(config.RANDOM_PROFILE_VIDEOS_MIN, config.RANDOM_PROFILE_VIDEOS_MAX)
    print(f"[{device.device_id}] Будет просмотрено {num_videos} видео в профиле.")

    for i in range(num_videos):
        watch_time = random.uniform(config.RANDOM_PROFILE_VIDEO_WATCH_MIN, config.RANDOM_PROFILE_VIDEO_WATCH_MAX)
        print(f"[{device.device_id}] Просмотр видео {i+1}/{num_videos} в течение {watch_time:.1f} сек...")
        time.sleep(watch_time)

        # Свайп вверх к следующему видео (если это не последнее видео)
        if i < num_videos - 1:
            x = device.width // 2
            y_start = int(device.height * 0.75)
            y_end = int(device.height * 0.25)
            device.swipe(x, y_start, x, y_end, duration_ms=300)
            time.sleep(2.0)

    # Возврат в основную ленту
    print(f"[{device.device_id}] Возврат из профиля в ленту рекомендаций...")
    device.press_back() # Назад из видеоплеера в профиль
    time.sleep(1.5)
    device.press_back() # Назад из профиля в ленту
    time.sleep(1.5)
    ensure_in_main_feed(device, force=True)


def follow_user(device):
    """
    Пытается подписаться на открытый аккаунт, если еще не подписан.
    """
    print(f"[{device.device_id}] Попытка подписки на аккаунт...")
    
    # 1. Поиск кнопки подписки ("Подписаться", "Follow", "Подписаться в ответ")
    follow_coords = device.get_ui_dump_and_find_element(
        text_patterns=[r"^подписаться$", r"^follow$", r"^подписаться в ответ$", r"^seguir$", r"^seguir de volta$", r"^seguir también$", r"^seguir tambien$"],
        res_patterns=["follow_btn", "btn_follow", "follow_button", "profile_follow"]
    )
    
    if follow_coords:
        print(f"[{device.device_id}] Найдена кнопка подписки: {follow_coords}. Нажимаем...")
        device.tap(*follow_coords)
        time.sleep(1.5)
        return

    # 2. Проверка, подписаны ли мы уже ("Сообщение", "Message", "Вы подписаны", "Following", "Друзья", "Friends")
    already_following = device.get_ui_dump_and_find_element(
        text_patterns=[r"^сообщение$", r"^message$", r"^вы подписаны$", r"^following$", r"^друзья$", r"^friends$", r"^mensaje$", r"^mensagem$", r"^siguiendo$", r"^seguindo$", r"^amigos$"]
    )
    
    if already_following:
        print(f"[{device.device_id}] Уже подписаны на этот аккаунт.")
    else:
        # Fallback клик (кнопка подписки обычно находится по центру экрана под шапкой профиля)
        fallback_x = int(device.width * 0.5)
        fallback_y = int(device.height * 0.28) # Примерно y=28% высоты
        print(f"[{device.device_id}] Кнопка подписки не распознана. Пробуем fallback клик: {fallback_x}, {fallback_y}")
        device.tap(fallback_x, fallback_y)
        time.sleep(1.5)


def leave_text_comment(device, comment_text):
    """
    Оставляет текстовый комментарий под видео.
    """
    device.ensure_tiktok_foreground()
    print(f"[{device.device_id}] Оставляем комментарий: '{comment_text}'...")
    
    # 1. Открытие комментариев
    comment_btn = device.get_ui_dump_and_find_element(
        res_patterns=["comment", "btn_comment", "comment_button", "comment_count", "icon_comment", "comment_icon"],
        desc_patterns=["comment", "комментари", "обсудить", "comentario", "comentarios", "comentário", "comentários"]
    )
    if comment_btn:
        print(f"[{device.device_id}] Found comments button: {comment_btn}. Tapping...")
        device.tap(*comment_btn)
    else:
        print(f"[{device.device_id}] Comments button not found in UI dump. Tapping y=70% coordinates...")
        device.tap(int(device.width * 0.92), int(device.height * 0.70))
    time.sleep(3.0)

    # Проверяем, открылась ли панель комментариев
    is_open = device.get_ui_dump_and_find_element(
        res_patterns=[r"/e9u$", r"/a7s$", "comment_input", "input_comment", "comment_edit_text", "edit_text"],
        desc_patterns=["close", "закрыть", "comentarios", "comments", "fechar", "comentario", "comentário", "comentários"]
    )
    if not is_open:
        print(f"[{device.device_id}] Comments panel not open. Tapping y=72%...")
        device.tap(int(device.width * 0.92), int(device.height * 0.72))
        time.sleep(3.0)
        is_open = device.get_ui_dump_and_find_element(
            res_patterns=[r"/e9u$", r"/a7s$", "comment_input", "input_comment", "comment_edit_text", "edit_text"],
            desc_patterns=["close", "закрыть", "comentarios", "comments", "fechar", "comentario", "comentário", "comentários"]
        )
        if not is_open:
            print(f"[{device.device_id}] Still not open. Tapping old fallback y=62%...")
            device.tap(int(device.width * 0.92), int(device.height * 0.62))
            time.sleep(3.0)
            is_open = device.get_ui_dump_and_find_element(
                res_patterns=[r"/e9u$", r"/a7s$", "comment_input", "input_comment", "comment_edit_text", "edit_text"],
                desc_patterns=["close", "закрыть", "comentarios", "comments", "fechar", "comentario", "comentário", "comentários"]
            )
            if not is_open:
                print(f"[{device.device_id}] [ВНИМАНИЕ] Не удалось открыть панель комментариев. Пропускаем.")
                return False

    # 2. Клик по полю ввода
    input_field_y = None
    input_field = device.get_ui_dump_and_find_element(
        res_patterns=["comment_input", "input_comment", "comment_edit_text", "edit_text", r"/e9u$"],
        text_patterns=["оставьте комментарий", "добавить комментарий", "add comment", "leave a comment", "añadir comentario", "deja un comentario", "adicionar comentário", "adicionar comentario", "deixe um comentário", "deixe um comentario", "comentar", "comente"]
    )
    if input_field:
        input_field_y = input_field[1]
        device.tap(*input_field)
    else:
        input_field_y = int(device.height * 0.46)
        device.tap(int(device.width * 0.35), int(device.height * 0.96))
    time.sleep(2.0)

    # Очищаем текст от любых не-ASCII символов, чтобы клавиатура/ADB не генерировали мусорные символы
    clean_text = "".join(c for c in comment_text if ord(c) < 128)
    clean_text = " ".join(clean_text.split())

    # 3. Ввод текста комментария
    print(f"[{device.device_id}] Ввод текста: '{clean_text}'...")
    try:
        from brain import human_gestures as hg
        hg.type(device.device_id, clean_text)
    except Exception as e:
        print(f"[{device.device_id}] human_gestures.type error: {e}. Falling back to input_text_safe.")
        device.input_text_safe(clean_text)
    time.sleep(1.5)

    # 4. Открываем панель эмодзи TikTok и вставляем смайлик/стикер
    try:
        device.comment_emoji()
    except Exception as e:
        print(f"[{device.device_id}] Ошибка при добавлении эмодзи: {e}")
    time.sleep(1.5)

    # 5. Скрываем клавиатуру Gboard кнопкой Back (только если она открыта!)
    if device.is_keyboard_open():
        print(f"[{device.device_id}] Клавиатура открыта. Скрываем (нажатие Back)...")
        device.press_back()
        time.sleep(2.0) # Даем клавиатуре полностью закрыться, а кнопке «Отправить» опуститься вниз

    # 6. Нажатие кнопки «Отправить» (красный кружок со стрелочкой вверх)
    print(f"[{device.device_id}] Нажатие кнопки Отправить...")
    send_btn = device.get_ui_dump_and_find_element(
        res_patterns=["send", "publish", "post", "comment_post", "button_send", "btn_send", r"/e9z$"],
        desc_patterns=["send", "отправить", "enviar", "publicar", "post comment"]
    )
    if send_btn:
        print(f"[{device.device_id}] Found Send button in UI: {send_btn}. Tapping it...")
        device.tap(*send_btn)
    else:
        if device.is_keyboard_open():
            print(f"[{device.device_id}] Keyboard is open. Tapping Send at y=54%...")
            device.tap(int(device.width * 0.90), int(device.height * 0.54))
        else:
            print(f"[{device.device_id}] Keyboard is closed. Tapping Send at y=91%...")
            device.tap(int(device.width * 0.90), int(device.height * 0.91))
    time.sleep(2.5)

    # 7. Закрываем панель комментариев (только если она всё еще открыта!)
    is_comments_open = device.get_ui_dump_and_find_element(
        res_patterns=[r"/e9u$", r"/a7s$", "comment_input", "input_comment", "comment_edit_text", "edit_text"],
        desc_patterns=["close", "закрыть", "comentarios", "comments", "fechar", "comentario", "comentário", "comentários"]
    )
    if is_comments_open:
        print(f"[{device.device_id}] Закрытие панели комментариев...")
        # Try to find and click the close 'X' button
        close_btn = device.get_ui_dump_and_find_element(
            res_patterns=["close", "btn_close", "close_btn", "comment_close"],
            desc_patterns=["close", "закрыть", "cerrar", "clear", "cancel", "x", "fechar"]
        )
        if close_btn:
            print(f"[{device.device_id}] Found close button at {close_btn}. Tapping it...")
            device.tap(*close_btn)
            time.sleep(1.5)
        else:
            # Fallback: tap outside the comments panel (y=20%)
            print(f"[{device.device_id}] Close button not found. Tapping outside panel (y=20%)...")
            device.tap(device.width // 2, int(device.height * 0.20))
            time.sleep(1.5)
            # Try back keyevent as double insurance
            device.press_back()
            time.sleep(1.5)
    return True


def simulate_share_copy_link(device):
    """
    Имитирует репост путем нажатия на кнопку "Поделиться" и копирования ссылки.
    """
    print(f"[{device.device_id}] [Поведенческий фактор] Имитация репоста (копирование ссылки)...")
    try:
        # Клик по кнопке "Поделиться" (обычно внизу справа, стрелка)
        share_btn = device.get_ui_dump_and_find_element(
            res_patterns=["share_button", "share_btn", r"share$", r"/aw4$", r"/b7p$"]
        )
        if share_btn:
            device.tap(*share_btn)
        else:
            # Fallback координаты кнопки поделиться
            device.tap(int(device.width * 0.92), int(device.height * 0.81))
            
        time.sleep(3.0) # Ждем открытия панели "Поделиться"
        
        # Клик по кнопке "Копировать ссылку" (Copy Link)
        copy_link_btn = device.get_ui_dump_and_find_element(
            res_patterns=["copy_link", "link_copy", r"copy_link_button", r"/f7o$", r"/b2o$"],
            text_patterns=["копировать ссылку", "copy link", "copiar enlace", "copiar link"]
        )
        if copy_link_btn:
            device.tap(*copy_link_btn)
        else:
            # Fallback: первая кнопка в нижнем горизонтальном списке панели "Поделиться"
            fallback_x = int(device.width * 0.15)
            fallback_y = int(device.height * 0.80)
            device.tap(fallback_x, fallback_y)
            
        time.sleep(2.0) # Ждем копирования
    except Exception as e:
        print(f"[{device.device_id}] Ошибка при имитации репоста: {e}")
    finally:
        ensure_comments_closed(device)


def watch_and_interact_on_video(device, watch_time, like_chance, comment_chance, stop_event):
    """
    Watches current video for watch_time and likes/comments with specified chances.
    """
    if is_live_stream(device):
        print(f"[{device.device_id}] LIVE stream detected before watch! Skipping immediately...")
        return "LIVE_STREAM"

    print(f"[{device.device_id}] Просмотр видео в течение {watch_time:.1f} сек...")
    
    # Safe wait checking for interruptions
    watch_start = time.time()
    while time.time() - watch_start < watch_time:
        if stop_event.is_set():
            return False
        time.sleep(0.5)

    if is_live_stream(device):
        print(f"[{device.device_id}] LIVE stream detected before interaction! Skipping...")
        return "LIVE_STREAM"

    # Like (like_chance)
    if random.random() < like_chance:
        print(f"[{device.device_id}] Сработал шанс {like_chance*100}% лайка! Ставим лайк (двойной тап)...")
        device.double_tap(device.width // 2, device.height // 2)
        time.sleep(1.0)

    # Comment (comment_chance)
    if random.random() < comment_chance:
        comment_text = random.choice(config.COMMENT_POOL)
        try:
            leave_text_comment(device, comment_text)
        except Exception as e:
            print(f"[{device.device_id}] Не удалось оставить комментарий: {e}")
            device.press_back()
            time.sleep(1.0)
            
    # Reading comments: only trigger if comment_chance > 0.05
    if comment_chance > 0.05 and random.random() < 0.15:
        try:
            # Try to open comments
            print(f"[{device.device_id}] [Поведенческий фактор] Открываем комментарии для чтения...")
            comments_btn = device.get_ui_dump_and_find_element(
                res_patterns=["comment_button", "comment_count", "comment_icon", r"/e9u$"],
                desc_patterns=["comments", "комментарии", "comentarios", "comentários"]
            )
            if comments_btn:
                device.tap(*comments_btn)
            else:
                # Fallback tap on comments icon position (usually right side, around x=92%, y=62%)
                device.tap(int(device.width * 0.92), int(device.height * 0.62))
                
            time.sleep(2.5)
            
            # If keyboard is open, hide it
            if device.is_keyboard_open():
                device.press_back()
                time.sleep(1.0)
                
            # Scroll comments a bit (1-2 times)
            for _ in range(random.randint(1, 2)):
                if stop_event.is_set():
                    break
                x_comm = int(device.width * 0.5)
                y_start_comm = int(device.height * 0.8)
                y_end_comm = int(device.height * 0.4)
                device.swipe(x_comm, y_start_comm, x_comm, y_end_comm, duration_ms=400)
                time.sleep(random.uniform(2.0, 4.0)) # Pause to "read"
                
            # Wait a bit more
            time.sleep(random.uniform(2.0, 5.0))
            
            # Close comments
            print(f"[{device.device_id}] [Поведенческий фактор] Закрываем комментарии...")
            ensure_comments_closed(device)
        except Exception as e:
            print(f"[{device.device_id}] [Поведенческий фактор] Ошибка при чтении комментариев: {e}")
            ensure_comments_closed(device)
            
    # Имитация репостов (Копирование ссылки — Share): 3% шанс
    if comment_chance > 0.05 and random.random() < 0.03:
        try:
            simulate_share_copy_link(device)
        except Exception as e:
            print(f"[{device.device_id}] Ошибка при вызове репоста: {e}")
            ensure_comments_closed(device)
            
    return True


def scroll_feed_stage(device, duration_sec, stop_event, like_chance, comment_chance, enter_profile_chance=None):
    """
    Выполняет скроллинг ленты рекомендаций в течение заданного времени (в секундах).
    """
    ep_chance = enter_profile_chance if enter_profile_chance is not None else config.ENTER_PROFILE_CHANCE
    stage_start_time = time.time()
    
    while not stop_event.is_set():
        ensure_in_main_feed(device)
        # Check time limit of current stage
        elapsed_stage = time.time() - stage_start_time
        if elapsed_stage >= duration_sec:
            print(f"[{device.device_id}] Этап скроллинга завершен (прошло {elapsed_stage:.1f}/{duration_sec} сек).")
            break

        # 1. Быстрый четкий ADB свайп снизу вверх (100% надежный переход, 0% задержек)
        x = device.width // 2
        y_start = int(device.height * 0.75)
        y_end = int(device.height * 0.25)
        scroll_dur = random.randint(220, 320)
        device.swipe(x, y_start, x, y_end, duration_ms=scroll_dur)
        time.sleep(1.0)

        # 2. Время просмотра видео: от 3 до 20 секунд
        watch_time = random.uniform(config.WATCH_MIN_SEC, config.WATCH_MAX_SEC)
        
        success = watch_and_interact_on_video(device, watch_time, like_chance, comment_chance, stop_event)
        if not success:
            return
        if success == "LIVE_STREAM":
            continue

        # 3. Случайный переход в профиль автора
        if random.random() < ep_chance:
            watch_random_profile(device)
            continue

        # 4. Случайная небольшая пауза перед следующим скроллом
        pause_dur = random.uniform(config.PAUSE_MIN_SEC, config.PAUSE_MAX_SEC)
        time.sleep(pause_dur)


def transition_to_target_profile_via_search(device, account_name):
    """
    Выполняет переход на целевой профиль через глобальный поиск TikTok.
    Имитирует ручной ввод имени пользователя с клавиатуры.
    """
    print(f"[{device.device_id}] [@{account_name}] Переход на целевой аккаунт через ПОИСК...")
    
    # 1. Нажатие на иконку поиска (обычно вверху справа: x=91%, y=6%)
    device.tap(int(device.width * 0.91), int(device.height * 0.06))
    time.sleep(2.5)
    
    # 2. Тап по полю ввода
    device.tap(int(device.width * 0.5), int(device.height * 0.06))
    time.sleep(1.0)
    
    # 3. Ввод имени аккаунта с имитацией клавиатуры
    print(f"[{device.device_id}] [@{account_name}] Вводим имя аккаунта в строку поиска...")
    device.input_text_safe(account_name)
    time.sleep(1.5)
    
    # 4. Отправка нажатия Enter (keycode 66)
    device.run_shell("input keyevent 66")
    time.sleep(3.5)
    
    # 5. Переход на вкладку "Пользователи"
    users_tab = device.get_ui_dump_and_find_element(
        text_patterns=["пользователи", "users", "cuentas", "comunidades"],
        res_patterns=[r"tab_text$"]
    )
    if users_tab:
        device.tap(*users_tab)
    else:
        # Fallback на вкладку "Пользователи" (вторая вкладка слева, обычно x=35%, y=12%)
        device.tap(int(device.width * 0.35), int(device.height * 0.12))
    time.sleep(2.5)
    
    # 6. Клик по первой карточке пользователя в списке (обычно x=50%, y=22%)
    device.tap(int(device.width * 0.5), int(device.height * 0.22))
    time.sleep(4.0)
    
    # Закрываем клавиатуру, если она осталась открытой
    if device.is_keyboard_open():
        device.press_back()
        time.sleep(1.0)


def go_to_profile_robust(device):
    """
    Надежно переводит телефон на страницу Профиль в TikTok с закрытием оверлеев и повторными попытками.
    """
    try:
        # 1. Двойное прожатие Back для гарантированного сброса шторок, комментариев и баннеров
        device.press_back()
        time.sleep(0.5)
        device.press_back()
        time.sleep(0.5)
        
        # 2. Тап в верхнюю область для гарантированного снятия оверлеев
        device.tap(device.width // 2, int(device.height * 0.15))
        time.sleep(0.5)
        
        # 3. Двойной тап точно по кнопке "Профиль" в правом нижнем углу (x=90%, y=96%)
        device.tap(int(device.width * 0.90), int(device.height * 0.96))
        time.sleep(1.0)
        device.tap(int(device.width * 0.90), int(device.height * 0.96))
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[{device.device_id}] Ошибка перехода на профиль: {e}")
        # Fallback клик
        device.tap(int(device.width * 0.90), int(device.height * 0.96))
        return False

def run_device_automation(device_id, stop_event):
    """
    Основной поток автоматизации для конкретного устройства.
    """
    device = ADBDevice(device_id)
    print(f"[{device_id}] Запуск автоматизации.")

    try:
        # 1. Случайная стартовая задержка (включение всех за первые 30 секунд)
        stagger_delay = random.uniform(config.INITIAL_STAGGER_MIN_SEC, config.INITIAL_STAGGER_MAX_SEC)
        print(f"[{device_id}] Рассинхронизация старта. Ожидание {stagger_delay:.1f} сек...")
        time.sleep(stagger_delay)

        if stop_event.is_set():
            return

        # 2. Очистка кэша TikTok для маскировки
        print(f"[{device_id}] Очистка кэша TikTok...")
        device.run_shell(f"rm -rf /sdcard/Android/data/{device.package_name}/cache")
        device.run_shell(f"rm -rf /data/data/{device.package_name}/cache")

        # 3. Запуск TikTok
        device.start_tiktok()
        ensure_in_main_feed(device, force=True)

        # --- ЭТАП 1: Первичный скроллинг рекомендаций (без лайков, комментов и заходов в профили, от 4 до 6 минут) ---
        stage_1_duration = random.uniform(config.STAGE_1_DURATION_MIN, config.STAGE_1_DURATION_MAX)
        print(f"[{device_id}] === НАЧАЛО ЭТАПА 1 (Скроллинг ленты {stage_1_duration:.1f} сек без реакций) ===")
        scroll_feed_stage(device, stage_1_duration, stop_event, like_chance=0.02, comment_chance=0.0, enter_profile_chance=0.0)

        if stop_event.is_set():
            return

        # --- STAGE 2: Transitions to random accounts ---
        if getattr(config, 'SKIP_STAGE_2', False):
            print(f"[{device_id}] === ЭТАП 2 ПРОПУЩЕН (по запросу: работаем только по 1 и 3 этапам) ===")
        else:
            run_stage_2(device, stop_event)

        if stop_event.is_set():
            return

        # --- STAGE 3: Final recommendations feed scroll ---
        stage_3_dur = random.uniform(config.STAGE_3_DURATION_MIN, config.STAGE_3_DURATION_MAX)
        print(f"[{device_id}] === НАЧАЛО ЭТАПА 3 (Скроллинг {stage_3_dur:.1f} сек) ===")
        scroll_feed_stage(device, stage_3_dur, stop_event, config.LIKE_CHANCE, config.COMMENT_CHANCE)

        print(f"[{device_id}] Скрипт автоматизации успешно завершен.")

    except Exception as e:
        print(f"[{device_id}] [ОШИБКА] Произошел сбой: {e}")
    finally:
        # Финал: переходим на собственный профиль в TikTok и оставляем открытым (не выходим на рабочий стол)
        print(f"[{device_id}] Финал. Переход на собственный профиль в TikTok...")
        go_to_profile_robust(device)
        print(f"[{device_id}] Устройство переведено на вкладку 'Профиль' TikTok и оставлено открытым!")


