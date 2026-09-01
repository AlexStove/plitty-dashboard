import urllib.request
import json
import re

track_id = "120286811"
album_id = "28498877"

# Test 1: album.jsx
try:
    url = f"https://music.yandex.ru/handlers/album.jsx?album={album_id}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("Album JSX Success! Title:", data.get('title'))
        volumes = data.get('volumes', [])
        for vol in volumes:
            for tr in vol:
                if str(tr.get('id')) == track_id or str(tr.get('realId')) == track_id:
                    artist = ", ".join([a.get('name') for a in tr.get('artists', [])])
                    print(f"FOUND TRACK: {artist} - {tr.get('title')}")
except Exception as e:
    print("Album JSX failed:", e)

# Test 2: Yandex Music Widget iframe page metadata
try:
    url = f"https://music.yandex.ru/iframe/#track/{track_id}/{album_id}"
    url_embed = f"https://music.yandex.ru/album/{album_id}/track/{track_id}?lang=ru"
    # Try mobile user agent
    req = urllib.request.Request(url_embed, headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'})
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        print("Mobile HTML len:", len(html))
        # Search for title in mobile HTML
        m = re.search(r'<title>(.*?)</title>', html)
        if m:
            print("Mobile Title:", m.group(1))
except Exception as e:
    print("Widget embed failed:", e)
