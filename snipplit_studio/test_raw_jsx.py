import urllib.request

url = "https://music.yandex.ru/handlers/track.jsx?track=120286811%3A28498877&lang=ru&external-domain=music.yandex.ru"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest'
})
with urllib.request.urlopen(req) as resp:
    text = resp.read().decode('utf-8')
    print("Len:", len(text))
    print(text[:1000])
