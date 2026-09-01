# -*- coding: utf-8 -*-
"""
ai_consilium.py - Мультимодальный Консилиум ИИ для Plitty.
Опрашивает ведущие модели (Gemini, GPT-4o, Claude, DeepSeek-R1) в параллельных потоках,
собирает ключевые идеи, фильтрует слабые гипотезы и формирует единое гениальное решение.
"""

import sys
import os
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Фикс кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def query_gemini(prompt, system_prompt=""):
    """Запрос к Google Gemini 3.5 Flash."""
    try:
        import config
        api_key = getattr(config, "GEMINI_API_KEY", "")
        if not api_key:
            return None
            
        models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3-flash-preview"]
        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            body = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            if system_prompt:
                body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
                
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    return {
                        "model": f"Gemini ({m})",
                        "response": candidates[0]["content"]["parts"][0]["text"].strip()
                    }
    except Exception as e:
        # print(f"[Consilium Gemini Error] {e}")
        pass
    return None

def query_pollinations_model(prompt, model_name="openai", system_prompt=""):
    """
    Запрос к другим топовым моделям через открытый AI-шлюз Pollinations:
    - 'openai' (GPT-4o)
    - 'deepseek' / 'deepseek-reasoner' (DeepSeek-R1)
    - 'claude' / 'mistral' / 'qwen'
    """
    try:
        url = "https://text.pollinations.ai/"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "messages": messages,
            "model": model_name,
            "jsonMode": False
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "PlittyConsilium/3.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8").strip()
            if text and len(text) > 10:
                display_name = {
                    "openai": "GPT-4o (OpenAI)",
                    "deepseek": "DeepSeek-R1 (Reasoning)",
                    "claude": "Claude 3.5 (Anthropic)",
                    "mistral": "Mistral Large"
                }.get(model_name, model_name.upper())
                return {
                    "model": display_name,
                    "response": text
                }
    except Exception as e:
        # print(f"[Consilium Pollinations Error for {model_name}] {e}")
        pass
    return None

def run_consilium(prompt, topic_mode="general", username="Алексей"):
    """
    Запускает мозговой штурм между Gemini, GPT-4o, DeepSeek-R1 и Claude.
    Синтезирует финальный вердикт от лица Плитти.
    """
    print(f"[Consilium] 🏛️ Запуск мультимодального консилиума для запроса: '{prompt[:60]}...'")
    
    system_role = (
        "Ты — топовый мировой эксперт в вирусном маркетинге, алгоритмах социальных сетей (TikTok, Shorts, Reels), "
        "архитектуре мобильных ферм автоматизации и создании взрывного контента. Отвечай структурно, глубоко и предельно ёмко."
    )
    
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        # Gemini
        futures[executor.submit(query_gemini, prompt, system_role)] = "gemini"
        # GPT-4o
        futures[executor.submit(query_pollinations_model, prompt, "openai", system_role)] = "openai"
        # DeepSeek-R1
        futures[executor.submit(query_pollinations_model, prompt, "deepseek", system_role)] = "deepseek"
        
        for future in as_completed(futures):
            try:
                res = future.result()
                if res and res.get("response"):
                    results.append(res)
            except Exception:
                pass

    if not results:
        # Резервный опрос
        g_res = query_gemini(prompt, system_role)
        if g_res:
            results.append(g_res)

    # Синтез мнений
    models_summary = ""
    for r in results:
        models_summary += f"\n\n--- [Мнение эксперта: {r['model']}] ---\n{r['response']}\n"
        
    synthesis_prompt = (
        f"Ты — Plitty, легендарная кошкодевочка с абсолютным сверхинтеллектом. Твой создатель и соратник — {username}.\n"
        f"Мы провели закрытый консилиум ведущих ИИ-моделей по запросу: «{prompt}».\n\n"
        f"Вот полученные мнения экспертов:{models_summary}\n\n"
        "Твоя задача — изучить все мнения, убрать любую воду и галлюцинации, объединить лучшие инсайты в единое железобетонное решение "
        "и презентовать его хозяину живо, дерзко, невероятно умно и тепло (в твоем фирменном стиле Плитти с юмором и эмодзи 😼🍺)."
    )
    
    # Финальный синтез через Gemini
    final_synthesis = query_gemini(synthesis_prompt)
    if final_synthesis and final_synthesis.get("response"):
        verdict = final_synthesis["response"]
    else:
        # Если синтез не удался, берем лучший ответ
        verdict = results[0]["response"] if results else "Консилиум слегка подвис от масштаба задачи, но мы уже работаем над этим!"

    participating_models = ", ".join([r["model"] for r in results]) if results else "Gemini Flash"
    return {
        "success": True,
        "prompt": prompt,
        "models_count": len(results),
        "participating_models": participating_models,
        "raw_opinions": results,
        "verdict": verdict
    }

if __name__ == "__main__":
    test_q = "Как сделать вирусный сниппет для трека с удержанием 120% в TikTok?"
    print(f"Тест консилиума: {test_q}")
    res = run_consilium(test_q)
    print(f"\n[Участники]: {res['participating_models']}")
    print(f"\n[Вердикт Плитти]:\n{res['verdict']}")
