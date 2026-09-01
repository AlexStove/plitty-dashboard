import urllib.request
import re

url = "https://music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)',
    'Accept-Language': 'ru-RU,ru;q=0.9'
})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    title_m = re.search(r'<title>(.*?)</title>', html)
    og_title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    print("YandexBot Title:", title_m.group(1) if title_m else "None")
    print("YandexBot OG Title:", og_title_m.group(1) if og_title_m else "None")
except Exception as e:
    print("Error:", e)
