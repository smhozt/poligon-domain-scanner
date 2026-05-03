import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone, timedelta

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SAFE_BROWSING_API_KEY = os.environ.get("SAFE_BROWSING_API_KEY", "")

REPORTED_FILES = ["reported.json", "betsat_reported.json", "turkbet_reported.json"]
SB_REPORTED_FILE = "safe_browsing_reported.json"

SAFE_BROWSING_API = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

# ============================================================
# WHİTELİST — Bizim domainlerimiz (Google'a bildirilmez)
# ============================================================
WHITELIST = set([
    # Superbetin
    "superbetin.com", "superbetin1828.com",
    *[f"superbetin{n}.com" for n in [724, 1240, 1268, 1560, 2369]],
    *[f"superbetin{n}.com" for n in range(1300, 1411)],
    *[f"superbetin{n}.com" for n in range(1700, 1975)],
    # Betsat
    "betsat.com", "betsat1563.com", "betsat1567.com",
    *[f"betsat{n}.com" for n in range(1539, 1701)],
    # Turkbet
    "turkbet.com", "turkbet.io", "722turkbet.com", "723turkbet.com",
    *[f"{n}turkbet.com" for n in range(600, 891)],
])

def get_root(domain):
    parts = domain.split(".")
    if len(parts) > 2:
        return ".".join(parts[-2:])
    return domain

def is_whitelisted(domain):
    root = get_root(domain)
    return domain in WHITELIST or root in WHITELIST

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
                "SOCIAL_ENGINEERING",
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
    all_domains = []
    for f in REPORTED_FILES:
        all_domains.extend(load_json(f))

    reported_domains = list(set(all_domains))
    sb_done = set(load_json(SB_REPORTED_FILE))

    # Whitelist ve daha önce gönderilmişleri çıkar
    skipped_whitelist = []
    new_domains = []
    for d in reported_domains:
        if is_whitelisted(d):
            skipped_whitelist.append(d)
            print(f"  🛡️ Whitelist'te, atlandı: {d}")
            continue
        if d not in sb_done:
            new_domains.append(d)

    if skipped_whitelist:
        print(f"\n⚠️ {len(skipped_whitelist)} domain whitelist'te — Google'a bildirilmedi.")

    if not new_domains:
        print("Safe Browsing'e gönderilecek yeni domain yok.")
        return

    print(f"{len(new_domains)} domain Safe Browsing'e gönderilecek...")

    already_flagged = []
    newly_reported = []
    failed = []

    batch_size = 500
    batches = [new_domains[i:i+batch_size] for i in range(0, len(new_domains), batch_size)]

    async with aiohttp.ClientSession() as session:
        # Zaten flaglenmiş mi kontrol et
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

        for domain in not_flagged[:200]:
            success = await report_to_safe_browsing(session, domain)
            if success:
                newly_reported.append(domain)
                print(f"  📤 Bildirildi: {domain}")
            else:
                failed.append(domain)
                print(f"  ❌ Başarısız: {domain}")
            sb_done.add(domain)
            await asyncio.sleep(0.5)

        for d in already_flagged:
            sb_done.add(d)

    save_json(SB_REPORTED_FILE, list(sb_done))

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

    if skipped_whitelist:
        msg += f"🛡️ *Whitelist (atlandı):* {len(skipped_whitelist)} domain\n"

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
