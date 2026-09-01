import urllib.request
import urllib.parse
import json
import re

url_to_find = "https://music.yandex.ru/album/28498877/track/120286811"
track_id = "120286811"

# Method: Search DuckDuckGo Lite API
try:
    search_q = f"\"120286811\" site:music.yandex.ru"
    req = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/",
        data=urllib.parse.urlencode({'q': search_q}).encode('utf-8'),
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        print("DuckDuckGo Lite len:", len(html))
        snippets = re.findall(r'<td class=\"result-snippet\">(.*?)</td>', html, re.DOTALL)
        for s in snippets:
            clean_s = re.sub(r'<[^>]+>', '', s).strip()
            print("Snippet:", clean_s)
except Exception as e:
    print("DDG Lite failed:", e)
