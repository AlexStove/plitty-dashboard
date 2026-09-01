# -*- coding: utf-8 -*-
"""
image_generator.py - Art Director Engine 4.5 Masterpiece (Dedicated 2D Anime & Manga Pipeline).
Особенности:
1. Gemini Prompt Architect 4.5: преобразует любые запросы в чистые Danbooru/Pixiv теги + кинематографический бриф.
2. Anti-Uncanny Valley Shield: полностью блокирует генерацию «косплей-людей» и принуждает к чистому 2D-аниме рисунку (cel-shading).
3. Multi-Provider Gateway: поддержка Hugging Face Inference (Animagine XL 3.1 / SDXL Anime), Airforce и Pollinations.
4. Конфиденциальность: все сгенерированные файлы сохраняются строго локально в web_dashboard/generated/.
"""

import os
import sys
import time
import urllib.request
import urllib.parse
import json
import random
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

GENERATED_DIR = os.path.join(os.path.dirname(__file__), "web_dashboard", "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

# Негативный щит против псевдо-реализма и мыла
UNIVERSAL_NEGATIVE_PROMPT = (
    "photorealistic, realistic, 3d, photo, real human face, skin pores, oily skin, cosplay, doll, "
    "bad anatomy, extra limbs, extra fingers, missing fingers, fused fingers, mutated hands, "
    "poorly drawn hands, poorly drawn face, deformed eyes, blurry, lowres, jpeg artifacts, "
    "watermark, signature, text, draft, amateur, bad proportions, duplicate, twin, cloned face"
)

# Матрица стилей 4.5
STYLE_MATRIX = {
    "anime_masterpiece": {
        "model": "flux-anime",
        "aspect": (832, 1216),
        "anchor": (
            "masterpiece, best quality, score_9, score_8_up, 2d anime illustration, "
            "Kyoto Animation and Ufotable visual excellence, vibrant iridescent anime eyes with sparkling highlights, "
            "intricate flowing hair strands, clean crisp vector lineart, subtle dynamic cel shading, "
            "volumetric god rays, floating luminous particles, trending on pixiv, 8k uhd"
        )
    },
    "shinkai_scenery": {
        "model": "flux-anime",
        "aspect": (1216, 832),
        "anchor": (
            "masterpiece, Makoto Shinkai visual style, breathtaking cinematic anime sky, glowing cumulus clouds, "
            "vibrant crystalline water reflections, sunset god rays, clean anime screencap, 8k resolution"
        )
    },
    "anime_90s_retro": {
        "model": "flux-anime",
        "aspect": (832, 1152),
        "anchor": (
            "masterpiece, 1990s retro anime aesthetic, vintage hand-drawn cel shading, Sailor Moon and Cowboy Bebop vibes, "
            "clean black ink contours, nostalgic pastel color palette, subtle 35mm film grain, 2d anime drawing"
        )
    },
    "manga_detailed": {
        "model": "flux-anime",
        "aspect": (832, 1216),
        "anchor": (
            "masterpiece, breathtaking detailed manga cover illustration, dynamic perspective, intricate screentone textures, "
            "fine Japanese ink cross-hatching, sharp expressive linework, high contrast dramatic lighting, 2d manga art"
        )
    },
    "cyberpunk_anime": {
        "model": "flux",
        "aspect": (832, 1216),
        "anchor": (
            "masterpiece, futuristic cyberpunk anime aesthetic, 2d anime drawing, neon-drenched Night City streets, "
            "glowing holographic UI elements, wet asphalt reflections, volumetric neon rim lighting, 8k uhd"
        )
    },
    "ghibli_whimsical": {
        "model": "flux-anime",
        "aspect": (1216, 832),
        "anchor": (
            "masterpiece, Studio Ghibli aesthetic directed by Hayao Miyazaki, lush green wildflower meadows, "
            "soft hand-painted watercolor textures, fluffy billowing clouds, warm golden summer sunlight, 2d anime art"
        )
    },
    "cinematic_photo": {
        "model": "flux-realism",
        "aspect": (832, 1216),
        "anchor": (
            "award-winning portrait photography, shot on Hasselblad H6D-100c, 85mm f/1.2 lens, "
            "natural soft lighting, shallow depth of field, 8k uhd dslr raw"
        )
    },
    "default": {
        "model": "flux-anime",
        "aspect": (832, 1216),
        "anchor": (
            "masterpiece, best quality, 2d anime illustration, clean lineart, vibrant anime colors, "
            "volumetric atmospheric lighting, intricate details, flawless 2d anatomy, 8k uhd resolution"
        )
    }
}

def detect_best_style(prompt_text):
    p = prompt_text.lower()
    if any(k in p for k in ["90", "ретро", "retro", "90s", "вхс", "vhs", "ковбой", "бибоп", "старое аниме"]):
        return "anime_90s_retro"
    elif any(k in p for k in ["манга", "manga", "комикс", "черно-бел", "тушь", "штрих"]):
        return "manga_detailed"
    elif any(k in p for k in ["пейзаж", "небо", "облака", "закат", "рассвет", "шинкан", "shinkai", "город"]):
        return "shinkai_scenery"
    elif any(k in p for k in ["гибли", "ghibli", "миядзаки", "акварель", "лето", "деревня", "лес", "природа"]):
        return "ghibli_whimsical"
    elif any(k in p for k in ["киберпанк", "cyberpunk", "неон", "neon", "будущее", "робот", "кибер"]):
        return "cyberpunk_anime"
    elif any(k in p for k in ["фото", "фотографи", "photo", "реалистичн", "человек", "девушка фото", "портрет фото"]):
        return "cinematic_photo"
    else:
        return "anime_masterpiece"

def expand_prompt_with_gemini(prompt_text, style_key):
    try:
        import config
        api_key = getattr(config, "GEMINI_API_KEY", "")
        if not api_key:
            return None
            
        system_instruction = (
            "You are the world's most elite 2D Anime & Manga Art Director.\n"
            "Your task: Convert the user's raw prompt into a breathtaking 2D anime illustration prompt using both natural descriptions and Danbooru tags.\n\n"
            "MANDATORY RULES:\n"
            "1. PURE 2D ANIME AESTHETIC: Enforce '2d anime illustration, clean lineart, vibrant anime coloring, Kyoto Animation style'. NEVER photorealistic/3d/cosplay.\n"
            "2. CANONICAL PLITTY (if prompt mentions 'плитти', 'plitty', 'себя', 'саму себя'):\n"
            "   - '1girl, solo, plitty, cute anime catgirl, messy pastel-pink hair, ahoge cowlick, fluffy pink cat ears with white inner fluff, pink cat tail, expressive glowing amber eyes, delicate blush'.\n"
            "   - Clothing: e.g. 'white spaghetti-strap sundress' or 'black bikini' or 'white tank top with denim micro-shorts'.\n"
            "   - Props: holding a cold frosty can of craft beer or cute beverage.\n"
            "3. COMPOSITION & LIGHTING: Specify golden hour sunset, tropical beach or neon background, volumetric god rays, soft cel-shading, shallow depth of field.\n"
            "4. OUTPUT FORMAT: Return ONLY the final English prompt (40-70 words), no markdown, no quotes."
        )
        
        models = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            body = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{system_instruction}\n\nUser input: {prompt_text}\nTarget style: {style_key}"}
                        ]
                    }
                ]
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if text and len(text) > 15:
                        return text.strip('"\'\n\r').replace("`", "")
    except Exception as e:
        print(f"[Prompt Architect Note] {e}")
    return None

