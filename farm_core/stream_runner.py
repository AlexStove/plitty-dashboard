# stream_runner.py
"""
Многопоточный менеджер запуска просмотра стримов на всех подключенных устройствах фермы.
Поддерживает платформы: Kick, Twitch, TikTok.
Интегрирован со Smart Role Manager, Gemini AI Brain и Live Audio Transcriber.
"""

import sys
import os
import time
import argparse
import random
import threading
from adb_helper import ADBDevice, get_unlocked_devices
from stream_automation import TikTokLiveWatcher, KickLiveWatcher, TwitchLiveWatcher
from gemini_stream_brain import StreamRoleManager
from gemini_stream_transcriber import LiveAudioTranscriber

def run_device_worker(dev_id: str, platform: str, streamer: str, duration: int,
                      enable_likes: bool, enable_comments: bool,
                      stop_event: threading.Event, status_dict: dict,
                      stagger_sec: float = 0.0, role_info: dict = None):
    if stagger_sec > 0:
        time.sleep(stagger_sec)
        
    try:
        dev = ADBDevice(dev_id)
        if platform == "kick":
            watcher = KickLiveWatcher(dev, streamer, duration, enable_likes, enable_comments, stop_event, status_dict, role_info)
        elif platform == "twitch":
            watcher = TwitchLiveWatcher(dev, streamer, duration, enable_likes, enable_comments, stop_event, status_dict)
        elif platform == "tiktok":
            watcher = TikTokLiveWatcher(dev, streamer, duration, enable_likes, enable_comments, stop_event, status_dict)
        else:
            watcher = KickLiveWatcher(dev, streamer, duration, enable_likes, enable_comments, stop_event, status_dict, role_info)
            
        watcher.run()
    except Exception as e:
        print(f"[{dev_id}] [ERROR] Сбой воркера стрима: {e}")
        sys.stdout.flush()
        if dev_id in status_dict:
            status_dict[dev_id]["status"] = f"error: {e}"

def start_stream_session(platform: str, streamer: str, duration: int = 10,
                         enable_likes: bool = False, enable_comments: bool = True,
                         mode: str = "organic"):
    print(f"============================================================")
    print(f"🚀 СТАРТ УМНОЙ СТРИМ-СЕССИИ (SMART ORGANIC AUDIENCE)")
    print(f"  • Платформа: {platform.upper()}")
    print(f"  • Стример: @{streamer}")
    print(f"  • Длительность: {duration} мин")
    print(f"  • Режим чата: {mode.upper()}")
    print(f"  • Комментарии: {'ВКЛ (Gemini AI Brain)' if enable_comments else 'ВЫКЛ'}")
    print(f"============================================================")
    sys.stdout.flush()
    
    unlocked = get_unlocked_devices()
    if not unlocked:
        print("[!] Ошибка: Нет разблокированных устройств для запуска стрим-сессии!")
        sys.stdout.flush()
        return {"success": False, "error": "Нет разблокированных устройств", "threads": [], "stop_event": None, "status_dict": {}}
        
    print(f"[+] Разблокировано и готово устройств: {len(unlocked)}")
    
    # Расчет ролей
    roles_map = StreamRoleManager.calculate_roles(unlocked, duration, mode=mode)
    
    # Запуск фонового AI-транскрибатора
    transcriber = None
    if enable_comments:
        try:
            transcriber = LiveAudioTranscriber(streamer, platform)
            transcriber.start()
            print(f"[+] 🧠 Фоновый транскрибатор Gemini Audio AI активирован для @{streamer}")
        except Exception as te:
            print(f"[!] Транскрибатор: {te}")
    
    sys.stdout.flush()
    stop_event = threading.Event()
    status_dict = {}
    threads = []
    
    num_devs = len(unlocked)
    for i, dev_id in enumerate(unlocked):
        stagger = (i / (num_devs - 1)) * 6.0 + random.uniform(0.0, 1.0) if num_devs > 1 else 0.0
        role_info = roles_map.get(dev_id, {})
        t = threading.Thread(
            target=run_device_worker,
            args=(dev_id, platform, streamer, duration, enable_likes, enable_comments, stop_event, status_dict, stagger, role_info),
            name=f"StreamThread-{dev_id}"
        )
        threads.append(t)
        t.start()
        
    print(f"[+] Запущено {len(threads)} потоков (все зайдут на стрим в течение 8 секунд).")
    sys.stdout.flush()
    return {
        "success": True,
        "active_devices": len(unlocked),
        "stop_event": stop_event,
        "threads": threads,
        "status_dict": status_dict,
        "transcriber": transcriber
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Запуск просмотра стрима на ферме")
    parser.add_argument("--platform", default="kick", choices=["kick", "twitch", "tiktok"], help="Платформа стрима")
    parser.add_argument("--streamer", required=True, help="Никнейм стримера")
    parser.add_argument("--duration", type=int, default=10, help="Длительность просмотра в минутах")
    parser.add_argument("--mode", default="organic", choices=["organic", "stealth", "raid"], help="Режим активности")
    parser.add_argument("--no-likes", action="store_true", help="Отключить лайки")
    parser.add_argument("--no-comments", action="store_true", help="Отключить комментарии")
    
    args = parser.parse_args()
    res = start_stream_session(
        platform=args.platform,
        streamer=args.streamer,
        duration=args.duration,
        enable_likes=not args.no_likes,
        enable_comments=not args.no_comments,
        mode=args.mode
    )
    
    if res["success"]:
        threads = res["threads"]
        status_dict = res["status_dict"]
        stop_event = res["stop_event"]
        start_ts = time.time()
        max_duration_sec = args.duration * 60 + 15
        
        try:
            while any(t.is_alive() for t in threads):
                elapsed = time.time() - start_ts
                if elapsed >= max_duration_sec:
                    print(f"\n⏰ Превышен тайм-аут стрима ({args.duration} мин). Принудительное завершение...")
                    stop_event.set()
                    break
                    
                active_count = sum(1 for s in status_dict.values() if "watching" in s.get("status", ""))
                total_comments = sum(s.get("comments", 0) for s in status_dict.values())
                print(f"[*] В эфире: {active_count}/{len(threads)} | Комментов от фермы: {total_comments}", flush=True)
                time.sleep(3.0)
        except KeyboardInterrupt:
            print("\n[!] Остановка по Ctrl+C...")
            stop_event.set()
            
        if res.get("transcriber"):
            res["transcriber"].stop()
            
        for t in threads:
            t.join(timeout=8)
            
        total_comments = sum(s.get("comments", 0) for s in status_dict.values())
        print(f"\n[SUMMARY] Комментов оставлено: {total_comments}")
        print("🏁 СТРИМ-СЕССИЯ ПОЛНОСТЬЮ ЗАВЕРШЕНА", flush=True)
