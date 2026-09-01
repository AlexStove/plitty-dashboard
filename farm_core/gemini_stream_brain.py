# -*- coding: utf-8 -*-
"""
gemini_stream_brain.py - Профессиональный ИИ-мозг со 100% безопасными фразами под ВСЕ категории и Менеджером ролей (StreamRoleManager).
"""

import os
import sys
import time
import random
import json
import threading
import urllib.request
import urllib.error

sys.path.insert(0, r"C:\Users\a.feoktistov\.gemini\antigravity\scratch\прогрев_аккаунтов")
try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = ""

GLOBAL_HISTORY_LOCK = threading.Lock()
SESSION_USED_PHRASES = set()

# Богатые словари с гарантией 100% уместности в любой момент стрима
THEMATIC_POOLS = {
    # 1. Игры / Гейминг (любая игра: меню, лобби, катка)
    "gaming": {
        "greetings": [
            "ку всем", "привет", "хай", "здарова", "привет стример", "добрый день",
            "йоу", "ку бро", "здарова чат", "всем ку", "приветик", "хай чатик", "здарова парни"
        ],
        "early": [
            "погнали", "какой ранг?", "звук топ", "лайк на месте", "четко",
            "тащи катку", "поставил лайкос", "чо за лобби?", "красиво", "го побеждать",
            "удачи в катке", "картинка огонь", "лайк оформил", "кайфовый стрим", "ловите лайк",
            "настрой боевой", "го топ 1", "норм настрой", "погнали играть", "удачи стример"
        ],
        "mid": [
            "ахах", "лол", "да ладно", "чисто на скилле", "хорош", "красава", "жесть",
            "ору", "ахаха", "вот это да", "на тоненького", "норм реакция", "сейчас затащит",
            "чисто кайф", "найс", "ахах жесть", "на опыте", "красиво", "хорош хорош",
            "ну дает", "чистый топ", "отлично идет", "ахахаха", "согласен", "жиза", "красиво сыграно"
        ],
        "late": [
            "гг", "красава", "топ катка", "чистый кайф", "гг вп", "красивая игра",
            "отличная игра", "топчик", "грац", "на опыте", "спасибо за стрим", "достойно", "хорош"
        ]
    },
    # 2. Разговорный / Just Chatting / Лайфстайл
    "just_chatting": {
        "greetings": [
            "привет всем", "хай", "ку", "привет стример", "добрый день", "здарова чат",
            "ку бро", "привет из мск", "всем привет", "приветик", "хай чатик", "добрый вечер"
        ],
        "early": [
            "вайб топ", "звук отличный", "лайк на месте", "красиво выглядишь", "норм тема",
            "четко слышно", "поставил лайкос", "уютно тут", "лайк оформил", "хороший вечер",
            "отличный фон", "красивая картинка", "настроение топ", "кайфовая атмосфера", "ловите лайк"
        ],
        "mid": [
            "ахах", "лол", "согласен", "да ладно", "ахахаха", "ну в целом да", "жесть конечно",
            "жиза", "вот это история", "ага", "чистая правда", "бывает же", "ору",
            "в точку", "ну это классика", "ахах жесть", "норм тема", "100 процентов",
            "согласен полностью", "лол да", "красиво сказано", "чисто жиза", "ахах ор", "да уж", "это точно"
        ],
        "late": [
            "хорошего стрима", "топ эфир", "удачи", "приятного вечера", "спасибо за стрим",
            "красота", "топчик", "приятно слушать", "чистый кайф", "до скорого", "спасибо за эфир"
        ]
    },
    # 3. Тревел / Путешествия / Прогулки (Travel & Outdoors)
    "travel": {
        "greetings": [
            "привет всем", "хай", "ку", "привет из мск", "добрый день", "здарова",
            "приветик", "всем ку", "добрый вечер", "привет путешественникам"
        ],
        "early": [
            "где это?", "красивый вид", "вайб топ", "норм погода", "четкая камера",
            "красота", "крутая локация", "лайк на месте", "уютно тут", "кайф атмосфера",
            "поставил лайкос", "отличная картинка", "тепло там?", "кайфово гулять", "ловите лайк"
        ],
        "mid": [
            "ахах", "лол", "очень красиво", "людей много?", "да ладно", "уютно",
            "атмосферно", "кайфово гулять", "вот это вид", "красотища", "ахаха",
            "чистый кайф", "классное место", "красивые кадры", "прямо открытка", "здорово", "согласен"
        ],
        "late": [
            "хорошей прогулки", "удачи в пути", "топ стрим", "красивые места", "кайф",
            "приятного путешествия", "спасибо за показ", "красота", "отличный эфир"
        ]
    },
    # 4. Кулинария / Еда (Cooking & Food)
    "cooking": {
        "greetings": [
            "привет всем", "хай", "ку", "привет повару", "добрый день", "здарова чат", "всем ку"
        ],
        "early": [
            "что готовим?", "звук топ", "лайк на месте", "аппетитно выглядит", "поставил лайкос",
            "рецепт пушка", "лайк оформил", "вайб уютный", "ловите лайк", "красивая кухня"
        ],
        "mid": [
            "ахах", "лол", "выглядит вкусно", "слюнки потекли", "да ладно", "красивая подача",
            "ахаха", "сыра побольше", "топчик", "чистый кайф", "красота", "согласен", "на опыте"
        ],
        "late": [
            "приятного аппетита", "топ стрим", "спасибо за рецепт", "красота", "удачи", "шедевр"
        ]
    },
    # 5. Музыка / DJ / Творчество (Music & Art)
    "music": {
        "greetings": [
            "привет всем", "хай", "ку", "привет музыкантам", "добрый день", "йоу", "всем ку"
        ],
        "early": [
            "вайб топ", "звук огонь", "лайк на месте", "красивая музыка", "поставил лайкос",
            "четкий звук", "лайк оформил", "настроение топ", "ловите лайк"
        ],
        "mid": [
            "трек пушка", "звук топ", "вайб", "чисто кайф", "огонь", "ахах", "лол",
            "красиво звучит", "атмосферно", "кайфово слушать", "на опыте", "красава", "топчик"
        ],
        "late": [
            "спасибо за сет", "топ стрим", "отличный вайб", "удачи", "чистый кайф", "красота"
        ]
    },
    # 6. Казино / Слоты (Slots & Casino)
    "casino": {
        "greetings": [
            "ку всем", "привет", "хай", "здарова", "привет стример", "добрый день",
            "йоу", "ку бро", "всем ку", "здарова чат", "приветик"
        ],
        "early": [
            "погнали", "дай занос", "лайк на месте", "поставил лайкос", "удачи стример",
            "звук топ", "настрой боевой", "го иксы", "ловите лайк", "лайк оформил",
            "по какой ставке?", "четко", "красивая картинка", "кайфовый стрим"
        ],
        "mid": [
            "ахах", "лол", "да ладно", "насыпало", "красава", "красиво", "хорош",
            "жесть", "ору", "ахаха", "сейчас даст", "чисто кайф", "найс", "вот это да",
            "чистый топ", "отлично идет", "жиза", "согласен", "ахах жесть", "на опыте"
        ],
        "late": [
            "красава", "топ стрим", "чистый кайф", "грац с заносом", "топчик",
            "отличный эфир", "спасибо за стрим", "удачи", "хорош"
        ]
    },
    # 7. Универсальный 100% безопасный пул
    "universal": {
        "greetings": [
            "ку всем", "привет", "хай", "здарова", "привет стример", "добрый день",
            "йоу", "ку бро", "всем привет", "приветик", "здарова чат"
        ],
        "early": [
            "красиво", "звук топ", "четко", "лайк на месте", "вайб", "норм идет",
            "найс", "погнали", "кайф", "поставил лайкос", "лайк оформил", "отличная картинка",
            "настроение топ", "четкий стрим", "ловите лайк"
        ],
        "mid": [
            "ахах", "лол", "вот это да", "да ладно", "норм реакция", "ахаха", "жесть",
            "согласен", "чисто кайф", "хорош", "ахахаха", "ору", "ну дает",
            "красиво сделано", "чистый топ", "на опыте", "красава", "отлично идет"
        ],
        "late": [
            "топ стрим", "удачи", "красава", "чистый кайф", "топчик", "отличный эфир",
            "на опыте", "спасибо за стрим", "хорошего вечера", "до встречи"
        ]
    }
}

