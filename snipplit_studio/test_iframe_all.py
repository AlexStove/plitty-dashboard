import urllib.request
import re
import json

url = "https://music.yandex.ru/iframe/track/120286811/28498877"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
html = urllib.request.urlopen(req).read().decode('utf-8')

# Search for window.__... or JSON objects in iframe
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print("Iframe script count:", len(scripts))
for i, s in enumerate(scripts):
    if len(s) > 50:
        print(f"Script {i} ({len(s)} chars):", s[:250])
