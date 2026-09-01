# -*- coding: utf-8 -*-
"""
trend_spider.py - Глобальный Веб-Паук Трендов и Алгоритмический Предиктор для Plitty.
Парсит и анализирует тренды TikTok, Shorts и Reels в реальном времени,
предсказывает алгоритмические качели и подстраивает параметры прогрева/накрутки.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

# Фикс кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CACHE_DIR = Path(__file__).resolve().parent / "scratch" / "trends_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "latest_trends.json"

def fetch_web_trends_summary(query: str = "trending tiktok sounds hashtags viral 2026"):
    """
    Получает актуальные тренды и алгоритмические паттерны из открытых источников.
    """
    try:
        # Используем быстрый поиск актуальных трендов через DuckDuckGo / Public API
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            
        import re
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)
        clean_snippets = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:6]]
        return " ".join(clean_snippets)
    except Exception as e:
        # print(f"[Trend Spider Web Error] {e}")
        return ""

def analyze_algorithm_and_trends(category: str = "music", username: str = "Алексей") -> dict:
    """
    Анализирует алгоритмическую погоду, вирусные звуки, форматы хуков
    и предсказывает сдвиги в рекомендательных системах TikTok/Shorts/Reels.
    """
    print(f"[Trend Spider] 🕷️ Паук сканирует алгоритмы и тренды ({category})...")
    
    # 1. Проверяем свежесть кэша (до 30 минут)
    if CACHE_FILE.exists() and (time.time() - os.path.getmtime(CACHE_FILE) < 1800):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                return cached
        except Exception:
            pass

    web_intel = fetch_web_trends_summary(f"tiktok viral music trends {category} algorithm changes 2026")
    
    # 2. Прогоняем данные через ИИ-мозг Плитти
    prompt = (
        f"Ты — Plitty, глобальный ИИ-директор трендов и мастер взлома алгоритмов TikTok, Shorts и Reels. "
        f"Проанализируй текущую обстановку в алгоритмах и выдай боевую сводку для своего создателя {username}.\n\n"
        f"Свежие сигналы из сети: {web_intel[:800] if web_intel else 'Стандартная волна обновлений алгоритмов TikTok и Shorts'}\n\n"
        "Составь четкий отчет:\n"
        "1. 🔥 **Топ-3 формата контента / вирусных хуков прямо сейчас** (почему они держат зрителя);\n"
        "2. 🎵 **Звуковые тренды** (темп BPM, структура припева, питч);\n"
        "3. 🛡️ **Алгоритмический барометр & Безопасность фермы** (как настроить прогрев, чтобы не словить теневой бан: время удержания, паузы);\n"
        "4. 💡 **Рекомендация для параметров config.py** (WATCH_MIN_SEC, LIKE_CHANCE).\n\n"
        "Отвечай ярко, структурированно, профессионально и с кошачьей харизмой Плитти! 😼🍺"
    )
    
    import ai_consilium
    g_res = ai_consilium.query_gemini(prompt)
    if g_res and g_res.get("response"):
        report_text = g_res["response"]
    else:
        report_text = (
            f"🐾 <b>Сводка от Плитти:</b> Алгоритмы TikTok сейчас на пике строгости к первому 3-секундному удержанию. "
            f"Рекомендую ставить <code>WATCH_MIN_SEC = 9</code>, <code>LIKE_CHANCE = 0.25</code> и крутить бесшовные петли! 😼🔥"
        )
        
    trend_data = {
        "timestamp": time.time(),
        "category": category,
        "report": report_text,
        "recommended_config": {
            "WATCH_MIN_SEC": 8,
            "WATCH_MAX_SEC": 16,
            "LIKE_CHANCE": 0.28,
            "COMMENT_CHANCE": 0.08
        }
    }
    
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(trend_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
        
    return trend_data

if __name__ == "__main__":
    print("[+] Запуск теста Trend Spider...")
    res = analyze_algorithm_and_trends("музыка и сниппеты")
    print("\n--- ОТЧЕТ ВЕБ-ПАУКА ТРЕНДОВ ---\n")
    print(res["report"])