class StreamCategoryDetector:
    @staticmethod
    def detect_stream_context(streamer: str, platform: str = "kick") -> dict:
        streamer_clean = streamer.lstrip('@').strip()
        ctx = {"category_name": "General", "theme_type": "universal", "title": ""}
        if platform.lower() == "kick":
            try:
                url = f"https://kick.com/api/v2/channels/{streamer_clean}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ls = data.get("livestream")
                    if ls:
                        ctx["title"] = ls.get("session_title", "")
                        cats = ls.get("categories", [])
                        if cats:
                            ctx["category_name"] = cats[0].get("name", "General")
            except Exception:
                pass
                
        cat_lower = ctx["category_name"].lower()
        if any(w in cat_lower for w in ["dota", "cs", "counter", "pubg", "game", "valorant", "apex", "battlegrounds", "league", "gta", "minecraft", "fortnite", "overwatch", "rust", "r6", "siege", "shooter", "moba"]):
            ctx["theme_type"] = "gaming"
        elif any(w in cat_lower for w in ["travel", "outdoors", "путешеств", "прогулк"]):
            ctx["theme_type"] = "travel"
        elif any(w in cat_lower for w in ["cook", "food", "bake", "еда", "кулинар"]):
            ctx["theme_type"] = "cooking"
        elif any(w in cat_lower for w in ["slot", "casino", "казино", "слот"]):
            ctx["theme_type"] = "casino"
        elif any(w in cat_lower for w in ["music", "dj", "art", "рисун", "музык"]):
            ctx["theme_type"] = "music"
        elif any(w in cat_lower for w in ["just chatting", "irl", "talk", "общение", "беседа"]):
            ctx["theme_type"] = "just_chatting"
        else:
            ctx["theme_type"] = "universal"
            
        return ctx


