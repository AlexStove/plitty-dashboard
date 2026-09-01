import os
from pathlib import Path
from moviepy import VideoFileClip
from PIL import Image
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

THUMBS_DIR = config.DOWNLOADS_DIR / "thumbnails"
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

def get_footage_thumbnail_url(video_path_str: str) -> str:
    """
    Возвращает URL превью мгновенно (5мс), не блокируя ответы сервера.
    """
    v_path = Path(video_path_str)
    if not v_path.exists():
        return ""

    thumb_name = f"thumb_{v_path.stem}.jpg"
    thumb_path = THUMBS_DIR / thumb_name

    if thumb_path.exists():
        return f"/downloads/thumbnails/{thumb_name}"
    
    # Фолбек на правильно сконструированный путь к видеофайлу
    try:
        rel_path = str(v_path.relative_to(config.DOWNLOADS_DIR)).replace("\\", "/")
        return f"/downloads/{rel_path}"
    except Exception:
        return f"/downloads/footages/{v_path.name}"

def create_single_thumb(v_path: Path):
    thumb_name = f"thumb_{v_path.stem}.jpg"
    thumb_path = THUMBS_DIR / thumb_name
    if thumb_path.exists():
        return
    try:
        clip = VideoFileClip(str(v_path))
        t = min(1.0, max(0.0, clip.duration / 2))
        frame = clip.get_frame(t)
        clip.close()
        img = Image.fromarray(frame)
        img.thumbnail((240, 420))
        img.save(thumb_path, "JPEG", quality=75)
    except Exception as err:
        pass

def generate_all_thumbnails_async():
    """Фоновая генерация миниатюр в отдельном потоке."""
    import threading
    def _worker():
        for file in config.FOOTAGE_DIR.rglob("*"):
            if file.suffix.lower() in ['.mp4', '.mov', '.avi']:
                create_single_thumb(file)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

