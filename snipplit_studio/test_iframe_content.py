import urllib.request
import re

url = "https://music.yandex.ru/iframe/track/120286811/28498877"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html = urllib.request.urlopen(req).read().decode('utf-8')

# Search for any track/artist text in iframe HTML
print("Iframe HTML:")
for line in html.split('\n'):
    if any(k in line.lower() for k in ["title", "artist", "track", "bhabie", "gucci", "careless"]):
        print("MATCH:", line[:200])