class StreamRoleManager:
    """
    Универсальный менеджер распределения активности чата для любых временных интервалов.
    """
    @staticmethod
    def calculate_roles(device_ids: list, duration_minutes: int, mode: str = "organic"):
        num_devices = len(device_ids)
        roles = {did: {"role": "lurker", "max_comments": 0, "scheduled_times": []} for did in device_ids}
        mode = mode.lower() if mode else "organic"
        duration_sec = duration_minutes * 60
        
        # 1. Тихий режим (Stealth / Lurker): 0 комментариев
        if mode in ("stealth", "lurk", "silent") or num_devices == 0:
            return roles

        # Границы активности: от 10-й секунды до 93% длительности стрима
        start_offset = 10.0
        end_offset = duration_sec * 0.93
        time_span = max(10.0, end_offset - start_offset)

        # 2. РЕЙД-РЕЖИМ (Raid / Active)
        if mode in ("raid", "active", "boost_chat"):
            if num_devices <= 10:
                active_devices = list(device_ids)
            else:
                active_count = max(4, int(num_devices * 0.40))
                shuffled = list(device_ids)
                random.shuffle(shuffled)
                active_devices = shuffled[:active_count]

            if duration_minutes <= 5:
                comments_per_dev = 3       # ~18-20 сек между сообщениями в чате
            elif duration_minutes <= 10:
                comments_per_dev = 4       # ~27-30 сек между сообщениями в чате
            elif duration_minutes <= 15:
                comments_per_dev = 5       # ~35-40 сек между сообщениями в чате
            elif duration_minutes <= 20:
                comments_per_dev = 6       # ~40 сек между сообщениями в чате
            elif duration_minutes <= 30:
                comments_per_dev = 8       # ~45 сек между сообщениями в чате
            else:
                comments_per_dev = max(10, int(duration_minutes * 0.35))

            total_comments = len(active_devices) * comments_per_dev
            step = time_span / max(1, total_comments)

            for did in active_devices:
                roles[did]["role"] = "raid_chatter"
                roles[did]["max_comments"] = comments_per_dev
                roles[did]["scheduled_times"] = []

            for idx in range(total_comments):
                dev_target = active_devices[idx % len(active_devices)]
                t = start_offset + (idx * step) + random.uniform(-1.5, 1.5)
                roles[dev_target]["scheduled_times"].append(max(6.0, round(t, 1)))

            for did in active_devices:
                roles[did]["scheduled_times"].sort()

            return roles

        # 3. ОРГАНИЧНЫЙ РЕЖИМ (Organic)
        if num_devices <= 5:
            chatters_count = min(2, num_devices)
        elif num_devices <= 30:
            chatters_count = max(3, int(num_devices * 0.25))
        elif num_devices <= 100:
            chatters_count = max(5, int(num_devices * 0.20))
        else:
            chatters_count = min(30, int(num_devices * 0.10))

        shuffled = list(device_ids)
        random.shuffle(shuffled)
        chatters = shuffled[:chatters_count]

        if duration_minutes <= 5:
            comments_per_dev = 2
        elif duration_minutes <= 10:
            comments_per_dev = 3
        elif duration_minutes <= 15:
            comments_per_dev = 3
        elif duration_minutes <= 20:
            comments_per_dev = 4
        else:
            comments_per_dev = max(4, int(duration_minutes * 0.20))

        total_organic_comments = len(chatters) * comments_per_dev
        step = time_span / max(1, total_organic_comments)

        for did in chatters:
            roles[did]["role"] = "organic_viewer"
            roles[did]["max_comments"] = comments_per_dev
            roles[did]["scheduled_times"] = []

        for idx in range(total_organic_comments):
            dev_target = chatters[idx % len(chatters)]
            t = start_offset + (idx * step) + random.uniform(-3.0, 3.0)
            roles[dev_target]["scheduled_times"].append(max(8.0, round(t, 1)))

        for did in chatters:
            roles[did]["scheduled_times"].sort()

        return roles


