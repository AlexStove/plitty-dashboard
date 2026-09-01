import os
import shutil
from pathlib import Path
from moviepy import VideoFileClip
from database.db import db
import config

source_dir = Path(r"C:\Users\a.feoktistov\Downloads\Новая папка")
target_dir = config.FOOTAGE_DIR
target_dir.mkdir(parents=True, exist_ok=True)

print("Processing fashion footages from Downloads...")
processed_files = []

for file_path in source_dir.glob("*.mp4"):
    filename = file_path.name
    clean_name = filename if (filename.startswith("fashion_") or filename.startswith("beauty_")) else f"fashion_{filename}"
    dest_path = target_dir / clean_name

    shutil.copy2(str(file_path), str(dest_path))
    
    duration = 0.0
    width, height = 720, 1280
    try:
        clip = VideoFileClip(str(dest_path))
        duration = clip.duration
        width, height = clip.size
        clip.close()
    except Exception as e:
        print(f"Metadata read error for {clean_name}: {e}")

    footage_id = db.add_footage(
        filename=clean_name,
        file_path=str(dest_path),
        duration=duration,
        width=width,
        height=height,
        category="fashion"
    )
    processed_files.append((clean_name, footage_id, duration, f"{width}x{height}"))
    print(f"[+] Added fashion footage #{footage_id}: {clean_name} ({int(duration)}s, {width}x{height})")

print(f"SUCCESS: Imported {len(processed_files)} fashion footages into database and target folder!")
