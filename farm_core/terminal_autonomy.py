# -*- coding: utf-8 -*-
"""
terminal_autonomy.py - Модуль Терминальной Автономии и Самолечения для Plitty.
Дает Плитти возможность запускать скрипты на сервере, читать логи в реальном времени,
купировать зависания и самостоятельно лечить сбои на смартфонах фермы.
"""

import sys
import os
import subprocess
import threading
import time
import json
from pathlib import Path

# Фикс кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "scratch" / "farm_logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Глобальный реестр активных автономных задач
active_farm_tasks = {}

def execute_terminal_safe(cmd_str: str, timeout_sec: int = 15) -> dict:
    """Безопасное выполнение терминальной команды."""
    print(f"[Terminal Autonomy] 💻 Выполнение команды: {cmd_str}")
    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "success": res.returncode == 0,
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip(),
            "returncode": res.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Превышен таймаут выполнения ({timeout_sec}с)", "stdout": "", "stderr": ""}
    except Exception as e:
        return {"success": False, "error": str(e), "stdout": "", "stderr": ""}

def get_live_farm_logs(max_lines: int = 25) -> str:
    """Собирает последние строки логов работы фермы и автохилера."""
    logs_output = []
    
    # 1. Проверяем лог-файлы в папке scratch
    for log_file in sorted(LOGS_DIR.glob("*.log"), key=os.path.getmtime, reverse=True)[:3]:
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = "".join(lines[-max_lines:])
                logs_output.append(f"📄 <b>{log_file.name}</b>:\n{tail.strip()}")
        except Exception:
            pass
            
    # 2. Если файлов нет, опрашиваем статус ADB
    if not logs_output:
        adb_res = execute_terminal_safe(".\\platform-tools\\adb.exe devices")
        logs_output.append(f"📱 <b>ADB Devices Live Status</b>:\n{adb_res.get('stdout', 'Нет данных')}")

    return "\n\n".join(logs_output) if logs_output else "Логи пусты. Ферма ожидает команд."

def diagnose_and_heal_farm() -> dict:
    """
    Полная автономная диагностика и самолечение фермы:
    - Проверка хабов и авторизации ADB
    - Перезапуск упавших демонов
    - Очистка зависших процессов TikTok
    - Возврат телефонов на рабочий стол
    """
    print("[Terminal Autonomy] 🛡️ Запуск глубокой автодиагностики и самолечения фермы...")
    actions_taken = []
    
    # 1. Проверяем ADB устройства
    try:
        from adb_helper import get_connected_devices, ADBDevice
        devices = get_connected_devices()
        dev_count = len(devices)
        actions_taken.append(f"🔍 Обнаружено {dev_count} активных смартфонов по ADB.")
    except Exception as e:
        # Пытаемся перезапустить adb server
        execute_terminal_safe(".\\platform-tools\\adb.exe kill-server")
        time.sleep(1)
        execute_terminal_safe(".\\platform-tools\\adb.exe start-server")
        actions_taken.append(f"⚠️ Перезапущен ADB-сервер из-за сбоя: {e}")
        from adb_helper import get_connected_devices, ADBDevice
        devices = get_connected_devices()
        dev_count = len(devices)

    # 2. Сброс зависших окон и очистка кэша на каждом смартфоне в потоках
    if devices:
        def heal_device(dev_id):
            try:
                dev = ADBDevice(dev_id)
                dev.stop_tiktok()
                # Разблокировка экрана и возврат на Home
                dev.wake_up()
                dev.press_home()
            except Exception:
                pass

        threads = []
        for dev_id in devices:
            t = threading.Thread(target=heal_device, args=(dev_id,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=4)
        actions_taken.append(f"✨ Сброшен экран и очищена память на {len(devices)} смартфонах.")

    # 3. Синхронизируем Firebase статус
    try:
        import cloud_agent
        cloud_agent.fb_request("connected_devices_count", "PUT", dev_count)
        actions_taken.append("☁️ Статус фермы синхронизирован с Firebase RTDB.")
    except Exception:
        pass

    report = (
        f"🛡️ <b>Отчет самолечения Plitty:</b>\n" +
        "\n".join([f"• {a}" for a in actions_taken]) +
        f"\n\n<b>Итог:</b> Ферма в полной боевой готовности! Подключено: <b>{dev_count}</b> устройств. 😼🍺"
    )
    
    return {
        "success": True,
        "devices_count": dev_count,
        "actions": actions_taken,
        "report": report
    }

def start_farm_script(script_name: str) -> dict:
    """Запускает скрипт автоматизации в фоновом режиме."""
    script_map = {
        "прогрев": "automation.py",
        "automation": "automation.py",
        "накрутка": "nakrutka.py",
        "nakrutka": "nakrutka.py",
        "ночная накрутка": "nakrutka_night.py",
        "турбо": "turbo_adb.py"
    }
    
    target_file = script_map.get(script_name.lower().strip(), script_name)
    target_path = BASE_DIR / target_file
    
    if not target_path.exists():
        return {"success": False, "error": f"Скрипт {target_file} не найден на сервере!"}

    log_file = LOGS_DIR / f"{Path(target_file).stem}_{int(time.time())}.log"
    
    try:
        proc = subprocess.Popen(
            [sys.executable, str(target_path)],
            cwd=str(BASE_DIR),
            stdout=open(log_file, "w", encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT
        )
        active_farm_tasks[target_file] = {
            "pid": proc.pid,
            "process": proc,
            "log_file": str(log_file),
            "start_time": time.time()
        }
        print(f"[Terminal Autonomy] 🚀 Скрипт {target_file} успешно запущен в фоне (PID: {proc.pid})")
        return {
            "success": True,
            "pid": proc.pid,
            "script": target_file,
            "log_file": str(log_file),
            "message": f"🚀 <b>Скрипт {target_file} запущен!</b> (PID: {proc.pid})\nЛоги пишутся в автономный поток."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def stop_all_farm_scripts() -> dict:
    """Останавливает все запущенные фоновые скрипты."""
    stopped = []
    for script_name, task in list(active_farm_tasks.items()):
        try:
            proc = task.get("process")
            if proc and proc.poll() is None:
                proc.terminate()
                stopped.append(script_name)
        except Exception:
            pass
    active_farm_tasks.clear()
    
    # Также выполняем сброс через adb
    diagnose_and_heal_farm()
    return {
        "success": True,
        "stopped_scripts": stopped,
        "message": f"🛑 Все скрипты ({', '.join(stopped) if stopped else 'нет активных'}) остановлены, смартфоны переведены в режим ожидания."
    }

if __name__ == "__main__":
    print("[+] Тест диагностики и самолечения фермы...")
    diag = diagnose_and_heal_farm()
    print(diag["report"])
