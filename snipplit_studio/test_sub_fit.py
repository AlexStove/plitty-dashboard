from services.video_engine import create_subtitle_image
import config

output_path = "test_subtitle_wrapped.png"
text = "THE WAVES, TOUCHING THE SHORE AGAIN AND AGAIN AND AGAIN"

create_subtitle_image(
    text=text,
    width=720,
    height=1280,
    font_path=str(config.FONT_PATH),
    font_size=42,
    output_path=output_path,
    style="tiktok",
    pos_y_ratio=0.72
)

print("Generated test subtitle image:", output_path)
