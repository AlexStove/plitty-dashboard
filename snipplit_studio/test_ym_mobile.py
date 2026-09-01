import urllib.request
import json
from yandex_music import Client

track_id = "120286811"

# Method A: yandex_music library with Mobile Headers
try:
    client = Client(headers={
        'User-Agent': 'Yandex-Music-API',
        'X-Yandex-Music-Client': 'YandexMusicAndroid/24023241'
    })
    tracks = client.tracks([track_id])
    if tracks:
        tr = tracks[0]
        artist = ", ".join([a.name for a in tr.artists])
        print(f"MOBILE YM SUCCESS! {artist} - {tr.title}")
except Exception as e:
    print("Mobile YM failed:", e)

# Method B: Direct URL call to Yandex Mobile API
try:
    url = f"https://api.music.yandex.net/tracks/{track_id}"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Yandex-Music-API',
        'X-Yandex-Music-Client': 'YandexMusicAndroid/24023241'
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        res = data.get('result', [])
        if res:
            tr = res[0]
            artist = ", ".join([a.get('name') for a in tr.get('artists', [])])
            print(f"DIRECT MOBILE API SUCCESS! {artist} - {tr.get('title')}")
except Exception as e:
    print("Direct Mobile API failed:", e)
