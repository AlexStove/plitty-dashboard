from services.downloader import Downloader
from pathlib import Path

downloader = Downloader(Path("downloads/music"))

url = "https://music.yandex.ru/album/28498877/track/120286811"
print("Testing Yandex download & Shazam recognition...")
res = downloader.download_from_yandex(url)
print("DOWNLOAD RESULT:", res)
