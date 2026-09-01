import urllib.request
import json

track_id = "120286811"
album_id = "28498877"

# Test 1: music.yandex.ru/handlers/track.jsx?track=120286811%3A28498877
url1 = f"https://music.yandex.ru/handlers/track.jsx?track={track_id}%3A{album_id}"
req1 = urllib.request.Request(url1, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Referer': f'https://music.yandex.ru/album/{album_id}/track/{track_id}'
})

try:
    with urllib.request.urlopen(req1) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("JSX TRACK SUCCESS! Title:", data.get('track', {}).get('title'))
        artists = [a.get('name') for a in data.get('track', {}).get('artists', [])]
        print("Artists:", ", ".join(artists))
except Exception as e:
    print("JSX TRACK Error:", e)

# Test 2: music.yandex.ru/handlers/album.jsx?album=28498877
url2 = f"https://music.yandex.ru/handlers/album.jsx?album={album_id}"
req2 = urllib.request.Request(url2, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': f'https://music.yandex.ru/album/{album_id}'
})

try:
    with urllib.request.urlopen(req2) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("JSX ALBUM SUCCESS! Album Title:", data.get('title'))
        volumes = data.get('volumes', [])
        for vol in volumes:
            for tr in vol:
                if str(tr.get('id')) == track_id or str(tr.get('realId')) == track_id:
                    artist = ", ".join([a.get('name') for a in tr.get('artists', [])])
                    print(f"FOUND TRACK IN ALBUM: {artist} - {tr.get('title')}")
except Exception as e:
    print("JSX ALBUM Error:", e)
