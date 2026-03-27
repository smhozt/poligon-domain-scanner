import asyncio
import aiohttp
import os
import re
from urllib.parse import urlparse

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

# Arama terimleri
SEARCH_QUERIES = [
    "superbetin",
    "superbetin giris",
    "superbetin yeni adres",
    "betsat",
    "betsat giris",
    "turkbet",
    "turkbet giris",
]

# Bizim güvenli domainler
SAFE_DOMAINS = {
    "superbetin.com", "superbetin1813.com", "superbetin1814.com",
    "superbetinturkey.com", "t.me", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "google.com", "wikipedia.org",
    "betsat.com", "turkbet.com",
    # 1814-1974 arasi superbetin
}
# superbetin 1814-1974 arasi ekle
for i in range(1814, 1975):
    SAFE_DOMAINS.add(f"superbetin{i}.com")
# betsat
for i in range(1539, 1710):
    SAFE_DOMAINS.add(f"betsat{i}.com")
# turkbet
for i in range(709, 874):
    SAFE_DOMAINS.add(f"{i}turkbet.com")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def extract_domain(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # www. kaldir
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except:
        return ""

def is_suspicious(domain, query):
    if not domain:
        return False
    if domain in SAFE_DOMAINS:
        return False
    
    # Marka iceriyor mu ama bizim degilse
    brands = ["superbetin", "betsat", "turkbet", "superbetim"]
    for brand in brands:
        if brand in domain:
            return True
    return False

async def google_search(session, query):
    url = f"https://www.google.com/search?q={query}&gl=tr&hl=tr&num=10"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                html = await resp.text()
                # Google sonuc linklerini cek
                links = re.findall(r'href="(https?://[^"&]+)"', html)
                domains = set()
                for link in links:
                    domain = extract_domain(link)
                    if domain and not domain.startswith("google"):
                        domains.add(domain)
                return list(domains)
    except Exception as e:
        print(f"Google search hatasi ({query}): {e}")
    return []

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            chat_id = chat_id.strip()
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try:
                await session.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                })
            except:
                pass

async def main():
    found = []
    
    connector = aiohttp.TCPConnector(limit=3)
    async with aiohttp.ClientSession(connector=connector) as session:
        for query in SEARCH_QUERIES:
            print(f"Araniyor: {query}")
            domains = await google_search(session, query)
            
            for domain in domains:
                if is_suspicious(domain, query):
                    if not any(f["domain"] == domain for f in found):
                        found.append({
                            "domain": domain,
                            "query": query
                        })
                        print(f"[SUSPICIOUS] {domain} ('{query}' aramasinda)")
            
            await asyncio.sleep(5)  # Google rate limit icin bekle

    if found:
        msg = "[ALARM] Google Aramasinda Sahte Site!\n"
        msg += f"{len(found)} supheli domain bulundu:\n\n"
        for item in found:
            msg += f"[GOOGLE] `{item['domain']}`\n"
            msg += f"   Arama: '{item['query']}'\n\n"
        msg += "Kontrol edin: https://www.google.com/search?q=superbetin&gl=tr"
        
        print(msg)
        await send_telegram(msg)
    else:
        print("Google taramasi temiz - sahte site bulunamadi.")

if __name__ == "__main__":
    asyncio.run(main())
