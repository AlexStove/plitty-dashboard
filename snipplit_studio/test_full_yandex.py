from services.downloader import Downloader
from pathlib import Path

downloader = Downloader(Path("downloads/music"))

url = "https://music.yandex.ru/album/28498877/track/120286811"
text = "Слушаю Bhad Bhabie — Gucci Flip Flops x Careless Whisper на Яндекс Музыке: https://music.yandex.ru/album/28498877/track/120286811"

print("Testing full Yandex link download with text context & Shazam AI...")
res = downloader.download_by_link(url, user_text=text)
print("FINAL DOWNLOAD RESULT:", res)
