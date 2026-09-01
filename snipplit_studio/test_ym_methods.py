import urllib.request
import json
import re

url = "https://music.yandex.ru/album/28498877/track/120286811"

# Method 1: Yandex Music OEmbed
try:
    oembed_url = f"https://music.yandex.ru/api/v2.1/oembed?url={urllib.parse.quote(url)}&format=json"
    req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("OEmbed Success! Title:", data.get('title'), "Author:", data.get('author_name'))
except Exception as e:
    print("OEmbed failed:", e)

# Method 2: Yandex Music Widget Endpoint
try:
    widget_url = "https://music.yandex.ru/api/v2.1/handlers/track/120286811"
    req = urllib.request.Request(widget_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("Widget API Success! Title:", data.get('title'))
except Exception as e:
    print("Widget API failed:", e)

# Method 3: Parsing track ID from URL and searching via DuckDuckGo / Bing / Yandex
try:
    track_id = "120286811"
    # Search DuckDuckGo HTML for yandex track page title
    search_url = f"https://html.duckduckgo.com/html/?q=site:music.yandex.ru+track+{track_id}"
    req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        titles = re.findall(r'<a class=\"result__a\"[^>]*>(.*?)</a>', html)
        print("DuckDuckGo Titles:", titles[:3])
except Exception as e:
    print("Search failed:", e)
