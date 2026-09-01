import urllib.request
import re

urls = [
    "https://music.yandex.ru/album/28498877/track/120286811/embed/",
    "https://music.yandex.ru/iframe/track/120286811/28498877",
    "https://music.yandex.ru/iframe/track/120286811",
    "https://music.yandex.ru/album/28498877/track/120286811"
]

for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        html = urllib.request.urlopen(req).read().decode('utf-8')
        print("URL:", url, "LEN:", len(html))
        titles = re.findall(r'<title>(.*?)</title>', html)
        print("TITLES:", titles)
        meta_titles = re.findall(r'<meta[^>]*content="([^"]+)"[^>]*>', html)
        print("META SAMPLES:", [m for m in meta_titles if len(m) < 80][:5])
    except Exception as e:
        print("ERR:", url, e)
