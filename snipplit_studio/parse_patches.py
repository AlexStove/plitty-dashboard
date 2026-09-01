import urllib.request
import re
import json

url = "https://music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9'
})

html = urllib.request.urlopen(req).read().decode('utf-8')

matches = re.findall(r'window\.__STATE_PATCHES__\s*=\s*window\.__STATE_PATCHES__\s*\|\|\s*\[\]\)\.push\((.*?)\);', html)
for m in matches:
    try:
        data = json.loads(m)
        for item in data:
            val = str(item.get('value'))
            if len(val) > 20 and ("title" in val.lower() or "artist" in val.lower() or "track" in val.lower() or "name" in val.lower()):
                print("PATH:", item.get('path'))
                print("VAL:", val[:300])
                print("-" * 50)
    except Exception as e:
        print("Err:", e)
