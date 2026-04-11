import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone, timedelta

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SAFE_BROWSING_API_KEY = os.environ.get("SAFE_BROWSING_API_KEY", "")

REPORTED_FILE = "reported.json"
SB_REPORTED_FILE = "safe_browsing_reported.json"

SAFE_BROWSING_API = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

def load_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else list(data)
    except:
        return []

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(list(data), f)

async def check_safe_browsing(session, urls):
    """Google Safe Browsing API ile URL kontrol et"""
    if not SAFE_BROWSING_API_KEY:
        print("SAFE_BROWSING_API_KEY eksik!")
        return []

    payload = {
        "client": {
            "clientId": "poligon-phishing-scanner",
            "clientVersion": "1.0.0"
        },
        "threatInfo": {
            "threatTypes": [
                "MALWARE",
                "SOCIAL_ENGINEERING",  # Phishing
                "UNWANTED_SOFTWARE",
                "POTENTIALLY_HARMFUL_APPLICATION"
            ],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": f"https://{u}"} for u in urls]
        }
    }

    try:
        url = f"{SAFE_BROWSING_API}?key={SAFE_BROWSING_API_KEY}"
        async with session.post(url, json=payload, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("matches", [])
            else:
                print(f"Safe Browsing API HTTP {resp.status}")
                return []
    except Exception as e:
        print(f"Safe Browsing API hatası: {e}")
        return []

async def report_to_safe_browsing(session, url):
    """Google Safe Browsing'e phishing olarak bildir"""
    report_url = "https://safebrowsing.google.com/safebrowsing/report_phish/"
    params = {"url": f"https://{url}"}
    try:
        async with session.get(report_url, params=params, timeout=10) as resp:
            return resp.status in [200, 204, 302]
    except:
        return False

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try:
                await session.post(tg_url, json={
                    "chat_id": chat_id.strip(),
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
            except Exception as e:
                print(f"Telegram hatası: {e}")

async def main():
    reported_domains = load_json(REPORTED_FILE)
    sb_done = set(load_json(SB_REPORTED_FILE))

    # Daha önce gönderilmemiş domainler
    new_domains = [d for d in reported_domains if d not in sb_done]

    if not new_domains:
        print("Safe Browsing'e gönderilecek yeni domain yok.")
        return

    print(f"{len(new_domains)} domain Safe Browsing'e gönderilecek...")

    already_flagged = []
    newly_reported = []
    failed = []

    # 500'lük batch'ler halinde gönder (API limiti)
    batch_size = 500
    batches = [new_domains[i:i+batch_size] for i in range(0, len(new_domains), batch_size)]

    async with aiohttp.ClientSession() as session:
        # Önce zaten flaglenmiş mi kontrol et
        for batch in batches:
            matches = await check_safe_browsing(session, batch)
            for match in matches:
                flagged_url = match.get("threat", {}).get("url", "").replace("https://", "")
                if flagged_url:
                    already_flagged.append(flagged_url)
                    print(f"  ✅ Zaten flagli: {flagged_url}")

        # Henüz flaglenmemişleri bildir
        not_flagged = [d for d in new_domains if d not in already_flagged]
        print(f"\n{len(not_flagged)} domain Google'a bildiriliyor...")

        for domain in not_flagged[:200]:  # Max 200 per run
            success = await report_to_safe_browsing(session, domain)
            if success:
                newly_reported.append(domain)
                print(f"  📤 Bildirildi: {domain}")
            else:
                failed.append(domain)
                print(f"  ❌ Başarısız: {domain}")
            sb_done.add(domain)
            await asyncio.sleep(0.5)

        # Zaten flaglenenleri de done'a ekle
        for d in already_flagged:
            sb_done.add(d)

    save_json(SB_REPORTED_FILE, list(sb_done))

    # Telegram raporu
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"🛡️ *[SAFE BROWSING] Rapor* — {now}\n\n"

    if already_flagged:
        msg += f"✅ *Zaten Google'da flagli:* {len(already_flagged)} domain\n"
        for d in already_flagged[:5]:
            msg += f"  • `{d}`\n"
        if len(already_flagged) > 5:
            msg += f"  • ... ve {len(already_flagged)-5} domain daha\n"
        msg += "\n"

    if newly_reported:
        msg += f"📤 *Google'a yeni bildirilen:* {len(newly_reported)} domain\n"
        for d in newly_reported[:5]:
            msg += f"  • `{d}`\n"
        if len(newly_reported) > 5:
            msg += f"  • ... ve {len(newly_reported)-5} domain daha\n"
        msg += "\n"

    if failed:
        msg += f"❌ *Başarısız:* {len(failed)} domain\n"

    if not already_flagged and not newly_reported and not failed:
        msg += "Gönderilecek yeni domain yok.\n"

    msg += f"\n🤖 _Toplam Safe Browsing'e gönderilen: {len(sb_done)}_"

    await send_telegram(msg)
    print(f"\n✅ Tamamlandı!")
    print(f"   Zaten flagli: {len(already_flagged)}")
    print(f"   Yeni bildirilen: {len(newly_reported)}")
    print(f"   Başarısız: {len(failed)}")

if __name__ == "__main__":
    asyncio.run(main())
