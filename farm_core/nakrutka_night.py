# nakrutka_night.py
"""
Главная точка входа для запуска ночной накрутки на нескольких устройствах.
Выполняет 5 кругов накрутки с паузой 15 минут (на главном экране) между ними.
"""

import threading
import time
import sys
import config
from adb_helper import get_devices_with_lock_status, ADBDevice
from boost_automation import run_boost_automation

# Настройка UTF-8 для корректного вывода эмодзи в консоли Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    print("=" * 60)
    print("Запуск системы автоматизации TikTok (НОЧНАЯ НАКРУТКА - 5 КРУГОВ)")
    print("=" * 60)
    
    # 1. Считывание аккаунтов из аргументов командной строки
    accounts = sys.argv[1:]
    if not accounts:
        print("[!] Ошибка: не указаны аккаунты для накрутки!")
        print("[*] Использование: python nakrutka_night.py account1 account2 ...")
        sys.exit(1)
        
    # Удаляем символ '@' если он был передан оператором
    accounts = [acc.lstrip('@') for acc in accounts]
    
    print(f"[+] Целевые аккаунты для накрутки: {', '.join(accounts)}")
    print("=" * 60)

    # 2. Получение списка подключенных устройств
    devices_info = get_devices_with_lock_status()
    if not devices_info:
        print("[!] Критическая ошибка: не найдено ни одного подключенного Android-устройства!")
        sys.exit(1)
        
    unlocked_devices = [d["device_id"] for d in devices_info if d["is_unlocked"]]
    locked_devices = [d["device_id"] for d in devices_info if not d["is_unlocked"]]
    
    print(f"[+] Всего обнаружено устройств: {len(devices_info)}")
    print(f"🟢 РАЗБЛОКИРОВАНО и готово к работе: {len(unlocked_devices)}")
    if locked_devices:
        print(f"🔒 ЗАБЛОКИРОВАНО / СПЯТ (будут пропущены): {len(locked_devices)}")
    
    if not unlocked_devices:
        print("[!] Все устройства заблокированы или спят! Прерываем.")
        sys.exit(0)
        
    devices = unlocked_devices
        
    num_devices = len(devices)
    print(f"[+] Обнаружено устройств: {num_devices}")
    for dev in devices:
        print(f" - {dev}")
    print("=" * 60)
    
    stop_event = threading.Event()
    
    # Хранение результатов по кругам
    circle_reports = []
    start_time = time.time()
    threads = []
    
    try:
        for circle_idx in range(1, 6):
            if stop_event.is_set():
                break
                
            print(f"\n" + "=" * 60)
            print(f"=== НАЧАЛО НОЧНОГО КРУГА {circle_idx}/5 ===")
            print("=" * 60)
            
            completed_reps = {}
            threads = []
            
            # Запуск потоков накрутки для этого круга
            for dev_id in devices:
                t = threading.Thread(
                    target=run_boost_automation,
                    args=(dev_id, accounts, stop_event, completed_reps),
                    name=f"Thread-{dev_id}"
                )
                threads.append(t)
                t.start()
                
            print(f"[+] Запущен круг {circle_idx}. Ожидаем завершения всеми телефонами...")
            
            # Ожидание завершения круга всеми устройствами
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
                
            if stop_event.is_set():
                print(f"[!] Круг {circle_idx} был прерван.")
                break
                
            circle_circles = sum(completed_reps.values())
            print(f"[+] Все телефоны завершили круг {circle_idx}!")
            print(f"[+] Выполнено кругов (видео-повторений) в этом круге: {circle_circles}")
            
            # Сохраняем отчет за этот круг
            circle_reports.append({
                "circle": circle_idx,
                "reps": circle_circles,
                "device_details": dict(completed_reps)
            })
            
            # Принудительно выводим все устройства на главный экран (Home screen)
            print("[*] Выводим все телефоны на главный экран...")
            for dev_id in devices:
                try:
                    dev = ADBDevice(dev_id)
                    dev.run_shell("input keyevent 3")  # KEYCODE_HOME
                except Exception as e:
                    print(f"[{dev_id}] Ошибка вывода на главный экран: {e}")
            
            # Если это не последний круг, делаем паузу 15 минут
            if circle_idx < 5:
                pause_minutes = 15
                print(f"\n[*] Переходим в режим ожидания на {pause_minutes} минут перед следующим кругом...")
                
                # Обратный отсчет по минутам с возможностью прерывания
                for min_left in range(pause_minutes, 0, -1):
                    if stop_event.is_set():
                        break
                    print(f"[*] До старта круга {circle_idx + 1} осталось: {min_left} мин...")
                    # 60 секунд спим частями по 1 сек для мгновенной реакции на Ctrl+C
                    for _ in range(60):
                        if stop_event.is_set():
                            break
                        time.sleep(1.0)
                        
        # Финальный отчет при штатном завершении
        total_time = time.time() - start_time
        print_final_report(circle_reports, total_time, interrupted=False)
        
    except KeyboardInterrupt:
        print("\n[!] Получен сигнал прерывания (Ctrl+C). Безопасно завершаем работу потоков...")
        stop_event.set()
        
        # Ожидаем завершения активных потоков перед выходом
        for t in threads:
            if t.is_alive():
                t.join()
                
        total_time = time.time() - start_time
        print_final_report(circle_reports, total_time, interrupted=True)

def print_final_report(reports, total_time, interrupted=False):
    print("\n" + "=" * 60)
    status_str = " (ПРЕРВАНО)" if interrupted else ""
    print(f"ОТЧЕТ ПО НОЧНОЙ НАКРУТКЕ{status_str}:")
    print(f" - Общее время работы скрипта: {total_time // 3600:.0f} ч { (total_time % 3600) // 60:.0f} мин {total_time % 60:.1f} сек")
    
    total_all_reps = sum(r["reps"] for r in reports)
    print(f" - Всего кругов (видео-повторений) за всю ночь: {total_all_reps}")
    print(f" - Успешно выполнено ночных кругов: {len(reports)}/5")
    print("=" * 60)
    
    for r in reports:
        print(f" Ночной круг {r['circle']}: {r['reps']} повторений видео.")
    print("=" * 60)
    print("[+] Все потоки накрутки остановлены, телефоны на главном экране.")

if __name__ == "__main__":
    main()
