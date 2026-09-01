import urllib.request
import json

urls_to_test = [
    "https://music.yandex.ru/handlers/track.jsx?track=120286811%3A28498877&lang=ru&external-domain=music.yandex.ru",
    "https://music.yandex.ru/handlers/album.jsx?album=28498877&lang=ru",
    "https://music.yandex.ru/api/v2.1/handlers/track/120286811:28498877",
    "https://music.yandex.ru/api/v2.1/handlers/album/28498877"
]

for url in urls_to_test:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print("SUCCESS:", url)
            print("DATA KEYS:", list(data.keys()))
            if 'track' in data:
                t = data['track']
                art = ", ".join([a['name'] for a in t.get('artists', [])])
                print(f"RESULT: {art} - {t.get('title')}")
    except Exception as e:
        print("FAILED:", url, "->", e)
