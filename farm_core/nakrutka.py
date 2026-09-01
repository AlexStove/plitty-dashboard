# nakrutka.py
"""
Главная точка входа для запуска накрутки на нескольких устройствах.
Считывает целевые аккаунты из аргументов командной строки, отфильтровывает
заблокированные/спящие смартфоны и запускает потоки ТОЛЬКО на разблокированных.
"""

import threading
import time
import sys
import config
from adb_helper import get_devices_with_lock_status
from boost_automation import run_boost_automation

# Настройка UTF-8 для корректного вывода эмодзи в консоли Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    print("=" * 60)
    print("Запуск системы автоматизации TikTok (НАКРУТКА)")
    print("=" * 60)
    
    # 1. Считывание аккаунтов из аргументов командной строки
    accounts = sys.argv[1:]
    if not accounts:
        print("[!] Ошибка: не указаны аккаунты для накрутки!")
        print("[*] Использование: python nakrutka.py account1 account2 ...")
        sys.exit(1)
        
    # Удаляем символ '@' если он был передан оператором
    accounts = [acc.lstrip('@') for acc in accounts]
    
    print(f"[+] Целевые аккаунты для накрутки: {', '.join(accounts)}")
    print("=" * 60)

    # 2. Получение списка подключенных устройств и их статуса блокировки
    print("[*] Проверка статуса блокировки всех подключенных устройств...")
    devices_info = get_devices_with_lock_status()
    
    if not devices_info:
        print("[!] Критическая ошибка: не найдено ни одного подключенного Android-устройства!")
        sys.exit(1)
        
    unlocked_devices = [d["device_id"] for d in devices_info if d["is_unlocked"]]
    locked_devices = [d["device_id"] for d in devices_info if not d["is_unlocked"]]
    
    print(f"[+] Всего обнаружено устройств: {len(devices_info)}")
    print(f"🟢 РАЗБЛОКИРОВАНО и готово к работе: {len(unlocked_devices)}")
    for dev_id in unlocked_devices:
        print(f"   ✓ [READY] {dev_id}")
        
    if locked_devices:
        print(f"🔒 ЗАБЛОКИРОВАНО / СПЯТ (будут пропущены): {len(locked_devices)}")
        for d in devices_info:
            if not d["is_unlocked"]:
                print(f"   ✗ [SKIPPED] {d['device_id']} — {d['status_text']}")
                
    print("=" * 60)
    
    if not unlocked_devices:
        print("[!] Все устройства заблокированы или спят!")
        print("[*] Пожалуйста, разблокируйте экраны нужных смартфонов и запустите скрипт снова.")
        sys.exit(0)
    
    # Событие для безопасной остановки потоков при прерывании
    stop_event = threading.Event()
    threads = []
    completed_reps = {}
    start_time = time.time()
    
    # 3. Запуск потоков ТОЛЬКО для разблокированных устройств
    for dev_id in unlocked_devices:
        t = threading.Thread(
            target=run_boost_automation,
            args=(dev_id, accounts, stop_event, completed_reps),
            name=f"Thread-{dev_id}"
        )
        threads.append(t)
        t.start()
        
    print(f"\n[+] Все потоки накрутки ({len(threads)}) успешно запущены (только разблокированные).")
    print("[*] Для аварийного завершения нажмите Ctrl+C\n")

    # 4. Ожидание завершения потоков с обработкой Ctrl+C
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
            
        total_time = time.time() - start_time
        total_circles = sum(completed_reps.values())
        print("=" * 60)
        print("ОТЧЕТ ПО НАКРУТКЕ:")
        print(f" - Общее время выполнения: {total_time // 60:.0f} мин {total_time % 60:.1f} сек")
        print(f" - Всего кругов (повторений) выполнено: {total_circles}")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n[!] Получен сигнал прерывания (Ctrl+C). Завершаем работу потоков...")
        stop_event.set()
        
        for t in threads:
            t.join()
            
        total_time = time.time() - start_time
        total_circles = sum(completed_reps.values())
        print("=" * 60)
        print("ОТЧЕТ ПО НАКРУТКЕ (ПРЕРВАНО):")
        print(f" - Время выполнения до прерывания: {total_time // 60:.0f} мин {total_time % 60:.1f} сек")
        print(f" - Кругов выполнено до прерывания: {total_circles}")
        print("=" * 60)
        print("[+] Все потоки накрутки остановлены.")

if __name__ == "__main__":
    main()
