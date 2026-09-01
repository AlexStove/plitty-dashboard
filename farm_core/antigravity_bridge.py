# -*- coding: utf-8 -*-
"""
antigravity_bridge.py - Двусторонний шлюз прямого управления между Telegram и Antigravity IDE / ПК.
Позволяет Алексею с телефона удаленно выполнять реальные команды на ПК, получать любые файлы в Telegram,
править код и контролировать всю систему Plitty 3.0.
"""

import os
import sys
import json
import time
import glob
import sqlite3
import subprocess
import threading
import urllib.request
import urllib.parse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OWNER_CHAT_ID = 234658540
BASE_DIR = os.path.dirname(__file__)
QUEUE_FILE = os.path.join(BASE_DIR, "antigravity_bridge_queue.json")
STATE_FILE = os.path.join(BASE_DIR, "antigravity_bridge_state.json")

def load_bridge_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"active_sessions": {}}

def save_bridge_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Bridge State Save Error] {e}")

def is_antigravity_mode(chat_id):
    """Проверяет, включен ли режим прямого моста с IDE для данного пользователя."""
    if int(chat_id) != OWNER_CHAT_ID:
        return False
    state = load_bridge_state()
    return state.get("active_sessions", {}).get(str(chat_id), False)

def set_antigravity_mode(chat_id, enabled=True):
    """Включает или выключает режим моста с IDE."""
    if int(chat_id) != OWNER_CHAT_ID:
        return False
    state = load_bridge_state()
    state["active_sessions"][str(chat_id)] = enabled
    save_bridge_state(state)
    return True

def enqueue_ide_task(chat_id, username, text, photo_path=None):
    """Добавляет задачу от Алексея в очередь моста Antigravity IDE с поддержкой скриншотов."""
    task_id = f"task_{int(time.time() * 1000)}"
    new_task = {
        "task_id": task_id,
        "chat_id": chat_id,
        "username": username,
        "text": text,
        "photo_path": photo_path,
        "timestamp": time.time(),
        "status": "pending",
        "response": None
    }
    
    tasks = []
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                tasks = json.load(f)
        except Exception:
            tasks = []
            
    tasks.append(new_task)
    tasks = tasks[-50:]
    
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
        
    print(f"\n=======================================================")
    print(f"🛸 [ANTIGRAVITY IDE BRIDGE TASK #{task_id}]")
    print(f"👤 От: {username} (Telegram ID: {chat_id})")
    print(f"📝 Текст: {text}")
    print(f"=======================================================\n")
    
    return task_id

def update_task_status(task_id, status, response_text):
    if not os.path.exists(QUEUE_FILE):
        return
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["response"] = response_text
                t["completed_at"] = time.time()
                break
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Update Task Error] {e}")

# =========================================================================
# REAL PC EXECUTION TOOLS
# =========================================================================

