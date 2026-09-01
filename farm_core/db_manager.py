# db_manager.py
"""
Модуль управления базой данных SQLite для Plitty 3.0.
Хранит долгосрочную историю работы фермы, метрики устройств,
логи сообщений чата и состояние Плитти.
"""

import sqlite3
import os
import time
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "plitty_farm.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Инициализирует структуры таблиц базы данных Plitty 3.0.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Таблица истории сообщений чата
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                avatar_state TEXT DEFAULT 'normal',
                timestamp REAL NOT NULL
            )
        """)
        
        # 2. Таблица событий и логов устройств
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                timestamp REAL NOT NULL
            )
        """)
        
        # 3. Таблица сессий прогрева
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warming_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time REAL NOT NULL,
                end_time REAL,
                devices_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'RUNNING'
            )
        """)
        
        # 4. Метрики и общая статистика фермы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS farm_metrics (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        conn.commit()
    print("[DB] База данных Plitty 3.0 успешно инициализирована.")

def log_chat_message(sender, text, avatar_state="normal", timestamp=None):
    if timestamp is None:
        timestamp = time.time()
        
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_messages (sender, text, avatar_state, timestamp)
            VALUES (?, ?, ?, ?)
        """, (sender, text, avatar_state, timestamp))
        conn.commit()

def get_chat_history(limit=50):
    FIVE_HOURS_SEC = 5 * 3600
    now = time.time()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        # Проверяем самое последнее сообщение
        cursor.execute("SELECT timestamp FROM chat_messages ORDER BY timestamp DESC LIMIT 1")
        last_msg = cursor.fetchone()
        
        if last_msg:
            last_ts = last_msg["timestamp"]
            # Если прошло больше 5 часов без активности — очищаем старый чат
            if now - last_ts > FIVE_HOURS_SEC:
                cursor.execute("DELETE FROM chat_messages")
                conn.commit()
                return []
                
        cursor.execute("""
            SELECT sender, text, avatar_state, timestamp 
            FROM chat_messages 
            ORDER BY timestamp ASC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def log_device_event(device_id, event_type, details=""):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO device_events (device_id, event_type, details, timestamp)
            VALUES (?, ?, ?, ?)
        """, (device_id, event_type, details, time.time()))
        conn.commit()

def record_session_start(devices_count):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO warming_sessions (start_time, devices_count, status)
            VALUES (?, ?, 'RUNNING')
        """, (time.time(), devices_count))
        conn.commit()
        return cursor.lastrowid

def record_session_end(session_id, status="COMPLETED"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE warming_sessions 
            SET end_time = ?, status = ?
            WHERE id = ?
        """, (time.time(), status, session_id))
        conn.commit()

def get_farm_stats_summary():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total_sessions FROM warming_sessions WHERE status = 'COMPLETED'")
        total_sessions = cursor.fetchone()["total_sessions"]
        
        cursor.execute("SELECT COUNT(*) as total_likes FROM device_events WHERE event_type = 'LIKE'")
        total_likes = cursor.fetchone()["total_likes"]
        
        cursor.execute("SELECT COUNT(*) as total_comments FROM device_events WHERE event_type = 'COMMENT'")
        total_comments = cursor.fetchone()["total_comments"]
        
        return {
            "total_sessions": total_sessions,
            "total_likes": total_likes,
            "total_comments": total_comments
        }

if __name__ == "__main__":
    init_db()
