import os
import sys
import logging
import hashlib
import uuid
from pathlib import Path
from typing import List, Dict, Any

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

logger = logging.getLogger(__name__)

_model_instance = None

def get_whisper_model():
    global _model_instance
    if _model_instance is None:
        # Очищаем прокси-переменные во избежание сбоев в сети на Windows
        for key in list(os.environ.keys()):
            if "proxy" in key.lower():
                os.environ.pop(key, None)
        
        from faster_whisper import WhisperModel
        
        # Используем пред-загруженную высокоточную модель 'small' / 'base' для мгновенного отклика
        for model_size in ["small", "base"]:
            try:
                logger.info(f"[Whisper AI] Загрузка модели распознавания речи: '{model_size}'...")
                _model_instance = WhisperModel(model_size, device="cpu", compute_type="int8")
                logger.info(f"[Whisper AI] Успешно загружена модель: '{model_size}'")
                break
            except Exception as e:
                logger.warning(f"[Whisper AI] Не удалось загрузить модель '{model_size}': {e}")
                
        if _model_instance is None:
            _model_instance = WhisperModel("base", device="cpu", compute_type="int8")


            
    return _model_instance

def clean_whisper_text(text: str) -> str:
    """Удаляет технические маркеры Whisper, галлюцинации и музыкальные теги."""
    import re
    # Удаляем конструкции в скобках: [музыка], (аплодисменты) и т.д.
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    # Удаляем водяные знаки титров
    bad_phrases = ["субтитры", "редактор", "перевод", "продолжение следует", "subscribe", "thanks for watching", "amara.org"]
    for bp in bad_phrases:
        if bp in text.lower():
            return ""
    return text.strip()

_transcription_cache = {}

def transcribe_audio_segment(audio_path: str, start_time: float = 0.0, end_time: float = None) -> List[Dict[str, Any]]:
    """
    Распознает речь на слух с помощью нейросети Whisper AI и возвращает пословный тайминг.
    Оптимизировано: пред-обрезка отрезка до 20-30с для ускорения в 40 раз + кэширование.
    """
    cache_key = (str(audio_path), round(start_time, 1), round(end_time, 1) if end_time else None)
    if cache_key in _transcription_cache:
        return _transcription_cache[cache_key]

    temp_segment_path = None
    target_path = audio_path
    time_offset = 0.0

    try:
        if (start_time > 0 or end_time is not None) and os.path.exists(audio_path):
            try:
                from moviepy import AudioFileClip
                clip = AudioFileClip(audio_path)
                dur = clip.duration
                s_t = max(0.0, start_time)
                e_t = min(dur, end_time) if end_time else min(dur, start_time + 30.0)
                
                if e_t - s_t > 0.5:
                    temp_dir = config.OUTPUT_DIR
                    file_stem = Path(audio_path).stem
                    hash_tag = hashlib.md5(file_stem.encode()).hexdigest()[:8]
                    temp_segment_path = str(temp_dir / f"whisper_{hash_tag}_{int(s_t)}_{int(e_t)}_{uuid.uuid4().hex[:4]}.wav")
                    
                    sub_clip = clip.subclipped(s_t, e_t)
                    sub_clip.write_audiofile(temp_segment_path, logger=None)
                    sub_clip.close()
                    clip.close()
                    target_path = temp_segment_path
                    time_offset = s_t
                else:
                    clip.close()
            except Exception as cut_err:
                print(f"[!] Ошибка предварительной обрезки для Whisper: {cut_err}")

        model = get_whisper_model()
        segments, info = model.transcribe(
            target_path,
            word_timestamps=True,
            language=None,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False
        )


        lyrics = []
        for segment in segments:
            if hasattr(segment, 'words') and segment.words:
                for w in segment.words:
                    word_str = clean_whisper_text(w.word)
                    if word_str and len(word_str) > 0:
                        w_s = float(w.start) + time_offset
                        w_e = float(w.end) + time_offset
                        lyrics.append({
                            "start": round(w_s, 2),
                            "end": round(w_e, 2),
                            "text": word_str
                        })
            else:
                text_str = clean_whisper_text(segment.text)
                if text_str:
                    s_s = float(segment.start) + time_offset
                    s_e = float(segment.end) + time_offset
                    lyrics.append({
                        "start": round(s_s, 2),
                        "end": round(s_e, 2),
                        "text": text_str
                    })

        lyrics.sort(key=lambda x: x["start"])
        _transcription_cache[cache_key] = lyrics
        return lyrics

    except Exception as err:
        logger.error(f"[Whisper AI] Ошибка распознавания речи: {err}")
        return []
    finally:
        if temp_segment_path and os.path.exists(temp_segment_path):
            try:
                os.remove(temp_segment_path)
            except Exception:
                pass



