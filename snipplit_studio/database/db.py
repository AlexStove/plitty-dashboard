import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import sys

# Добавляем родительскую директорию в path, чтобы импортировать config
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

class Database:
    def __init__(self, db_path: Path = config.DB_PATH):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        # Гарантируем, что папка для БД существует
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица треков
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT,
                file_path TEXT NOT NULL,
                lyrics_path TEXT,
                duration REAL,
                source TEXT NOT NULL,
                source_url TEXT,
                created_at TEXT NOT NULL
            )
            """)
            
            # Таблица видеофутажей
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS footages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                duration REAL,
                width INTEGER,
                height INTEGER,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL
            )
            """)

            # Авто-миграция колонки category при обновлении БД
            try:
                cursor.execute("ALTER TABLE footages ADD COLUMN category TEXT DEFAULT 'general'")
            except sqlite3.OperationalError:
                pass

            
            # Таблица задач генерации (чтобы отслеживать прогресс)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS render_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                footage_id INTEGER NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                status TEXT NOT NULL,  -- 'pending', 'processing', 'completed', 'failed'
                result_path TEXT,
                error_message TEXT,
                progress_percent INTEGER DEFAULT 0,
                progress_message TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """)

            # Безопасная миграция колонок progress
            try:
                cursor.execute("ALTER TABLE render_tasks ADD COLUMN progress_percent INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE render_tasks ADD COLUMN progress_message TEXT DEFAULT ''")
            except Exception:
                pass

            # Таблица нарезанных аудио-отрезков (для многократной видеогенерации)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audio_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                lyrics_json TEXT,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                duration REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
            # Таблица профилей ИИ-Инфлюенсеров (100+ профилей)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS influencers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                avatar_path TEXT,
                video_path TEXT NOT NULL,
                handle TEXT,
                created_at TEXT NOT NULL
            )
            """)

            # Таблица сохраненных видео-сниппетов
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_video_snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                duration REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """)

            # Таблица пользовательских пресетов
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                footage_category TEXT DEFAULT 'all',
                subtitle_style TEXT DEFAULT 'mrbeast',
                layout TEXT DEFAULT 'split50',
                video_filter TEXT DEFAULT 'none',
                created_at TEXT NOT NULL
            )
            """)

            conn.commit()

    # --- Операции с сохраненными готовыми сниппетами ---
    def add_saved_video_snippet(self, title: str, file_path: str, duration: float = 15.0) -> int:
        created_at = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO saved_video_snippets (title, file_path, duration, created_at) VALUES (?, ?, ?, ?)",
                (title, file_path, duration, created_at)
            )
            conn.commit()
            return cursor.lastrowid

    def get_all_saved_video_snippets(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM saved_video_snippets ORDER BY id DESC")
            items = [dict(row) for row in cursor.fetchall()]
            import random
            random.shuffle(items)
            return items

    def get_all_footages(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cat_lower = category.lower()
                if cat_lower == "hooks":
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) = 'hooks'")
                    items = [dict(row) for row in cursor.fetchall()]
                    import random
                    random.shuffle(items)
                    return items
                elif cat_lower in ["fashion", "beauty", "мода", "бьюти"]:
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) IN ('fashion', 'beauty', 'мода', 'бьюти')")
                    res = [dict(row) for row in cursor.fetchall()]
                    if res:
                        import random
                        random.shuffle(res)
                        return res
                elif cat_lower not in ["all", "general", "любая", "все"]:
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) = LOWER(?)", (cat_lower,))
                    res = [dict(row) for row in cursor.fetchall()]
                    if res:
                        import random
                        random.shuffle(res)
                        return res

            # Для всех обычных музыкальных сниппетов СТРОГО ИСКЛЮЧАЕМ КАТЕГОРИЮ 'hooks'!
            cursor.execute("SELECT * FROM footages WHERE LOWER(category) != 'hooks'")
            items = [dict(row) for row in cursor.fetchall()]
            import random
            random.shuffle(items)
            return items

    def get_random_footages(self, count: int = 1, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Возвращает случайные футажи со СТРОГО РАВНЫМ шансом выпадения любого ролика."""
        all_items = self.get_all_footages(category=category)
        if not all_items:
            return []
        import random
        random.shuffle(all_items)
        if len(all_items) >= count:
            return random.sample(all_items, count)
        return [random.choice(all_items) for _ in range(count)]

    def get_all_influencers(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category and category.lower() not in ["all", "general", "любая", "все"]:
                cursor.execute("SELECT * FROM influencers WHERE LOWER(category) = LOWER(?)", (category.lower(),))
                res = [dict(row) for row in cursor.fetchall()]
                if res:
                    import random
                    random.shuffle(res)
                    return res
            cursor.execute("SELECT * FROM influencers")
            items = [dict(row) for row in cursor.fetchall()]
            import random
            random.shuffle(items)
            return items


    def get_saved_video_snippet(self, snippet_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM saved_video_snippets WHERE id = ?", (snippet_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_saved_video_snippet(self, snippet_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM saved_video_snippets WHERE id = ?", (snippet_id,))
            conn.commit()



    # --- Операции с треками ---
    def add_track(self, title: str, artist: Optional[str], file_path: str, 
                  lyrics_path: Optional[str] = None, duration: Optional[float] = None, 
                  source: str = "upload", source_url: Optional[str] = None) -> int:
        
        created_at = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tracks (title, artist, file_path, lyrics_path, duration, source, source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, artist, file_path, lyrics_path, duration, source, source_url, created_at)
            )
            conn.commit()
            return cursor.lastrowid

    def clear_full_tracks(self):
        """Очищает все не-обрезанные треки из таблицы tracks, сохраняя отрезки audio_segments."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracks")
            conn.commit()

    def get_all_tracks(self) -> List[Dict[str, Any]]:

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracks ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_track_lyrics(self, track_id: int, lyrics_path: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tracks SET lyrics_path = ? WHERE id = ?", (lyrics_path, track_id))
            conn.commit()

    def update_track_metadata(self, track_id: int, title: str, artist: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tracks SET title = ?, artist = ? WHERE id = ?", (title, artist, track_id))
            conn.commit()

    def delete_track(self, track_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Сначала получим пути к файлам для удаления с диска
            cursor.execute("SELECT file_path, lyrics_path FROM tracks WHERE id = ?", (track_id,))
            row = cursor.fetchone()
            if row:
                try:
                    Path(row['file_path']).unlink(missing_ok=True)
                    if row['lyrics_path']:
                        Path(row['lyrics_path']).unlink(missing_ok=True)
                except Exception:
                    pass
            cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            conn.commit()

    # --- Операции с футажами ---
    def add_footage(self, filename: str, file_path: str, duration: Optional[float] = None, 
                    width: Optional[int] = None, height: Optional[int] = None, category: str = "general") -> int:
        created_at = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO footages (filename, file_path, duration, width, height, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (filename, file_path, duration, width, height, category or "general", created_at)
            )
            conn.commit()
            return cursor.lastrowid

    def update_footage_category(self, footage_id: int, category: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE footages SET category = ? WHERE id = ?", (category, footage_id))
            conn.commit()

    def get_all_footages(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cat_lower = category.lower()
                if cat_lower == "hooks":
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) = 'hooks' ORDER BY id DESC")
                    return [dict(row) for row in cursor.fetchall()]
                elif cat_lower in ["fashion", "beauty", "мода", "бьюти"]:
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) IN ('fashion', 'beauty', 'мода', 'бьюти') ORDER BY id DESC")
                    res = [dict(row) for row in cursor.fetchall()]
                    if res:
                        return res
                elif cat_lower not in ["all", "general", "любая", "все"]:
                    cursor.execute("SELECT * FROM footages WHERE LOWER(category) = LOWER(?) ORDER BY id DESC", (cat_lower,))
                    res = [dict(row) for row in cursor.fetchall()]
                    if res:
                        return res

            # Для всех обычных музыкальных сниппетов СТРОГО ИСКЛЮЧАЕМ КАТЕГОРИЮ 'hooks'!
            cursor.execute("SELECT * FROM footages WHERE LOWER(category) != 'hooks' ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_random_footages(self, count: int = 1, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Возвращает случайные футажи с СТРОГО РАВНЫМ шансом выпадения (ORDER BY RANDOM())."""
        all_items = self.get_all_footages(category=category)
        if not all_items:
            return []
        import random
        random.shuffle(all_items)
        if len(all_items) >= count:
            return random.sample(all_items, count)
        return [random.choice(all_items) for _ in range(count)]

    def get_footages_by_category(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.get_all_footages(category=category)





    def get_footage(self, footage_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM footages WHERE id = ?", (footage_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_footage(self, footage_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_path FROM footages WHERE id = ?", (footage_id,))
            row = cursor.fetchone()
            if row:
                try:
                    Path(row['file_path']).unlink(missing_ok=True)
                except Exception:
                    pass
            cursor.execute("DELETE FROM footages WHERE id = ?", (footage_id,))
            conn.commit()

    # --- Задачи рендеринга ---
    def add_render_task(self, task_id: str, user_id: int, track_id: int, footage_id: int, 
                        start_time: float, end_time: float) -> str:
        created_at = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO render_tasks (id, user_id, track_id, footage_id, start_time, end_time, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (task_id, user_id, track_id, footage_id, start_time, end_time, created_at)
            )
            conn.commit()
            return task_id

    def update_task_status(self, task_id: str, status: str, result_path: Optional[str] = None, 
                           error_message: Optional[str] = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE render_tasks 
                SET status = ?, result_path = ?, error_message = ? 
                WHERE id = ?
                """,
                (status, result_path, error_message, task_id)
            )
    def update_task_progress(self, task_id: str, percent: int, message: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE render_tasks 
                SET progress_percent = ?, progress_message = ? 
                WHERE id = ?
                """,
                (percent, message, task_id)
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM render_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def reset_stale_render_tasks(self):
        """Сбрасывает застрявшие задачи рендеринга при перезапуске сервера."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE render_tasks 
                SET status = 'failed', error_message = 'Перезапуск сервера' 
                WHERE status IN ('processing', 'pending')
                """
            )
            conn.commit()


    # --- Операции с аудио-отрезками ---
    def add_audio_segment(self, track_id: int, name: str, file_path: str, 
                          start_time: float, end_time: float, 
                          lyrics_json: Optional[str] = None) -> int:
        created_at = datetime.datetime.now().isoformat()
        duration = max(0.1, end_time - start_time)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audio_segments (track_id, name, file_path, lyrics_json, start_time, end_time, duration, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (track_id, name, file_path, lyrics_json, start_time, end_time, duration, created_at)
            )
            conn.commit()
            return cursor.lastrowid

    def get_all_audio_segments(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audio_segments ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_audio_segment(self, segment_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audio_segments WHERE id = ?", (segment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_audio_segment_lyrics(self, segment_id: int, lyrics_json: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE audio_segments SET lyrics_json = ? WHERE id = ?", (lyrics_json, segment_id))
            conn.commit()


    def delete_audio_segment(self, segment_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_path FROM audio_segments WHERE id = ?", (segment_id,))
            row = cursor.fetchone()
            if row:
                try:
                    Path(row['file_path']).unlink(missing_ok=True)
                except Exception:
                    pass
            cursor.execute("DELETE FROM audio_segments WHERE id = ?", (segment_id,))
            conn.commit()

    # --- Операции с ИИ-Инфлюенсерами (100+ профилей) ---
    def add_influencer(self, name: str, video_path: str, category: str = "general", 
                       avatar_path: Optional[str] = None, handle: Optional[str] = None) -> int:
        now = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO influencers (name, category, avatar_path, video_path, handle, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (name, category, avatar_path, video_path, handle, now))
            conn.commit()
            return cursor.lastrowid

    def get_all_influencers(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category and category.lower() not in ["all", "general", "любая", "все"]:
                cursor.execute("SELECT * FROM influencers WHERE LOWER(category) = LOWER(?) ORDER BY id ASC", (category.lower(),))
                res = [dict(row) for row in cursor.fetchall()]
                if res:
                    return res
            cursor.execute("SELECT * FROM influencers ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_influencer(self, influencer_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM influencers WHERE id = ?", (influencer_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_influencer(self, influencer_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM influencers WHERE id = ?", (influencer_id,))
            conn.commit()

    # --- Операции с Пользовательскими Пресетами ---
    def add_user_preset(self, user_id: int, name: str, footage_category: str = "all", 
                        subtitle_style: str = "mrbeast", layout: str = "split50", 
                        video_filter: str = "none") -> int:
        now = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO user_presets (user_id, name, footage_category, subtitle_style, layout, video_filter, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, name, footage_category, subtitle_style, layout, video_filter, now))
            conn.commit()
            return cursor.lastrowid

    def get_user_presets(self, user_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_presets WHERE user_id = ? ORDER BY id DESC", (user_id,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_user_preset(self, preset_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_presets WHERE id = ?", (preset_id,))
            conn.commit()

# Инициализируем глобальный объект базы данных
db = Database()


if __name__ == "__main__":
    print("Database initialized successfully at:", config.DB_PATH)