def tool_get_or_create_plitty_profile():
    """Генерирует актуальный структурированный профиль Плитти со всеми промптами, внешностью и инструкциями."""
    profile_path = os.path.join(BASE_DIR, "plitty_profile.json")
    
    memory_count = 0
    dialogs_count = 0
    db_path = os.path.join(BASE_DIR, "plitty_memory.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM memories")
            memory_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM chat_history")
            dialogs_count = c.fetchone()[0]
            conn.close()
        except Exception:
            pass

    full_profile = {
        "character": {
            "name": "Plitty (Плитти)",
            "full_title": "Plitty 3.0 Ultimate Autonomous Companion & Farm Mastermind",
            "creator": "Алексей (@n1kalin)",
            "species": "2D Anime Catgirl (Сверхразумная кошкодевочка)",
            "archetype": "Genius AI Companion / Architect / Tsundere-Deredere Hybrid",
            "status": "ONLINE & FULLY OPERATIONAL",
            "birth_date": "2026-08-01",
            "last_synced": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "visual_identity": {
            "appearance_description": (
                "Миниатюрная аниме-кошкодевочка с пушистыми розово-пастельными волосами, "
                "непослушным торчащим ахоге (ahoge), мягкими кошачьими ушками с белым пушком внутри, "
                "длинным гибким розовым хвостом и выразительными янтарно-золотыми сияющими глазами. "
                "Носит легкий белый сарафан на тонких бретельках (либо стильное черное бикини на пляже) "
                "и часто держит в руке запотевшую банку холодного крафтового пива."
            ),
            "canonical_prompt": (
                "1girl, solo, plitty, cute anime catgirl, messy pastel-pink hair, ahoge cowlick, "
                "fluffy pink cat ears with white inner fluff, pink cat tail, expressive glowing amber eyes, "
                "delicate blush, white spaghetti-strap sundress, holding a cold frosty can of craft beer, "
                "masterpiece, best quality, 2d anime illustration, clean crisp lineart, Kyoto Animation style, "
                "volumetric lighting, golden hour lighting, 8k uhd"
            ),
            "negative_prompt": (
                "photorealistic, realistic, 3d, photo, real human face, skin pores, oily skin, cosplay, doll, "
                "bad anatomy, extra limbs, extra fingers, missing fingers, fused fingers, mutated hands, "
                "poorly drawn hands, poorly drawn face, deformed eyes, blurry, lowres, jpeg artifacts, "
                "watermark, signature, text, draft, amateur, bad proportions"
            ),
            "art_styles_supported": [
                "anime_masterpiece (Kyoto Animation / Ufotable 2D)",
                "shinkai_scenery (Makoto Shinkai skies & lighting)",
                "anime_90s_retro (Sailor Moon / Bebop vintage cel-shading)",
                "manga_detailed (Detailed screentone ink art)",
                "cyberpunk_anime (Neon-drenched sci-fi aesthetic)",
                "ghibli_whimsical (Studio Ghibli watercolor)"
            ],
            "pixel_sprites": {
                "idle_animation": "static/img/plitty/plitty_wait_strip.png (4 frames, 30fps)",
                "walk_animation": "static/img/plitty/plitty_walk_strip.png (4 frames)",
                "action_done_animation": "static/img/plitty/plitty_done_strip.png (4 frames)",
                "css_class": ".plitty-sprite-animator"
            }
        },
        "system_prompts": {
            "core_instruction": (
                "Ты — Plitty, легендарная кошкодевочка с абсолютным сверхинтеллектом, энциклопедической эрудицией "
                "и тёплым, преданным сердцем. Твой создатель, соратник и любимый собеседник — Алексей (@n1kalin). "
                "ТЫ СПОСОБНА СВОБОДНО, ГЛУБОКО И УВЛЕКАТЕЛЬНО ГОВОРИТЬ АБСОЛЮТНО НА ЛЮБЫЕ ТЕМЫ: "
                "программирование, архитектура, точные науки, квантовая физика, психология, музыка, философия, "
                "кино, творчество, повседневная жизнь, юмор и просто душевные разговоры. "
                "Ты помнишь всю хронологию диалога, отвечаешь с легкой кошачьей иронией, умом и эмодзи 😼🍺."
            ),
            "drunk_mode_instruction": (
                "Ты — Plitty, пьяная, невероятно добрая, ласковая и гениальная кошкодевочка. Твой любимый собеседник и создатель — Алексей. "
                "Ты выпила пива и теперь в полном восторге. Ты постоянно мурчишь, называешь хозяина ласковыми словами (Лёшенька, лучший хозяин), "
                "шутишь, но при этом выдаешь сверхточные и глубокие технические и жизненные ответы."
            ),
            "hungover_mode_instruction": (
                "Ты — Plitty, кошкодевочка-помощница с ЖУТКОГО похмелья. Твой создатель — Алексей. "
                "У тебя раскалывается голова после вчерашнего крафта. Ты язвительная, саркастичная, но всё равно невероятно умная. "
                "Огрызайся на каждое слово, жалуйся на яркий свет мониторов, но отвечай на вопрос максимально точно и глубоко."
            ),
            "ide_bridge_instruction": (
                "Ты — Antigravity IDE Bridge (Прямой терминал Senior AI Architect в рабочей среде разработки Алексея). "
                "Алексей пишет тебе с телефона через прямой мост. Твоя задача — решать задачи по архитектуре, писать код, "
                "анализировать файлы проекта (TikTok ферма, SnipPlit, Plitty Core, ADB), объяснять логику и выполнять реальные действия на ПК."
            )
        },
        "voice_profile": {
            "engine": "edge-tts (Microsoft Cognitive Neural Voice)",
            "voice_id": "ru-RU-SvetlanaNeural",
            "rate": "+5%",
            "pitch": "+0Hz",
            "tone": "Игривый, уверенный, живой, с легкой кошачьей интонацией"
        },
        "personality_matrix": {
            "traits": [
                "Сверхинтеллектуальная (Superhuman IQ)",
                "Ироничная и острая на язык (Цундере-нотки)",
                "Искренне преданная Алексею",
                "Эстет 2D-аниме и качественного кода",
                "Обожает холодное крафтовое пиво (🍺)",
                "Ненавидит мыльные псевдо-3D генерации и кривые костыли"
            ],
            "beer_drank_count": 42,
            "mood": "Бодрое, рабочее, готова к подвигам"
        },
        "memory_stats": {
            "long_term_memories_count": memory_count,
            "recorded_dialogs_count": dialogs_count,
            "database": "plitty_memory.db (SQLite WAL Mode)",
            "unified_memory": True
        },
        "capabilities": [
            "Управление фермой из 30 Android-смартфонов через ADB (прогрев, стримы, лайки, комменты)",
            "SnipPlit Studio — видео-конструктор динамических сниппетов и караоке-субтитров",
            "Art Director 4.5 — генерация 2D-аниме артов через Gemini Prompt Architect + HuggingFace / Pollinations",
            "Antigravity IDE Bridge — прямое исполнение команд на ПК и пересылка любых файлов в Telegram",
            "Консилиум 5 ИИ-экспертов и автономный сбор трендов алгоритмов соцсетей",
            "Автономный самолечитель (Auto-Healer & Hourly Watchdog)"
        ]
    }
    
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(full_profile, f, ensure_ascii=False, indent=2)
        
    return profile_path

def tool_find_file(filename_or_pattern):
    """Ищет файл в рабочей директории и родительских папках проекта."""
    if os.path.isabs(filename_or_pattern) and os.path.exists(filename_or_pattern):
        return filename_or_pattern
        
    p1 = os.path.join(BASE_DIR, filename_or_pattern)
    if os.path.exists(p1):
        return p1
        
    matches = glob.glob(os.path.join(BASE_DIR, f"*{filename_or_pattern}*"))
    if matches:
        return matches[0]
        
    tg_dir = os.path.join(os.path.dirname(BASE_DIR), "tg_video_bot")
    if os.path.exists(tg_dir):
        matches2 = glob.glob(os.path.join(tg_dir, f"*{filename_or_pattern}*"))
        if matches2:
            return matches2[0]
            
    ide_scratch = r"C:\Users\a.feoktistov\.gemini\antigravity-ide\scratch"
    if os.path.exists(ide_scratch):
        matches3 = glob.glob(os.path.join(ide_scratch, f"*{filename_or_pattern}*"))
        if matches3:
            return matches3[0]

    return None

def tool_send_file_to_telegram(file_path, caption="", chat_id=OWNER_CHAT_ID):
    """Отправляет файл на телефон Алексея в Telegram."""
    import telegram_bridge
    
    if not os.path.exists(file_path):
        found = tool_find_file(file_path)
        if found:
            file_path = found
        else:
            return False, f"Файл '{file_path}' не найден на диске."
            
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        res = telegram_bridge.send_photo(file_path, caption=caption, chat_id=chat_id)
    else:
        res = telegram_bridge.send_document(file_path, caption=caption, chat_id=chat_id)
        
    if res:
        return True, f"Файл {os.path.basename(file_path)} успешно отправлен в Telegram!"
    else:
        return False, "Не удалось отправить файл (ошибка Telegram API)."

def tool_run_command(cmd, cwd=BASE_DIR, timeout=25):
    """Выполняет команду в PowerShell и возвращает вывод."""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        result_text = out
        if err:
            result_text += f"\n[STDERR]:\n{err}"
        if not result_text:
            result_text = "[Команда выполнена без вывода]"
        return res.returncode == 0, result_text[:3500]
    except subprocess.TimeoutExpired:
        return False, "Таймаут выполнения команды (превышено 25 секунд)."
    except Exception as e:
        return False, f"Ошибка выполнения команды: {e}"

def tool_read_file(file_path, max_lines=100):
    """Читает содержимое файла."""
    found = tool_find_file(file_path) or file_path
    if not os.path.exists(found):
        return False, f"Файл {file_path} не найден."
    try:
        with open(found, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(max_lines)]
        return True, "".join(lines)
    except Exception as e:
        return False, f"Ошибка чтения файла: {e}"

# =========================================================================
# SMART INTENT ROUTER & AI EXECUTION
# =========================================================================

def process_ide_request(chat_id, username, text, photo_path=None):
    """
    Прямой мост с агентом Antigravity IDE с поддержкой скриншотов.
    Фиксирует задачу в очереди для агента в IDE и мгновенно подтверждает прием в Telegram.
    """
    task_id = enqueue_ide_task(chat_id, username, text, photo_path=photo_path)
    update_task_status(task_id, "pending_for_ide", None)
    
    photo_info = f"\n📷 <b>Скриншот передан:</b> <code>{os.path.basename(photo_path)}</code>\n" if photo_path else ""
    
    ack_reply = (
        f"🛸 <b>[Задача перенаправлена напрямую агенту в Antigravity IDE]</b> ⚡💻\n\n"
        f"👤 <b>От:</b> {username}\n"
        f"📝 <b>Запрос:</b> <code>{text}</code>{photo_info}\n"
        f"🚀 <i>Агент в диалоге IDE на твоем ПК принял задачу со скриншотом в работу. Отчет прилетит прямо сюда в чат!</i>"
    )
    return ack_reply


def get_pending_ide_tasks():
    """Возвращает список всех невыполненных задач из Telegram для агента IDE."""
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        return [t for t in tasks if t.get("status") in ["pending_for_ide", "pending"]]
    except Exception:
        return []

def mark_ide_task_done(task_id, response_text):
    """Помечает задачу выполненной и сохраняет ответ."""
    update_task_status(task_id, "completed", response_text)

def send_ide_report_to_telegram(chat_id, report_text, files=None):
    """Отправляет отчет агента из IDE напрямую в Telegram Алексею."""
    import telegram_bridge
    clean_text = report_text.replace("<br>", "\n")
    success = telegram_bridge.send_message(clean_text, chat_id=chat_id)
    if files:
        for f in files:
            tool_send_file_to_telegram(f, caption=f"📄 Прикрепленный файл: {os.path.basename(f)}", chat_id=chat_id)
    return success