def align_lyrics_with_whisper(lyrics: List[Dict[str, Any]], audio_path: str, 
                             start_time: float, end_time: float) -> List[Dict[str, Any]]:
    """
    Выравнивает слова из субтитров (LRC/TXT) по реальному вокалу в аудиофайле
    с использованием нейросети Whisper AI. Возвращает пословный список с точными таймингами.
    """
    import re
    whisper_words = transcribe_audio_segment(audio_path, start_time, end_time)
    if not whisper_words:
        return []

    # Нормализация для сравнения слов (поддержка немецкого, английского, русского)
    def norm_word(w: str) -> str:
        s = w.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
        return re.sub(r'[^\w]', '', s)


    all_lrc_words = []
    for item in lyrics:
        raw_s = float(item["start"])
        raw_e = float(item.get("end", raw_s + 3.0))
        
        # Если тайминги в lyrics переданы в относительных секундах (0..duration), сдвигаем к start_time
        if start_time > 0 and raw_s < start_time - 1.0:
            s = raw_s + start_time
            e = raw_e + start_time
        else:
            s = raw_s
            e = raw_e

        words_in_line = item["text"].split()
        if not words_in_line:
            continue
        
        # Распределение внутри строки
        step = (e - s) / len(words_in_line)
        for idx, w in enumerate(words_in_line):
            all_lrc_words.append({
                "orig": w,
                "clean": norm_word(w),
                "est_start": round(s + idx * step, 2),
                "est_end": round(s + (idx + 1) * step, 2),
                "start": None,
                "end": None
            })

    if not all_lrc_words:
        return []

    # Поиск совпадений слов в Whisper
    w_idx = 0
    num_whisper = len(whisper_words)

    for l_idx, lrc_w in enumerate(all_lrc_words):
        target_clean = lrc_w["clean"]
        if not target_clean:
            continue

        best_match = None
        best_distance = 999.0
        best_w_idx = -1

        # Ищем совпадение в радиусе ±5 слов вокруг текущего указателя
        search_start = max(0, w_idx - 2)
        search_end = min(num_whisper, w_idx + 8)

        for j in range(search_start, search_end):
            w_item = whisper_words[j]
            wh_clean = norm_word(w_item["text"])
            
            if wh_clean == target_clean or (len(wh_clean) > 3 and target_clean in wh_clean) or (len(target_clean) > 3 and wh_clean in target_clean):
                time_dist = abs(w_item["start"] - lrc_w["est_start"])
                if time_dist < best_distance:
                    best_distance = time_dist
                    best_match = w_item
                    best_w_idx = j

        if best_match and best_distance < 3.0:
            lrc_w["start"] = best_match["start"]
            lrc_w["end"] = max(best_match["end"], best_match["start"] + 0.18)
            w_idx = best_w_idx + 1

    matched_count = sum(1 for w in all_lrc_words if w["start"] is not None)
    if matched_count < len(all_lrc_words) * 0.35 and len(all_lrc_words) > 3:
        logger.info(f"[Whisper AI] LRC match ratio too low ({matched_count}/{len(all_lrc_words)}). Falling back to direct Whisper speech recognition.")
        return []

    # Интерполяция для несовпавших слов

    for i in range(len(all_lrc_words)):
        if all_lrc_words[i]["start"] is None:
            # Находим предыдущее совпадение
            prev_t = all_lrc_words[i]["est_start"]
            if i > 0 and all_lrc_words[i-1]["end"] is not None:
                prev_t = all_lrc_words[i-1]["end"]

            # Находим следующее совпадение
            next_t = all_lrc_words[i]["est_end"]
            for k in range(i + 1, len(all_lrc_words)):
                if all_lrc_words[k]["start"] is not None:
                    next_t = all_lrc_words[k]["start"]
                    break

            all_lrc_words[i]["start"] = round(prev_t, 2)
            all_lrc_words[i]["end"] = round(max(prev_t + 0.2, min(next_t, prev_t + 0.6)), 2)

    result = []
    for item in all_lrc_words:
        result.append({
            "start": item["start"],
            "end": item["end"],
            "text": item["orig"]
        })

    result.sort(key=lambda x: x["start"])
    return result

