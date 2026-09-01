import re
from typing import List, Dict, Any, Optional

def parse_time(time_str: str) -> float:
    """Конвертирует строку времени [mm:ss.xx] в секунды (float)."""
    parts = re.split(r'[:\.]', time_str)
    if len(parts) == 2:  # mm:ss
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) >= 3:  # mm:ss.xx
        minutes = int(parts[0])
        seconds = int(parts[1])
        fraction = float("0." + parts[2])
        return minutes * 60 + seconds + fraction
    return 0.0

def parse_lrc(lrc_content: str, track_duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Парсит содержимое LRC-файла.
    Возвращает список словарей вида: [{"start": 10.5, "end": 15.0, "text": "Текст"}]
    """
    lines = lrc_content.splitlines()
    lyrics = []
    
    time_regex = r'\[(\d{2}:\d{2}(?:[\.:]\d{2,3})?)\]'
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        matches = re.findall(time_regex, line)
        if not matches:
            continue
            
        text = re.sub(time_regex, '', line).strip()
        
        for match in matches:
            try:
                start_time = parse_time(match)
                lyrics.append({
                    "start": start_time,
                    "text": text
                })
            except Exception:
                continue

    if not lyrics:
        return parse_txt_fallback(lrc_content, track_duration or 30.0)

    lyrics.sort(key=lambda x: x["start"])

    
    # Расчет точной естественной длительности фраз во избежание зависания текста на инструменталах
    for i in range(len(lyrics)):
        start = lyrics[i]["start"]
        text = lyrics[i]["text"].strip()
        word_count = len(text.split()) if text else 1
        
        # Естественная длительность звучания строки (примерно 0.45 сек на слово + задержка 0.6 сек)
        natural_dur = max(2.0, min(5.0, word_count * 0.45 + 0.6))
        
        if i < len(lyrics) - 1:
            next_start = lyrics[i+1]["start"]
            gap = next_start - start
            if gap > 0:
                # Ограничиваем длительность либо началом следующей строки, либо естественным звучанием
                lyrics[i]["end"] = round(start + min(gap, natural_dur), 2)
            else:
                lyrics[i]["end"] = round(start + natural_dur, 2)
        else:
            if track_duration and track_duration > start:
                lyrics[i]["end"] = round(min(track_duration, start + natural_dur), 2)
            else:
                lyrics[i]["end"] = round(start + natural_dur, 2)

    # Фильтруем строки с пустым текстом
    lyrics = [item for item in lyrics if item["text"].strip()]
            
    return lyrics

def parse_txt_fallback(txt_content: str, track_duration: float) -> List[Dict[str, Any]]:
    """
    Если пользователь загрузил обычный текст без таймингов,
    распределяем строки по естественной длительности произношения слов.
    """
    lines = [line.strip() for line in txt_content.splitlines() if line.strip()]
    if not lines or not track_duration:
        return []
        
    lyrics = []
    curr_t = 0.0
    
    # Считаем естественную длительность звучания каждой строки по количеству слов
    for i, line in enumerate(lines):
        words = line.split()
        w_cnt = len(words) if words else 1
        # Естественная длительность строки: ~0.42с на слово + 0.6с пауза
        line_dur = max(1.8, min(6.0, w_cnt * 0.42 + 0.6))
        
        s_t = round(curr_t, 2)
        e_t = round(curr_t + line_dur, 2)
        curr_t += line_dur + 0.2
        
        lyrics.append({
            "start": s_t,
            "end": e_t,
            "text": line
        })
        
    return lyrics


def slice_lyrics(lyrics: List[Dict[str, Any]], start_time: float, end_time: float) -> List[Dict[str, Any]]:
    """
    Вырезает кусок субтитров в диапазоне [start_time, end_time]
    и сдвигает тайминги к 0.0 секундам.
    """
    sliced = []
    for item in lyrics:
        s = item["start"]
        e = item["end"]
        if e > start_time and s < end_time:
            new_start = max(0.0, s - start_time)
            new_end = min(end_time - start_time, e - start_time)
            if new_end > new_start:
                sliced.append({
                    "start": round(new_start, 2),
                    "end": round(new_end, 2),
                    "text": item["text"]
                })
    return sliced

def split_line_into_words(sub_start: float, sub_end: float, text: str) -> List[Dict[str, Any]]:
    """
    Рассчитывает взвешенную длительность каждого слова в строке
    на основе длины слова/слогов и знаков препинания (а не просто делением на равные части).
    """
    words = text.split()
    if not words:
        return []

    total_dur = max(0.2, sub_end - sub_start)
    
    # Считаем вес каждого слова (длина + дополнительный вес за знаки препинания в конце)
    weights = []
    for w in words:
        clean_w = re.sub(r'[^\w]', '', w)
        w_len = max(1, len(clean_w))
        weight = float(w_len)
        if w.endswith((',', '.', '!', '?', ':', ';', '-')):
            weight += 1.5
        weights.append(weight)

    total_weight = sum(weights)
    if total_weight <= 0:
        total_weight = float(len(words))
        weights = [1.0] * len(words)

    result_words = []
    curr_t = sub_start
    for i, w in enumerate(words):
        w_dur = total_dur * (weights[i] / total_weight)
        # Ограничиваем минимальную длительность каждого слова (0.18 сек)
        w_dur = max(0.18, w_dur)
        w_start = round(curr_t, 2)
        w_end = round(curr_t + w_dur, 2)
        curr_t += w_dur

        result_words.append({
            "start": w_start,
            "end": w_end,
            "text": w
        })

    # Корректируем конечный тайминг последнего слова, чтобы не выходить за границу строки
    if result_words:
        result_words[-1]["end"] = min(sub_end, result_words[-1]["end"])

    return result_words

def chunk_words_into_phrases(words: List[Dict[str, Any]], max_words: int = 3) -> List[Dict[str, Any]]:
    """
    Группирует список пословных таймингов в компактные фразы по 2–3 слова.
    Формат результата: [{"start": 10.0, "end": 11.2, "text": "Я помню чудное", "words": [...]}]
    """
    if not words:
        return []

    chunks = []
    i = 0
    while i < len(words):
        group = words[i:i + max_words]
        chunk_start = group[0]["start"]
        chunk_end = group[-1]["end"]
        chunk_text = " ".join([w["text"] for w in group])

        chunks.append({
            "start": chunk_start,
            "end": chunk_end,
            "text": chunk_text,
            "words": group
        })
        i += max_words

    return chunks

