import urllib.request
import re

url_to_search = "site:music.yandex.ru/album/28498877/track/120286811"
req = urllib.request.Request(
    "https://www.bing.com/search?q=" + urllib.parse.quote(url_to_search),
    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
)

try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        titles = re.findall(r'<h2><a[^>]*>(.*?)</a></h2>', html, re.DOTALL)
        snippets = re.findall(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
        print("Bing Titles:", [re.sub(r'<[^>]+>', '', t).strip() for t in titles])
        print("Bing Snippets:", [re.sub(r'<[^>]+>', '', s).strip() for s in snippets])
except Exception as e:
    print("Bing Search Error:", e)
