# turbo_adb.py
"""
Турбо-движок параллельного выполнения ADB команд для 30 смартфонов.
Обеспечивает мгновенную реакцию и параллельную работу через ThreadPoolExecutor.
"""

import subprocess
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from adb_helper import ADB_PATH, get_connected_devices

def execute_single_adb(device_id, cmd_args, adb_port=5037, timeout=5):
    """
    Выполняет одиночную ADB команду на устройстве.
    """
    try:
        full_cmd = [ADB_PATH, "-P", str(adb_port), "-s", device_id] + cmd_args
        res = subprocess.run(full_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)
        return (device_id, res.returncode == 0, res.stdout.strip())
    except Exception as e:
        return (device_id, False, str(e))

def run_parallel_adb_command(command_args, target_devices=None, max_workers=30):
    """
    Выполняет ADB команду параллельно на всех 30 устройствах одновременно.
    """
    if target_devices is None:
        target_devices = get_connected_devices()
        
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for dev_id in target_devices:
            port = 5038 if "R5GYB" in dev_id or "R5CY" in dev_id else 5037
            future = executor.submit(execute_single_adb, dev_id, command_args, port)
            futures[future] = dev_id
            
        for future in as_completed(futures):
            dev_id, success, output = future.result()
            results[dev_id] = {"success": success, "output": output}
            
    return results

def turbo_swipe_all_up():
    """
    Мгновенно скроллит ленту вверх на всех 30 устройствах одновременно!
    """
    cmd = ["shell", "input", "swipe", "500", "1400", "500", "400", "250"]
    return run_parallel_adb_command(cmd)

def turbo_like_all():
    """
    Мгновенно ставит двойной тап лайк на всех 30 устройствах одновременно!
    """
    cmd = ["shell", "input", "tap", "540", "960"]
    run_parallel_adb_command(cmd)
    time.sleep(0.1)
    return run_parallel_adb_command(cmd)

if __name__ == "__main__":
    print("[Turbo ADB Engine] ⚡ Турбо-движок 30 устройств готов к работе!")
