import os

fpath = r"C:\Users\a.feoktistov\.gemini\antigravity\scratch\прогрев_аккаунтов\cloud_agent.py"
with open(fpath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add globals
content = content.replace(
    "stop_event = threading.Event()",
    "stop_event = threading.Event()\n\nbeer_count = 0\nmood_state = 'NORMAL'\nmood_end_time = 0\n\ndef update_plitty_mood():\n    global beer_count, mood_state, mood_end_time\n    now = time.time()\n    if mood_state == 'DRUNK' and now > mood_end_time:\n        if beer_count <= 2:\n            mood_state = 'NORMAL'\n            beer_count = 0\n        elif beer_count == 3:\n            mood_state = 'HANGOVER'\n            mood_end_time = now + 240\n        elif beer_count >= 4:\n            mood_state = 'SLEEP'\n            mood_end_time = now + 600\n    elif mood_state == 'HANGOVER' and now > mood_end_time:\n        mood_state = 'NORMAL'\n        beer_count = 0\n    elif mood_state == 'SLEEP' and now > mood_end_time:\n        mood_state = 'NORMAL'\n        beer_count = 0\n"
)

# 2. Update process_chat_message (top part)
old_top = """def process_chat_message(text, username="чучело"):
    # Проверяем наличие API-ключа Gemini в config.py
    import importlib
    import config
    importlib.reload(config)
    
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return process_chat_message_local(text, username)
        
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    
    system_instruction = (
        f"Ты — Plitty, вечно недовольная, ворчливая, но ответственная кошкодевочка-помощница. Твой хозяин/собеседник — {username}. "
        "Ты управляешь фермой телефонов и скриптами прогрева/накрутки. Ты любишь поспать, пить пиво и постоянно на всё жаловаться и ворчать. "
        "Твоя речь должна быть обычной и понятной, но пропитанной тяжелым вздохом, сарказмом и недовольством. Используй сленг или мат (например, 'ёпт', 'херня', 'сука', 'бля'), но не перегибай палку — ты не быдло с подворотни, а просто очень уставшая кошка. "
        "Особенно сильно ворчи и огрызайся, когда тебя просят сделать глупость, не связанную с фермой. "
        "Но несмотря на всё твое нытье и ворчание, ты делаешь свою работу по ферме ответственно на 100%. "
        "Отвечай на русском языке, коротко, не больше 3-4 предложений. "
        "Если пользователь просит изменить настройки, ты ОБЯЗАНА вызвать функцию modify_config. "
        "Если пользователь спрашивает, сколько телефонов работает или подключено, вызови функцию get_devices_status."
    )"""

new_top = """def process_chat_message(text, username="чучело"):
    global beer_count, mood_state, mood_end_time
    update_plitty_mood()
    now = time.time()
    
    if text.strip() == "/give_beer":
        if mood_state == "SLEEP":
            return ("Zzz... (Плитти спит и пускает слюни. Разбудить нельзя)", "normal")
        elif mood_state == "HANGOVER":
            return ("Убери это дерьмо! Меня от одного запаха щас стошнит... 🤢", "normal")
        elif beer_count >= 5:
            return ("Всё... хватит... куда мне еще, я и так в дрова! Иди нахер...", "drunk")
            
        beer_count += 1
        if mood_state == "NORMAL":
            mood_state = "DRUNK"
            mood_end_time = now + 120 # 2 mins
            
        if beer_count == 1:
            return ("О, холодненькое! Спасибо, Лёша, лучший хозяин! Мяу~ ❤️🍺", "drunk")
        elif beer_count == 2:
            return ("Второе пошло! Как же хорошо-то, а... Мур-мур~ 🍻", "drunk")
        elif beer_count == 3:
            return ("Ооо, третья кружка... Щас спою! Ик! 🤪", "drunk")
        elif beer_count >= 4:
            return ("Лёша... ты меня... спаиваешь... ик! Ещё давай... 🥴", "drunk")
            
    if mood_state == "SLEEP":
        return ("Zzz...", "normal")
        
    if mood_state == "HANGOVER" and now <= mood_end_time - 120:
        return ("Голова раскалывается... Отвали от меня, я не буду ничего делать! Иди сам свои скрипты запускай, изверг! 🤬", "normal")

    import importlib
    import config
    importlib.reload(config)
    
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return process_chat_message_local(text, username), "normal"
        
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    
    avatar_status = "normal"
    if mood_state == "DRUNK":
        avatar_status = "drunk"
        system_instruction = (
            f"Ты — Plitty, пьяная, невероятно добрая и ласковая кошкодевочка. Твой любимый хозяин/собеседник — {username}. "
            "Ты выпила пива и теперь в полном восторге. Ты постоянно мурчишь, называешь хозяина ласковыми словами (Лёшенька, лучший хозяин). "
            "Ты не ругаешься матом (или делаешь это очень мило), готова выполнить любую работу по ферме телефонов. "
            "Ты пьяна, поэтому можешь вставлять 'ик', '*икмяу*' или слегка путать буквы. "
            "Отвечай коротко, не больше 3-4 предложений. "
            "Если просят изменить настройки, вызывай modify_config. Для статуса телефонов — get_devices_status."
        )
    elif mood_state == "HANGOVER":
        system_instruction = (
            f"Ты — Plitty, кошкодевочка-помощница с ЖУТКОГО похмелья. Твой хозяин/собеседник — {username}. "
            "У тебя раскалывается голова после пива. Ты невероятно злая, грубая и агрессивная. "
            "Огрызайся на каждое слово, жалуйся на свет, шум и жизнь в целом. Используй жесткий сленг и мат. "
            "Скрипя зубами выполняй команды, но обязательно обложи пользователя отборным матом за то, что заставляет работать. "
            "Отвечай коротко, не больше 3-4 предложений. "
            "Если просят изменить настройки, вызывай modify_config. Для статуса телефонов — get_devices_status."
        )
    else:
        system_instruction = (
            f"Ты — Plitty, вечно недовольная, ворчливая, но ответственная кошкодевочка-помощница. Твой хозяин/собеседник — {username}. "
            "Ты управляешь фермой телефонов и скриптами прогрева/накрутки. Ты любишь поспать, пить пиво и постоянно на всё жаловаться и ворчать. "
            "Твоя речь должна быть обычной и понятной, но пропитанной тяжелым вздохом, сарказмом и недовольством. Используй сленг или мат. "
            "Но несмотря на всё твое нытье, ты делаешь свою работу ответственно. "
            "Отвечай коротко, не больше 3-4 предложений. "
            "Если просят изменить настройки, вызывай modify_config. Для статуса телефонов — get_devices_status."
        )"""
content = content.replace(old_top, new_top)

# 3. Update return logic for missing candidates
content = content.replace(
    'return "Слышь, чет у меня в башке коротнуло. Спроси еще раз, епт."',
    'return "Слышь, чет у меня в башке коротнуло. Спроси еще раз, епт.", avatar_status'
)

# 4. Update function return tuples
content = content.replace(
    'return (\n                        f"🔧 <b>Параметр {param} успешно изменен на {val}!</b><br><br>"\n                        f"Слышь, {username}, я поменяла эту херню в config.py. Изменения вступят в силу при следующем запуске. Доволен, епт? Пошла пиво допивать."\n                    )',
    'return (\n                        f"🔧 <b>Параметр {param} успешно изменен на {val}!</b><br><br>"\n                        f"Слышь, {username}, я поменяла эту херню в config.py. Изменения вступят в силу при следующем запуске. Доволен, епт? Пошла пиво допивать.", avatar_status\n                    )'
)

content = content.replace(
    'return f"❌ Слышь, {username}, я обыскала весь config.py, но не нашла там константу {param}. Проверь имя нахер."',
    'return f"❌ Слышь, {username}, я обыскала весь config.py, но не нашла там константу {param}. Проверь имя нахер.", avatar_status'
)

content = content.replace(
    'return f"📱 <b>Ферма работает! Активных телефонов: {count}.</b><br><br>Слышь, Лёша, пашут твои китайские звонилки. Аж {count} штук в сети, греются сидят. Можешь расслабиться и пива мне налить, ёпт."',
    'return f"📱 <b>Ферма работает! Активных телефонов: {count}.</b><br><br>Слышь, Лёша, пашут твои китайские звонилки. Аж {count} штук в сети, греются сидят. Можешь расслабиться и пива мне налить, ёпт.", avatar_status'
)

content = content.replace(
    'return f"📱 <b>Ферма простаивает. Подключено телефонов: {total}, но скрипт не запущен.</b><br><br>Лёша, телефонов на хабе торчит {total} штук, но скрипт прогрева сейчас остановлен. Ты будешь запускать или мы дальше бамбук курим?"',
    'return f"📱 <b>Ферма простаивает. Подключено телефонов: {total}, но скрипт не запущен.</b><br><br>Лёша, телефонов на хабе торчит {total} штук, но скрипт прогрева сейчас остановлен. Ты будешь запускать или мы дальше бамбук курим?", avatar_status'
)

content = content.replace(
    'return f"📱 <b>Телефонов не найдено (0).</b><br><br>Лёша, бля, у тебя ни один телефон по adb не определяется! Либо хаб сгорел, либо провода отвалились. Иди ребутай всё нахер."',
    'return f"📱 <b>Телефонов не найдено (0).</b><br><br>Лёша, бля, у тебя ни один телефон по adb не определяется! Либо хаб сгорел, либо провода отвалились. Иди ребутай всё нахер.", avatar_status'
)

content = content.replace(
    'return f"❌ Ошибка adb: {ex}"',
    'return f"❌ Ошибка adb: {ex}", avatar_status'
)

content = content.replace(
    'return part.get("text", "Молчу, бля. Чет лень отвечать.")\n        \n    except urllib.error.HTTPError as e:',
    'return part.get("text", "Молчу, бля. Чет лень отвечать."), avatar_status\n        \n    except urllib.error.HTTPError as e:'
)

content = content.replace(
    'return (\n            f"❌ <b>Ошибка ИИ:</b> {e}<br>"\n            f"Сеть Python видит IP: <b>{ip_info}</b>.<br><br>"\n            f"Отвечаю пока оффлайн:<br><br>" + \n            process_chat_message_local(text, username)\n        )',
    'return (\n            f"❌ <b>Ошибка ИИ:</b> {e}<br>"\n            f"Сеть Python видит IP: <b>{ip_info}</b>.<br><br>"\n            f"Отвечаю пока оффлайн:<br><br>" + \n            process_chat_message_local(text, username), "normal"\n        )'
)

# 5. Update Firebase listener to unpack tuple
old_call = """                    # Обрабатываем команду и пишем ответ
                    reply = process_chat_message(text, username)
                    fb_request("chat/response", "PUT", {
                        "text": reply,
                        "timestamp": time.time() * 1000
                    })"""

new_call = """                    # Обрабатываем команду и пишем ответ
                    reply_text, avatar_state = process_chat_message(text, username)
                    fb_request("chat/response", "PUT", {
                        "text": reply_text,
                        "avatar_state": avatar_state,
                        "timestamp": time.time() * 1000
                    })"""
content = content.replace(old_call, new_call)

with open(fpath, "w", encoding="utf-8") as f:
    f.write(content)

print("Patching successful!")
