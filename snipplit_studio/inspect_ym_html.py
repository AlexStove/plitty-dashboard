import urllib.request
import re

url = "https://music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9'
})

html = urllib.request.urlopen(req).read().decode('utf-8')

# Search for 120286811
pos = html.find("120286811")
print("Position of track_id in HTML:", pos)
if pos != -1:
    print("SURROUNDING HTML:")
    print(html[max(0, pos-200):min(len(html), pos+300)])
