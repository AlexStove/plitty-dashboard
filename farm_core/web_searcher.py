# -*- coding: utf-8 -*-
"""
web_searcher.py - Бесплатный Live Web-Search и Page Scraper для Plitty.
Использует DuckDuckGo API, Википедию и прямой скрейпинг страниц для получения актуальных знаний.
"""

import sys
import os
import re
import json
import urllib.request
import urllib.parse
from html import unescape

# Фикс кодировки
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def search_duckduckgo(query, max_results=5):
    """
    Поиск через DuckDuckGo Instant Answer API + Related Topics.
    """
    results = []
    try:
        q_enc = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={q_enc}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        abstract = data.get("AbstractText", "").strip()
        abstract_source = data.get("AbstractSource", "Web")
        abstract_url = data.get("AbstractURL", "")
        
        if abstract:
            results.append({
                "title": f"{data.get('Heading', query)} ({abstract_source})",
                "snippet": abstract,
                "url": abstract_url
            })
            
        related = data.get("RelatedTopics", [])
        for item in related:
            if len(results) >= max_results:
                break
            if "Text" in item:
                results.append({
                    "title": item.get("FirstURL", "").split("/")[-1].replace("_", " ") or query,
                    "snippet": item["Text"],
                    "url": item.get("FirstURL", "")
                })
            elif "Topics" in item:
                for sub in item["Topics"]:
                    if len(results) >= max_results:
                        break
                    if "Text" in sub:
                        results.append({
                            "title": sub.get("FirstURL", "").split("/")[-1].replace("_", " ") or query,
                            "snippet": sub["Text"],
                            "url": sub.get("FirstURL", "")
                        })
    except Exception as e:
        print(f"[DuckDuckGo Error] {e}")

    # Если пусто — опрашиваем Википедию
    if not results:
        results = search_wikipedia(query, max_results=max_results)
        
    return results

def search_wikipedia(query, max_results=3):
    """Поиск по русскоязычной Википедии."""
    results = []
    try:
        q_enc = urllib.parse.quote(query)
        url = f"https://ru.wikipedia.org/w/api.php?action=opensearch&search={q_enc}&limit={max_results}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "PlittyBot/3.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        if len(data) >= 4:
            titles = data[1]
            snippets = data[2]
            urls = data[3]
            for i in range(len(titles)):
                results.append({
                    "title": titles[i],
                    "snippet": snippets[i] or f"Статья: {titles[i]}",
                    "url": urls[i]
                })
    except Exception as e:
        print(f"[Wikipedia Error] {e}")
    return results

def scrape_web_page(url, max_chars=2500):
    """Быстро скачивает и очищает текст веб-страницы."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            
        clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:max_chars]
    except Exception as e:
        return f"Ошибка загрузки страницы: {e}"

def search_and_format_report(query, max_results=4):
    """Форматирует найденную информацию для Плитти."""
    results = search_duckduckgo(query, max_results=max_results)
    if not results:
        return f"🔍 По запросу «{query}» не удалось найти подробностей в открытых источниках."
        
    report = f"🌐 <b>Информация из сети по запросу «{query}»:</b>\n\n"
    for idx, r in enumerate(results, 1):
        report += f"<b>{idx}. {r['title']}</b>\n"
        if r['snippet']:
            report += f"   <i>{r['snippet']}</i>\n"
        if r.get('url'):
            report += f"   🔗 {r['url']}\n\n"
    return report.strip()