def generate_with_huggingface(prompt, hf_token, target_width, target_height):
    """Генерация через выделенный Hugging Face Router API по токену."""
    if not hf_token:
        return None
    try:
        url = "https://router.huggingface.co/hf-inference/models/cagliostrolab/animagine-xl-3.1"
        body = json.dumps({
            "inputs": prompt,
            "parameters": {
                "negative_prompt": UNIVERSAL_NEGATIVE_PROMPT,
                "width": target_width,
                "height": target_height
            }
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {hf_token}",
                "Content-Type": "application/json",
                "User-Agent": "PlittyAI/4.5"
            }
        )
        with urllib.request.urlopen(req, timeout=40) as response:
            return response.read()
    except Exception as e:
        print(f"[HF Generation Note] {e}")
    return None

def generate_image(prompt, width=None, height=None, model=None, style_preset=None, seed=None):
    if seed is None:
        seed = random.randint(100000, 99999999)

    style_key = style_preset or detect_best_style(prompt)
    style_data = STYLE_MATRIX.get(style_key, STYLE_MATRIX["default"])
    
    target_model = model or style_data["model"]
    target_width = width or style_data["aspect"][0]
    target_height = height or style_data["aspect"][1]
    style_anchor = style_data["anchor"]

    print(f"[Art Director 4.5] 🧠 Формирование шедевра для '{prompt}'...")
    expanded_prompt = expand_prompt_with_gemini(prompt, style_key)
    
    if expanded_prompt:
        master_prompt = f"{expanded_prompt}, {style_anchor}"
    else:
        p_clean = prompt
        replacements = {
            "себя": "1girl, solo, plitty, anime catgirl, messy pastel-pink hair, ahoge, fluffy pink cat ears, amber eyes, white sundress, cold beer",
            "саму себя": "1girl, solo, plitty, anime catgirl, messy pastel-pink hair, ahoge, fluffy pink cat ears, amber eyes, white sundress, cold beer",
            "плитти": "1girl, solo, plitty, anime catgirl, messy pastel-pink hair, ahoge, fluffy pink cat ears, amber eyes, white sundress, cold beer",
            "бикини": "black bikini, sitting on beach",
            "купальник": "stylish swimsuit, beach setting",
            "пиво": "holding a cold frosty can of craft beer"
        }
        for k, v in replacements.items():
            p_clean = re.sub(rf'\b{k}\b', v, p_clean, flags=re.IGNORECASE)
        master_prompt = f"masterpiece, best quality, 2d anime illustration, {p_clean}, {style_anchor}"

    print(f"[Art Director 4.5] 🎨 Стиль: {style_key} | Модель: {target_model} [{target_width}x{target_height}]")
    print(f"[Master Prompt] 📝 '{master_prompt[:180]}...'")

    filename = f"plitty_art_{int(time.time())}_{seed % 10000}.jpg"
    file_path = os.path.join(GENERATED_DIR, filename)

    # 1. Попытка через Hugging Face (если указан токен в config.py)
    try:
        import config
        hf_token = getattr(config, "HUGGINGFACE_API_KEY", "")
        if hf_token:
            img_bytes = generate_with_huggingface(master_prompt, hf_token, target_width, target_height)
            if img_bytes and len(img_bytes) > 4000:
                with open(file_path, "wb") as f:
                    f.write(img_bytes)
                web_url = f"/generated/{filename}"
                print(f"[HF Engine] 🏆 Сгенерирован 2D-шедевр: {filename}")
                return {
                    "success": True,
                    "file_path": file_path,
                    "filename": filename,
                    "web_url": web_url,
                    "prompt": prompt,
                    "enhanced_prompt": master_prompt,
                    "style_used": style_key,
                    "model_used": "animagine-xl-3.1",
                    "dimensions": f"{target_width}x{target_height}",
                    "seed": seed
                }
    except Exception:
        pass

    # 2. Многоуровневый отказоустойчивый шлюз генерации (Anti-429 Shield)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/*",
        "Referer": "https://pollinations.ai/"
    }

    candidate_urls = [
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(master_prompt)}?width={target_width}&height={target_height}&model=flux&seed={seed}&nologo=true",
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(master_prompt)}?width={target_width}&height={target_height}&model=turbo&seed={seed}&nologo=true",
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(master_prompt)}?width=768&height=1024&seed={seed}&nologo=true",
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote('masterpiece, 2d anime catgirl plitty, ' + prompt)}?seed={seed}&nologo=true"
    ]

    image_bytes = None
    used_model = "flux"
    for idx, cand_url in enumerate(candidate_urls):
        try:
            req = urllib.request.Request(cand_url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as response:
                img_data = response.read()
                if len(img_data) > 3000:
                    image_bytes = img_data
                    used_model = f"flux_engine_{idx+1}"
                    break
        except Exception:
            time.sleep(0.5)

    if image_bytes:
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        web_url = f"/generated/{filename}"
        print(f"[Art Engine 4.5] 🏆 Шедевр сохранен локально: {filename} ({len(image_bytes)} байт)")
        return {
            "success": True,
            "file_path": file_path,
            "filename": filename,
            "web_url": web_url,
            "prompt": prompt,
            "enhanced_prompt": master_prompt,
            "style_used": style_key,
            "model_used": used_model,
            "dimensions": f"{target_width}x{target_height}",
            "seed": seed
        }
    else:
        return {
            "success": False,
            "error": "Шлюз нейросети сейчас перегружен. Повтори запрос через 5 секунд!",
            "file_path": None,
            "filename": None,
            "web_url": None
        }

