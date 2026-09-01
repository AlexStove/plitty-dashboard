# account_personas.py
"""
Модуль тематического нишивания 30 смартфонов (Account Personas).
Разбивает 30 смартфонов фермы на 5 узкоспециализированных кластеров
и управляет целевым прогревом под каждую нишу.
"""

import db_manager

NICHE_CLUSTERS = {
    "CARS_TECH": {
        "title": "🏎️ Авто и Тюнинг",
        "search_keywords": ["bmw", "tuning", "supercars", "drift", "exhaust"],
        "target_tags": ["#cars", "#tuning", "#bmw", "#supercar"]
    },
    "MEME_HUMOR": {
        "title": "😂 Мемы и Юмор",
        "search_keywords": ["memes", "funny", "relatable", "comedy"],
        "target_tags": ["#meme", "#funny", "#humor", "#relatable"]
    },
    "FINANCE_CRYPTO": {
        "title": "📈 Бизнес и Финансы",
        "search_keywords": ["crypto", "trading", "business", "investing"],
        "target_tags": ["#crypto", "#business", "#money", "#trading"]
    },
    "FITNESS_SPORT": {
        "title": "🏋️ Фитнес и Спорт",
        "search_keywords": ["gym", "workout", "fitness", "bodybuilding"],
        "target_tags": ["#gym", "#fitness", "#workout", "#bodybuilding"]
    },
    "GAMING_GEEK": {
        "title": "🎮 Гейминг и Технологии",
        "search_keywords": ["gaming", "pcbuild", "setup", "esports"],
        "target_tags": ["#gaming", "#gamer", "#pcbuild", "#esports"]
    }
}

def get_device_persona(device_id, dev_index=0):
    """
    Присваивает девайсу тематический профиль в зависимости от его индекса.
    """
    clusters = list(NICHE_CLUSTERS.keys())
    cluster_key = clusters[dev_index % len(clusters)]
    info = NICHE_CLUSTERS[cluster_key]
    return {
        "device_id": device_id,
        "niche_key": cluster_key,
        "title": info["title"],
        "keywords": info["search_keywords"],
        "tags": info["target_tags"]
    }

def get_all_personas_summary(connected_devices):
    """
    Возвращает наглядный отчет о распределении ниш по всем 30 смартфонам.
    """
    if not connected_devices:
        return "📱 Нет подключенных устройств для распределения ниш."
        
    summary_lines = ["<b>👤 Нишевание 30 смартфонов (Account Personas):</b><br>"]
    for idx, dev_id in enumerate(sorted(connected_devices)):
        p = get_device_persona(dev_id, idx)
        summary_lines.append(f"• <b>{dev_id}</b> ➔ {p['title']}")
        
    return "<br>".join(summary_lines[:12]) + f"<br><i>...и еще {max(0, len(connected_devices) - 11)} устройств.</i>"

if __name__ == "__main__":
    print(get_all_personas_summary(["dev1", "dev2", "dev3", "dev4", "dev5"]))
