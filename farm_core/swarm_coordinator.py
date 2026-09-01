# swarm_coordinator.py
"""
Модуль координации Нейро-Роя (Swarm Intelligence / Телефонная ОПГ).
Координирует действия 30 смартфонами для органического вывод постов
и комментариев в топы рекомендаций TikTok.
"""

import time
import random
import threading
import db_manager

swarm_lock = threading.Lock()
active_swarm_targets = []

SWARM_REPLY_TEMPLATES = [
    "Factsss! 💯",
    "Agreed 100% ⚡",
    "Literally this!! 🔥",
    "Say it louder for the people in the back 👏",
    "Couldn't have said it better myself 🙌",
    "This right here 💯🔥",
    "Fr fr 😭",
    "W comment 👑"
]

def register_swarm_target(initiator_device, target_author, comment_text):
    """
    Регистрирует новую цель для атаки Нейро-Роя из 30 устройств.
    """
    with swarm_lock:
        target = {
            "id": f"swarm_{int(time.time())}",
            "initiator": initiator_device,
            "target_author": target_author,
            "comment_text": comment_text,
            "assigned_devices": [initiator_device],
            "likes_count": 1,
            "replies_count": 0,
            "created_at": time.time()
        }
        active_swarm_targets.append(target)
        
        # Записываем событие роя в БД SQLite
        db_manager.log_device_event(initiator_device, "SWARM_INITIATE", f"Target: @{target_author}")
        
    print(f"[Swarm Intelligence] 🐝 Запущена роевая атака от девайса [{initiator_device}] на цели @{target_author}!")
    return target["id"]

def get_swarm_task_for_device(device_id):
    """
    Возвращает персональную задачу Роя для конкретного смартфона.
    """
    with swarm_lock:
        if not active_swarm_targets:
            return None
            
        target = active_swarm_targets[-1] # Ближайшая активная цель
        
        if device_id in target["assigned_devices"]:
            return None
            
        target["assigned_devices"].append(device_id)
        
        task_type = "SWARM_LIKE" if random.random() < 0.6 else "SWARM_REPLY"
        if task_type == "SWARM_LIKE":
            target["likes_count"] += 1
        else:
            target["replies_count"] += 1
            
        db_manager.log_device_event(device_id, task_type, f"Target: @{target['target_author']}")
        
        return {
            "task_type": task_type,
            "target_author": target["target_author"],
            "comment_text": target["comment_text"],
            "reply_text": random.choice(SWARM_REPLY_TEMPLATES)
        }

def get_swarm_summary():
    """
    Возвращает отчет о текущей активности Нейро-Роя.
    """
    with swarm_lock:
        if not active_swarm_targets:
            return "🐝 Нейро-Рой находится в режиме ожидания целей."
            
        t = active_swarm_targets[-1]
        return (
            f"🐝 <b>Активный Нейро-Рой 30 устройств:</b><br>"
            f"Цель: <b>@{t['target_author']}</b><br>"
            f"Участвует смартфонов: <b>{len(t['assigned_devices'])}/30</b><br>"
            f"Роевых лайков: <b>{t['likes_count']}</b>, Ответных веток: <b>{t['replies_count']}</b>"
        )

if __name__ == "__main__":
    t_id = register_swarm_target("R5GYB0707GN", "taylorswift", "Best album ever!")
    print(get_swarm_summary())
