import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone, timedelta
from collections import Counter

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

# Tüm scanner dosyaları
REPORTED_FILES = {
    "superbetin": "reported.json",
    "betsat": "betsat_reported.json",
    "turkbet": "turkbet_reported.json",
    "google": "google_reported.json",
}
WHOIS_FILE = "whois_reported.json"
WEEKLY_STATS_FILE = "weekly_stats.json"

def load_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else list(data)
    except:
        return []

def load_dict(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except:
        return {}

def save_dict(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def detect_brand(domain):
    d = domain.lower()
    if "betsat" in d:
        return "betsat"
    elif "turkbet" in d or "turk-bet" in d:
        return "turkbet"
    else:
        return "superbetin"

def is_recent(domain, days=7):
    """Domain son N günde bulundu mu? (reported dosyası timestamp içermez,
    bu yüzden weekly_stats ile karşılaştırıyoruz)"""
    return True  # Tüm yenileri say

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try:
                await session.post(url, json={
                    "chat_id": chat_id.strip(),
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Telegram hatası: {e}")

async def main():
    now = datetime.now(TZ_SOFIA)
    week_str = now.strftime("%d.%m.%Y")

    # Geçen hafta stats yükle
    prev_stats = load_dict(WEEKLY_STATS_FILE)
    prev_total = prev_stats.get("total_domains", 0)
    prev_by_brand = prev_stats.get("by_brand", {})

    # Bu haftaki domainleri topla
    all_domains = set()
    by_brand = Counter()
    by_source = Counter()

    # Scanner reported dosyaları
    for brand, filename in REPORTED_FILES.items():
        domains = load_json(filename)
        for d in domains:
            all_domains.add(d)
            detected_brand = detect_brand(d)
            by_brand[detected_brand] += 1
        by_source[brand] = len(domains)

    # WHOIS şüpheli domainler
    whois_done = load_json(WHOIS_FILE)
    total_whois_checked = len(whois_done)

    # Bu haftaki yeni domainler
    new_this_week = len(all_domains) - prev_total
    if new_this_week < 0:
        new_this_week = 0

    # Marka bazında yeni domainler
    new_by_brand = {}
    for brand in ["superbetin", "betsat", "turkbet"]:
        curr = by_brand.get(brand, 0)
        prev = prev_by_brand.get(brand, 0)
        new_by_brand[brand] = max(0, curr - prev)

    # Domain tipi analizi
    vip_count = len([d for d in all_domains if ".vip" in d])
    com_count = len([d for d in all_domains if ".com" in d])
    other_count = len(all_domains) - vip_count - com_count

    # Raporu oluştur
    week_num = now.isocalendar()[1]
    
    report = f"""📊 *HAFTALIK PHİSHİNG RAPORU*
━━━━━━━━━━━━━━━━━━━━
📅 Hafta {week_num} — {week_str}
━━━━━━━━━━━━━━━━━━━━

🔢 *GENEL ÖZET*
├ Toplam tespit edilen domain: *{len(all_domains)}*
├ Bu hafta yeni: *+{new_this_week}*
└ WHOIS kontrol edilen: *{total_whois_checked}*

🎯 *MARKA BAZINDA*
├ 🔵 Superbetin: *{by_brand.get('superbetin', 0)}* (+{new_by_brand.get('superbetin', 0)} yeni)
├ 🟠 Betsat: *{by_brand.get('betsat', 0)}* (+{new_by_brand.get('betsat', 0)} yeni)
└ 🟢 Turkbet: *{by_brand.get('turkbet', 0)}* (+{new_by_brand.get('turkbet', 0)} yeni)

🌐 *DOMAIN TİPLERİ*
├ .vip domainler: *{vip_count}*
├ .com domainler: *{com_count}*
└ Diğer: *{other_count}*

🔍 *SCANNER PERFORMANSI*
├ VIP/SEO scanner: *{by_source.get('superbetin', 0)}* domain
├ Betsat scanner: *{by_source.get('betsat', 0)}* domain
├ Turkbet scanner: *{by_source.get('turkbet', 0)}* domain
└ Google scanner: *{by_source.get('google', 0)}* domain

⚡ *EYLEM GEREKTİRENLER*
"""

    # Aktif NICENIC domainleri listele (son eklenenler)
    all_list = sorted(list(all_domains))
    nicenic_domains = [d for d in all_list if any(
        x in d for x in ["1826", "1825", "1824", "1823", "yenigiris", "super9", "guncel"]
    )][:10]

    if nicenic_domains:
        report += f"├ Şikayet bekleyen domain sayısı: *{len(nicenic_domains)}*\n"
        for d in nicenic_domains[:5]:
            report += f"│  • `{d}`\n"
        if len(nicenic_domains) > 5:
            report += f"│  • ... ve {len(nicenic_domains)-5} domain daha\n"
    else:
        report += "└ Bekleyen eylem yok ✅\n"

    report += f"""
━━━━━━━━━━━━━━━━━━━━
🤖 _Otomatik rapor — Poligon Domain Scanner_"""

    # Stats kaydet
    new_stats = {
        "total_domains": len(all_domains),
        "by_brand": dict(by_brand),
        "by_source": dict(by_source),
        "last_report": week_str,
        "week": week_num,
    }
    save_dict(WEEKLY_STATS_FILE, new_stats)

    await send_telegram(report)
    print(f"✅ Haftalık rapor gönderildi!")
    print(f"   Toplam domain: {len(all_domains)}")
    print(f"   Bu hafta yeni: +{new_this_week}")

if __name__ == "__main__":
    asyncio.run(main())
