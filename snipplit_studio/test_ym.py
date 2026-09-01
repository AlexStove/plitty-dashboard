import urllib.request
import re
import json

url = "https://music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
})

html = urllib.request.urlopen(req).read().decode('utf-8')

# Search for any JSON state or title
print("HTML length:", len(html))

# Let's find script contents or JSON data
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print("Found scripts:", len(scripts))

for s in scripts:
    if "title" in s and "artists" in s:
        print("FOUND TRACK SCRIPT:", s[:300])

# Also check for title tag or og tags
title_match = re.search(r'<title>(.*?)</title>', html)
print("Title tag:", title_match.group(1) if title_match else "None")

# Search for JSON object containing "track" or "title"
json_matches = re.findall(r'(\{\"id\":\d+,\"title\":\".*?\"})', html)
print("JSON matches:", json_matches[:5])