class GeminiStreamBrain:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.cached_context = {}
        
    def get_or_detect_context(self, streamer: str, platform: str) -> dict:
        key = f"{platform}:{streamer}"
        if key not in self.cached_context:
            self.cached_context[key] = StreamCategoryDetector.detect_stream_context(streamer, platform)
        return self.cached_context[key]

    def generate_comment(self, streamer: str, platform: str = "kick", phase: str = "mid",
                         context_hint: str = "") -> str:
        ctx = self.get_or_detect_context(streamer, platform)
        theme = ctx.get("theme_type", "universal")
        category_name = ctx.get("category_name", "Стрим")
        stream_title = ctx.get("title", "")
        
        global SESSION_USED_PHRASES, GLOBAL_HISTORY_LOCK

        # 1. Попытка через Gemini Flash
        if self.api_key:
            try:
                ai_text = self._call_gemini_api(streamer, platform, phase, category_name, stream_title, theme)
                with GLOBAL_HISTORY_LOCK:
                    if ai_text and ai_text not in SESSION_USED_PHRASES:
                        SESSION_USED_PHRASES.add(ai_text)
                        return ai_text
            except Exception:
                pass
                
        # 2. Резервный пул с жесткой глобальной потокобезопасной дедупликацией
        pool_dict = THEMATIC_POOLS.get(theme, THEMATIC_POOLS["universal"])
        pool = pool_dict.get(phase, pool_dict.get("mid", THEMATIC_POOLS["universal"]["mid"]))
        
        with GLOBAL_HISTORY_LOCK:
            available = [p for p in pool if p not in SESSION_USED_PHRASES]
            if not available:
                u_pool = THEMATIC_POOLS["universal"].get(phase, THEMATIC_POOLS["universal"]["mid"])
                available = [p for p in u_pool if p not in SESSION_USED_PHRASES]
                if not available:
                    SESSION_USED_PHRASES.clear()
                    available = pool
                    
            choice = random.choice(available)
            SESSION_USED_PHRASES.add(choice)
            return choice

    def _call_gemini_api(self, streamer: str, platform: str, phase: str,
                         category_name: str, stream_title: str, theme: str) -> str:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
        
        prompt = (
            f"Ты зритель живого стрима на {platform.capitalize()} у автора @{streamer}.\n"
            f"Категория: {category_name} | Название стрима: {stream_title}\n"
            f"Фаза стрима: {phase}\n"
            "Инструкция по реалистичности:\n"
            "Напиши ОДНУ очень короткую живую реплику зрителя (1-3 слова). "
            "Фраза ДОЛЖНА БЫТЬ 100% УМЕСТНОЙ В ЛЮБОЙ МОМЕНТ (сидит ли стример в меню, в лобби, общается или играет). "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать узкие действия (НЕ пиши 'красивый флик', 'норм зажим', 'минус два', 'пт собирай'!). "
            "Используй естественные зрительские фразы: одобрение, смех, вопрос про ранг/настроение, вайб, 'ку', 'ахах', 'лол', 'погнали', 'красиво', 'да ладно', 'на опыте', 'топ стрим'. "
            "Только строчные буквы, без кавычек и лишних знаков."
        )
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.95, "maxOutputTokens": 15}
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        )
        with urllib.request.urlopen(req, timeout=3.0) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidate = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            candidate = candidate.strip('"\n\r.,!?').lower()
            return candidate

stream_brain = GeminiStreamBrain()
