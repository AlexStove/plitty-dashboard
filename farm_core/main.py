# main.py
"""
Главная точка входа для скрипта автоматизации TikTok на нескольких устройствах.
Обнаруживает устройства через ADB, отфильтровывает заблокированные/спящие
и запускает параллельные потоки автоматизации только на РАЗБЛОКИРОВАННЫХ телефонах.
"""

import threading
import time
import sys
import random
import config
from adb_helper import get_devices_with_lock_status
from automation import run_device_automation

# Настройка UTF-8 для корректного вывода эмодзи в консоли Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    print("=" * 60)
    print("Запуск системы автоматизации TikTok (ПРОГРЕВ)")
    print("=" * 60)
    
    # 1. Получение списка всех подключенных устройств и их статуса блокировки
    print("[*] Проверка статуса блокировки всех подключенных устройств...")
    devices_info = get_devices_with_lock_status()
    
    if not devices_info:
        print("[!] Критическая ошибка: не найдено ни одного подключенного Android-устройства!")
        print("[*] Убедитесь, что отладка по USB включена и устройства отображаются в 'adb devices'.")
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
    
    # 2. Запуск потоков ТОЛЬКО для разблокированных устройств
    for dev_id in unlocked_devices:
        t = threading.Thread(
            target=run_device_automation,
            args=(dev_id, stop_event),
            name=f"Thread-{dev_id}"
        )
        threads.append(t)
        t.start()
        
    print(f"\n[+] Успешно запущено потоков: {len(threads)} (только разблокированные).")
    print("[*] Для аварийного завершения нажмите Ctrl+C\n")

    # 3. Ожидание завершения потоков с обработкой Ctrl+C
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
            
        for t in threads:
            t.join()
            
        print("\n[+] Все разблокированные устройства успешно выполнили свои сценарии.")
            
    except KeyboardInterrupt:
        print("\n[!] Получен сигнал прерывания (Ctrl+C). Завершаем работу потоков...")
        stop_event.set()
        for t in threads:
            t.join()
        print("[+] Все активные потоки остановлены.")

if __name__ == "__main__":
    main()
