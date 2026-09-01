import urllib.request
import urllib.parse
import re

url_to_search = "https://music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(
    "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(url_to_search),
    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
)

try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        titles = re.findall(r'<a class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        print("DDG Titles:", [re.sub(r'<[^>]+>', '', t).strip() for t in titles])
        print("DDG Snippets:", [re.sub(r'<[^>]+>', '', s).strip() for s in snippets])
except Exception as e:
    print("DDG Search Error:", e)
