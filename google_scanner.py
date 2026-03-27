import os
import json
import urllib.request
import urllib.parse

# Şifreleri Github'dan alıyoruz
API_KEY = os.environ.get("GOOGLE_API_KEY")
CX = os.environ.get("GOOGLE_CX")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")

# Google'da aranacak kelimeler
QUERIES = ["superbetin", "superbetin giriş", "superbetin güncel adres", "superbetin yeni adres"]

# Alarm VERİLMEYECEK güvenli ve resmi domainler listesi
WHITELIST = [
    "superbetin.com", "superbetin1813.com", "superbetin1814.com", "superbetin1815.com",
    "superbetinturkey.vip", "twitter.com", "t.me", "youtube.com", "x.com",
    "instagram.com", "facebook.com", "pinterest.com", "linkedin.com"
]

def send_telegram(text):
    for chat_id in TELEGRAM_CHAT_IDS:
        if not chat_id.strip(): continue
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": chat_id.strip(), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req)
        except Exception as e:
            print(f"Telegram hatasi: {e}")

def main():
    if not API_KEY or not CX:
        print("HATA: Google API Key veya CX kodu eksik!")
        return

    found_suspicious = []

    for query in QUERIES:
        print(f"Araniyor: {query}")
        # gl=tr ve hl=tr parametreleri ile %100 Türkiye sonuclarini zorluyoruz
        url = f"https://www.googleapis.com/customsearch/v1?q={urllib.parse.quote(query)}&cx={CX}&key={API_KEY}&gl=tr&hl=tr&num=10"
        
        try:
            req = urllib.request.Request(url)
            response = urllib.request.urlopen(req)
            data = json.loads(response.read())

            for item in data.get("items", []):
                link = item.get("link", "")
                domain = urllib.parse.urlparse(link).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]

                # Domain "superbetin" iceriyorsa ama Whitelist'te yoksa yakala!
                if "superbetin" in domain and domain not in WHITELIST:
                    if domain not in [d['domain'] for d in found_suspicious]:
                        found_suspicious.append({"domain": domain, "link": link})

        except Exception as e:
            print(f"Google API Hatasi ({query}): {e}")

    if found_suspicious:
        msg = "🚨 <b>Google Arama Tarayıcısı: Şüpheli Siteler Tespit Edildi!</b>\n\n"
        for s in found_suspicious:
            msg += f"🌐 Domain: <code>{s['domain']}</code>\n🔗 Link: {s['link']}\n\n"
        send_telegram(msg)
        print("Supheli siteler Telegram'a gonderildi.")
    else:
        print("Tarama temiz, sahte site bulunamadi.")

if __name__ == "__main__":
    main()
