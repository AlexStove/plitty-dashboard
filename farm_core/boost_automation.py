# boost_automation.py
"""
Сценарий автоматизации накрутки для одного устройства.
"""

import time
import random
import config
import threading
from adb_helper import ADBDevice
from automation import scroll_feed_stage, ensure_in_main_feed, get_first_non_pinned_video

def transition_to_target_profile(device, account_name, stop_event):
    """
    Выбирает случайный способ перехода на целевой профиль:
    1. Прямая ссылка (Deep link) - 40%
    2. Поиск по имени пользователя - 30%
    3. Поиск по хэштегу - 30%
    """
    method = random.choices(["url", "search", "hashtag"], weights=[40, 30, 30])[0]
    
    if method == "url":
        print(f"[{device.device_id}] [@{account_name}] Способ перехода: Прямая ссылка (Deep link)...")
        url = f"https://www.tiktok.com/@{account_name}"
        cmd = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-p", device.package_name]
        device.run_adb(cmd)
        time.sleep(5.0)
        return True
        
    elif method == "search":
        print(f"[{device.device_id}] [@{account_name}] Способ перехода: Поиск по имени пользователя...")
        try:
            # Нажатие на иконку поиска (обычно вверху справа: x=91%, y=6%)
            device.tap(int(device.width * 0.91), int(device.height * 0.06))
            time.sleep(2.5)
            
            # Тап по полю ввода
            device.tap(int(device.width * 0.5), int(device.height * 0.06))
            time.sleep(1.0)
            
            # Ввод имени аккаунта
            device.input_text_safe(account_name)
            time.sleep(1.5)
            
            # Отправка нажатия Enter
            device.run_shell("input keyevent 66")
            time.sleep(3.5)
            
            # Переход на вкладку Пользователи
            users_tab = device.get_ui_dump_and_find_element(text_patterns=["пользователи", "users", "cuentas"])
            if users_tab:
                device.tap(*users_tab)
            else:
                device.tap(int(device.width * 0.35), int(device.height * 0.12))
            time.sleep(2.5)
            
            # Выбор первой карточки пользователя
            device.tap(int(device.width * 0.5), int(device.height * 0.22))
            time.sleep(4.0)
            return True
        except Exception as e:
            print(f"[{device.device_id}] [@{account_name}] Ошибка поиска, откат на прямую ссылку: {e}")
            
    elif method == "hashtag":
        print(f"[{device.device_id}] [@{account_name}] Способ перехода: Поиск по хэштегу...")
        try:
            # Нажатие на иконку поиска
            device.tap(int(device.width * 0.91), int(device.height * 0.06))
            time.sleep(2.5)
            
            # Ввод хэштега
            hashtag_query = f"#{account_name}"
            device.tap(int(device.width * 0.5), int(device.height * 0.06))
            time.sleep(1.0)
            device.input_text_safe(hashtag_query)
            time.sleep(1.5)
            device.run_shell("input keyevent 66")
            time.sleep(3.5)
            
            # Клик по первому видео в выдаче хэштегов
            device.tap(int(device.width * 0.25), int(device.height * 0.28))
            time.sleep(4.0)
            
            # Клик по аватару автора в видеоплеере (x=91%, y=48%)
            avatar_btn = device.get_ui_dump_and_find_element(res_patterns=["author_avatar", "avatar_button", "user_avatar"])
            if avatar_btn:
                device.tap(*avatar_btn)
            else:
                device.tap(int(device.width * 0.91), int(device.height * 0.48))
            time.sleep(4.0)
            return True
        except Exception as e:
            print(f"[{device.device_id}] [@{account_name}] Ошибка хэштега, откат на прямую ссылку: {e}")
            
    # Откатный прямой переход
    url = f"https://www.tiktok.com/@{account_name}"
    cmd = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-p", device.package_name]
    device.run_adb(cmd)
    time.sleep(5.0)
    return True

