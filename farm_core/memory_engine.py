# -*- coding: utf-8 -*-
"""
memory_engine.py - Движок Вечной Памяти для Plitty.
Хранит долгосрочные воспоминания, факты об Алексее, проектах, привычках и окружении
в локальной базе данных SQLite (Семантический поиск + Граф знаний).
"""

import os
import sys
import json
import time
import sqlite3
import re

# Фикс кодировки
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(__file__), "plitty_memory.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_memory_db():
    """Инициализирует таблицы долгосрочной памяти и графа знаний."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Таблица долговременных воспоминаний
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                content TEXT NOT NULL,
                keywords TEXT,
                importance INTEGER DEFAULT 3,
                created_at REAL NOT NULL
            )
        """)
        
        # 2. Таблица сущностей графа знаний
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                entity_type TEXT DEFAULT 'concept',
                attributes TEXT,
                updated_at REAL NOT NULL
            )
        """)
        
        # 3. Таблица связей в графе знаний
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                target_entity TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                UNIQUE(source_entity, relation_type, target_entity)
            )
        """)
        
        # 4. Таблица скользящей истории диалога (контекст сессии)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dialog_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        
        conn.commit()

# Инициализируем при импорте
init_memory_db()

def save_dialog_turn(session_id, role, content):
    """Сохраняет реплику диалога в историю сессии."""
    if not content or not session_id:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dialog_history (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (str(session_id), role, content.strip(), time.time()))
        
        # Ограничиваем историю 30 последними репликами на сессию
        cursor.execute("""
            DELETE FROM dialog_history WHERE id IN (
                SELECT id FROM dialog_history 
                WHERE session_id = ? 
                ORDER BY id DESC 
                LIMIT -1 OFFSET 30
            )
        """, (str(session_id),))
        conn.commit()

def get_dialog_history(session_id, max_turns=10):
    """
    Возвращает последние реплики диалога в формате сообщений Gemini:
    [ {"role": "user"|"model", "parts": [{"text": ...}]}, ... ]
    """
    if not session_id:
        return []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM (
                SELECT id, role, content FROM dialog_history 
                WHERE session_id = ? 
                ORDER BY id DESC 
                LIMIT ?
            ) ORDER BY id ASC
        """, (str(session_id), max_turns * 2))
        rows = cursor.fetchall()
        
    history = []
    for r in rows:
        r_role = "user" if r["role"] == "user" else "model"
        history.append({
            "role": r_role,
            "parts": [{"text": r["content"]}]
        })
    return history

def clear_dialog_history(session_id):
    """Очищает историю диалога сессии."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dialog_history WHERE session_id = ?", (str(session_id),))
        conn.commit()


def _extract_keywords(text):
    """Извлекает ключевые нормализованные токены для поиска."""
    clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in clean.split() if len(w) > 2]
    stopwords = {"это", "как", "так", "что", "или", "для", "при", "все", "еще", "уже", "был", "быть", "ты", "мы", "он", "она", "мне", "тебе", "меня", "тебя", "сам", "где", "кто"}
    return [w for w in words if w not in stopwords]

def save_memory(content, username="Алексей", category="fact", importance=3):
    """Сохраняет единицу воспоминания в базу."""
    if not content or len(content.strip()) < 4:
        return False
        
    keywords = " ".join(_extract_keywords(content))
    with get_connection() as conn:
        cursor = conn.cursor()
        # Проверяем на дубликаты
        cursor.execute("SELECT id FROM memories WHERE username = ? AND content = ?", (username, content))
        if cursor.fetchone():
            return False
            
        cursor.execute("""
            INSERT INTO memories (username, category, content, keywords, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, category, content.strip(), keywords, importance, time.time()))
        conn.commit()
    return True

def save_relation(source, relation, target):
    """Сохраняет факт связей в граф знаний."""
    if not source or not relation or not target:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO relations (source_entity, relation_type, target_entity, created_at)
            VALUES (?, ?, ?, ?)
        """, (source.strip(), relation.strip(), target.strip(), time.time()))
        conn.commit()
    return True

def retrieve_relevant_memories(query, username="Алексей", top_k=4):
    """
    Семантический BM25/TF-IDF поиск релевантных воспоминаний и фактов по графу.
    """
    query_tokens = set(_extract_keywords(query))
    if not query_tokens:
        return []

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, category, content, keywords, importance, created_at FROM memories WHERE username = ?", (username,))
        rows = cursor.fetchall()
        
        # Получаем также факты из графа
        cursor.execute("SELECT source_entity, relation_type, target_entity FROM relations")
        graph_rows = cursor.fetchall()

    scored = []
    for r in rows:
        kw_tokens = set(r["keywords"].split())
        overlap = query_tokens.intersection(kw_tokens)
        if overlap:
            score = len(overlap) * (1.0 + r["importance"] * 0.2)
            scored.append((score, r["content"]))

    # Проверяем граф связей
    graph_facts = []
    for gr in graph_rows:
        s, rel, t = gr["source_entity"], gr["relation_type"], gr["target_entity"]
        fact_tokens = set(_extract_keywords(f"{s} {rel} {t}"))
        if query_tokens.intersection(fact_tokens):
            graph_facts.append(f"ФАКТ: {s} -> [{rel}] -> {t}")

    scored.sort(key=lambda x: x[0], reverse=True)
    top_memories = [item[1] for item in scored[:top_k]]
    
    # Объединяем с найденными фактами графа
    combined = list(dict.fromkeys(top_memories + graph_facts[:3]))
    return combined

def auto_extract_facts_from_dialog(user_text, bot_reply, username="Алексей"):
    """
    Анализирует текст сообщения и автоматически сохраняет новые факты о предпочтениях,
    проектах, коде или задачах пользователя.
    """
    t_low = user_text.lower()
    
    # Шаблоны личных предпочтений
    likes_match = re.search(r'(?:я люблю|мне нравится|я обожаю|мой любимый)\s+([^.,!?\n]+)', t_low)
    if likes_match:
        pref = likes_match.group(1).strip()
        save_memory(f"{username} любит: {pref}", username=username, category="preference", importance=4)
        save_relation(username, "любит", pref)
        
    # Шаблоны проектов и работы
    project_match = re.search(r'(?:мой проект|я делаю|мы пилим|разрабатываю)\s+([^.,!?\n]+)', t_low)
    if project_match:
        proj = project_match.group(1).strip()
        save_memory(f"{username} разрабатывает проект: {proj}", username=username, category="project", importance=5)
        save_relation(username, "разрабатывает", proj)
        
    # Шаблоны имени и самопрезентации
    name_match = re.search(r'(?:меня зовут|я)\s+([А-Яа-яA-Za-z]+)', user_text)
    if name_match and "я" not in name_match.group(1).lower():
        extracted_name = name_match.group(1)
        save_memory(f"Имя создателя: {extracted_name}", username=username, category="identity", importance=5)

def format_memory_context_prompt(user_text, username="Алексей"):
    """Формирует блок контекста воспоминаний для добавления в системный промпт."""
    mems = retrieve_relevant_memories(user_text, username=username)
    if not mems:
        return ""
        
    block = "\n[🧠 ВЕЧНАЯ ПАМЯТЬ PLITTY (Вспомненный контекст об Алексее и проектах)]:\n"
    for m in mems:
        block += f"• {m}\n"
    block += "[Конец блока памяти]\n"
    return block
