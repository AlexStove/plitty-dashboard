# voice_engine.py
"""
Модуль голосового ИИ для Plitty 3.0.
Генерирует голосовые сообщения (Text-to-Speech) с саркастичным
нейро-голосом Плитти на базе edge-tts.
"""

import asyncio
import re
import os
import time
import edge_tts

VOICE_NAME = "ru-RU-SvetlanaNeural"

def strip_html_tags(text):
    """
    Удаляет HTML теги из текста для корректного озвучивания.
    """
    clean = re.sub(r'<[^>]+>', '', text)
    clean = clean.replace('&nbsp;', ' ').replace('&quot;', '"')
    return clean.strip()

async def async_generate_voice(text, output_path):
    clean_text = strip_html_tags(text)
    if not clean_text:
        clean_text = "Молчу, мяу."
        
    communicate = edge_tts.Communicate(clean_text, VOICE_NAME, rate="+5%", pitch="+2Hz")
    await communicate.save(output_path)
    return output_path

def generate_plitty_voice(text, output_filename=None):
    """
    Синхронный оберточный метод для генерации аудиофайла Plitty.
    """
    if output_filename is None:
        filename = f"plitty_voice_{int(time.time() * 1000)}.mp3"
        output_filename = os.path.join(os.path.dirname(__file__), "web_dashboard", filename)
        
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    asyncio.run(async_generate_voice(text, output_filename))
    return output_filename

if __name__ == "__main__":
    test_file = generate_plitty_voice("Привет, Лёша! Я теперь умею разговаривать голосом!")
    print(f"[Voice AI] Тестовый голосовой файл успешно создан: {test_file}")