def run_boost_automation(device_id, accounts, stop_event, completed_reps=None):
    """
    Основной поток накрутки для конкретного устройства.
    """
    device = ADBDevice(device_id)
    print(f"[{device_id}] Запуск сценария накрутки.")
    total_completed_reps = 0

    try:
        # 1. Стартовая задержка (рассинхронизация до 30 секунд)
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
        time.sleep(12.0)

        # --- ЭТАП 1: скроллинг рекомендаций (30 секунд) ---
        stage_1_duration = config.STAGE_1_DURATION_SEC
        print(f"[{device_id}] === НАЧАЛО ЭТАПА 1 (Скроллинг рекомендаций {stage_1_duration} сек) ===")
        scroll_feed_stage(device, stage_1_duration, stop_event, like_chance=0, comment_chance=0, enter_profile_chance=0)

        if stop_event.is_set():
            return

        # --- ЭТАП 2: Накрутка на целевых профилях ---
        shuffled_accounts = list(accounts)
        random.shuffle(shuffled_accounts)
        print(f"[{device_id}] === НАЧАЛО ЭТАПА 2 (Накрутка на целевых профилях: {len(shuffled_accounts)} шт) ===")
        print(f"[{device_id}] Порядок обхода аккаунтов: {', '.join(shuffled_accounts)}")
        
        for account_idx, account_name in enumerate(shuffled_accounts, 1):
            if stop_event.is_set():
                return
                
            print(f"[{device_id}] Переход на целевой аккаунт [{account_idx}/{len(shuffled_accounts)}]: @{account_name}...")
            transition_to_target_profile(device, account_name, stop_event)

            # Выбираем случайное число повторений от 10 до 15
            num_reps = random.randint(10, 15)
            print(f"[{device_id}] [@{account_name}] Выбрано количество повторений: {num_reps}")

            # Определение координат видео с повторными попытками для медленной сети
            video_coords = None
            for attempt in range(1, 6):
                print(f"[{device_id}] [@{account_name}] Поиск первого видео (попытка {attempt}/5)...")
                video_coords = get_first_non_pinned_video(device)
                if video_coords:
                    break
                time.sleep(2.0)

            # Если после 5 попыток всё еще не нашли, переоткрываем URL (для зависших страниц)
            if not video_coords:
                print(f"[{device_id}] [@{account_name}] Видео не найдено. Пробуем переоткрыть профиль...")
                device.run_adb(cmd)
                time.sleep(4.0)
                video_coords = get_first_non_pinned_video(device)

            if not video_coords:
                fallback_x = int(device.width * 0.18)
                fallback_y = int(device.height * 0.55)
                video_coords = (fallback_x, fallback_y)
                print(f"[{device_id}] [@{account_name}] Видео всё еще не найдено. Используем fallback: {video_coords}")
            else:
                print(f"[{device_id}] [@{account_name}] Видео найдено по координатам: {video_coords}")

            # Открываем первое видео (кликаем дважды с небольшой паузой для надежности)
            print(f"[{device_id}] [@{account_name}] Открытие первого видео...")
            device.tap(*video_coords)
            time.sleep(1.0)
            device.tap(*video_coords) # Повторный клик на случай лага тача
            time.sleep(3.0) # Ждем 3 секунды загрузки видеоплеера

            # Первоначальный просмотр первого видео
            watch_time = random.uniform(0.8, 1.2)
            print(f"[{device_id}] [@{account_name}] Первоначальный просмотр видео 1 ({watch_time:.1f} сек)...")
            time.sleep(watch_time)

            # Выполняем цикл из num_reps повторений (кругов)
            for rep in range(1, num_reps + 1):
                if stop_event.is_set():
                    return

                # Свайп вниз ко 2-му видео (рандомизированный по траектории и времени)
                print(f"[{device_id}] [@{account_name}] Повторение {rep}/{num_reps}: свайп вниз ко 2-му видео...")
                x_start = (device.width // 2) + random.randint(-5, 5)
                x_end = (device.width // 2) + random.randint(-5, 5)
                y_start = int(device.height * 0.75) + random.randint(-10, 10)
                y_end = int(device.height * 0.25) + random.randint(-10, 10)
                swipe_duration = random.randint(190, 270)
                device.swipe(x_start, y_start, x_end, y_end, duration_ms=swipe_duration)
                
                # Объединенное ожидание загрузки + просмотр (0.8 - 1.2 сек)
                watch_time = random.uniform(0.8, 1.2)
                print(f"[{device_id}] [@{account_name}] Повторение {rep}/{num_reps}: просмотр видео 2 ({watch_time:.1f} сек)...")
                time.sleep(watch_time)

                if stop_event.is_set():
                    return

                # Свайп вверх к 1-му видео (рандомизированный по траектории и времени)
                print(f"[{device_id}] [@{account_name}] Повторение {rep}/{num_reps}: свайп вверх к 1-му видео...")
                x_start_up = (device.width // 2) + random.randint(-5, 5)
                x_end_up = (device.width // 2) + random.randint(-5, 5)
                y_start_up = int(device.height * 0.25) + random.randint(-10, 10)
                y_end_up = int(device.height * 0.75) + random.randint(-10, 10)
                swipe_duration = random.randint(190, 270)
                device.swipe(x_start_up, y_start_up, x_end_up, y_end_up, duration_ms=swipe_duration)
                
                # Объединенное ожидание загрузки + просмотр (0.8 - 1.2 сек)
                watch_time = random.uniform(0.8, 1.2)
                print(f"[{device_id}] [@{account_name}] Повторение {rep}/{num_reps}: просмотр видео 1 ({watch_time:.1f} сек)...")
                time.sleep(watch_time)

                total_completed_reps += 1

            # Очистка состояния и возврат в ленту рекомендаций
            print(f"[{device_id}] [@{account_name}] Все круги завершены. Сброс состояния...")
            device.start_tiktok()
            time.sleep(12.0)
            ensure_in_main_feed(device, force=True)

        print(f"[{device_id}] Сценарий накрутки успешно завершен.")

    except Exception as e:
        print(f"[{device_id}] Ошибка сценария накрутки: {e}")
    finally:
        # Финал: переходим на собственный профиль в TikTok и оставляем открытым
        print(f"[{device_id}] Финал. Переход на собственный профиль в TikTok...")
        try:
            profile_tab = device.get_ui_dump_and_find_element(
                text_patterns=["профиль", "profile", "я", "me"],
                res_patterns=[r"tab_text$", r"profile_tab"]
            )
            if profile_tab:
                device.tap(*profile_tab)
            else:
                device.tap(int(device.width * 0.90), int(device.height * 0.96))
            time.sleep(2.0)
            print(f"[{device_id}] Устройство переведено на вкладку 'Профиль' TikTok и оставлено открытым!")
        except Exception as e_prof:
            print(f"[{device_id}] Ошибка перехода на профиль: {e_prof}")
        if completed_reps is not None:
            completed_reps[device_id] = total_completed_reps
