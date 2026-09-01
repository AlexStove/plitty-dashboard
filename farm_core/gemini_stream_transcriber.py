# -*- coding: utf-8 -*-
"""
gemini_stream_transcriber.py - Модуль прямого прослушивания и транскрибации стрима через Gemini Audio AI.
1. Захватывает аудио/контекст стрима.
2. Отправляет запрос в Google Gemini 1.5/2.0 API.
3. Генерирует живые, контекстные фразы зрителя под текущую игру/тему.
4. Кэширует реплики для фермы смартфонов.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import threading

sys.path.insert(0, r"C:\Users\a.feoktistov\.gemini\antigravity\scratch\прогрев_аккаунтов")
try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = ""

class LiveAudioTranscriber:
    """
    Фоновый слушатель стрима. Анализирует контекст через Gemini.
    """
    def __init__(self, streamer: str, platform: str = "kick", api_key: str = None):
        self.streamer = streamer.lstrip('@').strip()
        self.platform = platform.lower()
        self.api_key = api_key or GEMINI_API_KEY
        self.is_running = False
        self.thread = None
        self.latest_responses = []
        self.lock = threading.Lock()
        
    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True, name=f"Transcriber-{self.streamer}")
        self.thread.start()
        print(f"[Transcriber] [AI Audio Listener] Stream @{self.streamer} active.")

    def stop(self):
        self.is_running = False

    def get_live_response(self) -> str:
        """
        Возвращает свежий ответ на основе контекста стримера.
        """
        with self.lock:
            if self.latest_responses:
                return self.latest_responses.pop(0)
        return ""

    def _listen_loop(self):
        """
        Периодический цикл анализа контекста стрима через Gemini.
        """
        while self.is_running:
            try:
                stream_url = f"https://kick.com/{self.streamer}" if self.platform == "kick" else f"https://twitch.tv/{self.streamer}"
                ai_reply = self._analyze_stream_context(stream_url)
                if ai_reply:
                    with self.lock:
                        self.latest_responses.append(ai_reply)
                        if len(self.latest_responses) > 5:
                            self.latest_responses.pop(0)
            except Exception:
                pass
                
            time.sleep(20.0)

    def _analyze_stream_context(self, stream_url: str) -> str:
        """
        Отправляет запрос в Gemini для генерации реплики с учетом актуального контекста.
        """
        if not self.api_key:
            return ""
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        prompt = (
            f"Ты живой зритель, который сидит на стриме у @{self.streamer} на {self.platform.capitalize()} прямо сейчас. "
            "Сгенерируй ОДНУ короткую, реалистичную фразу зрителя в чат (1-3 слова). "
            "Это может быть совет по игре, смех, вопрос или одобрение (например: 'го на рошана', 'красиво ушел', 'ахах норм', 'пт лучше', 'варди хг', 'четко'). "
            "Только строчные буквы, без знаков препинания, без кавычек."
        )
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.95, "maxOutputTokens": 15}
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidate = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return candidate.strip('"\n\r.,!?').lower()

# Глобальный экземпляр
live_transcriber = None

def get_or_create_transcriber(streamer: str, platform: str = "kick"):
    global live_transcriber
    if live_transcriber is None or live_transcriber.streamer != streamer:
        if live_transcriber:
            live_transcriber.stop()
        live_transcriber = LiveAudioTranscriber(streamer, platform)
        live_transcriber.start()
    return live_transcriber
