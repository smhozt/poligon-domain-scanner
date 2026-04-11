import asyncio
import aiohttp
import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

# ============================================================
# WHOIS KONTROL EDİLECEK DOMAINLER
# Bu liste scanner'ların bulduğu yeni domainlerden gelir
# ============================================================
REPORTED_FILE = "reported.json"
WHOIS_REPORTED_FILE = "whois_reported.json"

# Şüpheli registrar'lar
SUSPICIOUS_REGISTRARS = [
    "nicenic", "nicenic international",
]

# Şüpheli lokasyonlar
SUSPICIOUS_LOCATIONS = [
    "batumi", "georgia", "istanbul", "turkey",
]

def load_json(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except:
        return []

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(list(data), f)

async def get_whois(session, domain):
    """whois.arin.net veya whoisjsonapi kullan"""
    # whoisjsonapi.com ücretsiz API
    url = f"https://whoisjsonapi.com/v1/{domain}"
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        pass

    # Alternatif: rdap
    try:
        clean = domain.split(".")[-2] + "." + domain.split(".")[-1]
        url2 = f"https://rdap.org/domain/{domain}"
        async with session.get(url2, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"rdap": data}
    except:
        pass

    return None

def parse_whois(domain, data):
    """WHOIS verisinden önemli bilgileri çıkar"""
    if not data:
        return None

    result = {
        "domain": domain,
        "registrar": "",
        "registrant_country": "",
        "registrant_state": "",
        "registered_on": "",
        "is_nicenic": False,
        "is_suspicious": False,
        "risk_level": "LOW",
        "risk_reasons": [],
    }

    raw = json.dumps(data).lower()

    # Registrar tespiti
    for reg in SUSPICIOUS_REGISTRARS:
        if reg in raw:
            result["registrar"] = "NICENIC"
            result["is_nicenic"] = True
            result["risk_reasons"].append("NICENIC registrar")
            break

    # Lokasyon tespiti
    for loc in SUSPICIOUS_LOCATIONS:
        if loc in raw:
            result["registrant_state"] = loc.title()
            result["risk_reasons"].append(f"Registrant: {loc.title()}")
            break

    # Kayıt tarihi — son 30 günde kaydedilmiş mi?
    date_patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}/\d{2}/\d{4})",
    ]
    dates_found = []
    for pattern in date_patterns:
        dates_found.extend(re.findall(pattern, raw))

    if dates_found:
        try:
            reg_date = datetime.strptime(dates_found[0], "%Y-%m-%d")
            days_old = (datetime.now() - reg_date).days
            result["registered_on"] = dates_found[0]
            if days_old <= 30:
                result["risk_reasons"].append(f"Yeni kayıt ({days_old} gün önce)")
        except:
            pass

    # Risk seviyesi
    if result["is_nicenic"] and result["registrant_state"]:
        result["risk_level"] = "CRITICAL"
        result["is_suspicious"] = True
    elif result["is_nicenic"]:
        result["risk_level"] = "HIGH"
        result["is_suspicious"] = True
    elif result["registrant_state"] in ["Batumi", "Istanbul"]:
        result["risk_level"] = "MEDIUM"
        result["is_suspicious"] = True

    return result

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
            except Exception as e:
                print(f"Telegram hatası: {e}")

async def main():
    # Scanner'ların bulduğu domainleri oku
    reported_domains = load_json(REPORTED_FILE)
    whois_done = set(load_json(WHOIS_REPORTED_FILE))

    # Yeni domainler — daha önce WHOIS yapılmamış
    new_domains = [d for d in reported_domains if d not in whois_done]

    if not new_domains:
        print("WHOIS kontrolü yapılacak yeni domain yok.")
        return

    print(f"{len(new_domains)} domain WHOIS kontrolü yapılacak...")

    suspicious = []

    async with aiohttp.ClientSession() as session:
        for domain in new_domains[:50]:  # Max 50 domain per run
            print(f"WHOIS: {domain}")
            data = await get_whois(session, domain)
            result = parse_whois(domain, data)

            if result and result["is_suspicious"]:
                suspicious.append(result)
                print(f"  ⚠️ {result['risk_level']}: {', '.join(result['risk_reasons'])}")
            else:
                print(f"  ✅ Temiz")

            whois_done.add(domain)
            await asyncio.sleep(1)

    save_json(WHOIS_REPORTED_FILE, list(whois_done))

    if suspicious:
        now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
        msg = f"🕵️ *[WHOIS ALARM] Şüpheli Domain Tespiti!* — {now}\n\n"

        critical = [r for r in suspicious if r["risk_level"] == "CRITICAL"]
        high = [r for r in suspicious if r["risk_level"] == "HIGH"]
        medium = [r for r in suspicious if r["risk_level"] == "MEDIUM"]

        for group, icon, label in [
            (critical, "🚨", "KRİTİK — NICENIC + Batumi/Istanbul"),
            (high, "⚠️", "YÜKSEK — NICENIC"),
            (medium, "🟡", "ORTA — Şüpheli Lokasyon"),
        ]:
            if group:
                msg += f"{icon} *{label}*\n"
                for r in group:
                    msg += f"  🌐 `{r['domain']}`\n"
                    msg += f"  📋 {r['registrar'] or 'Bilinmiyor'} | {r['registrant_state'] or '?'}\n"
                    msg += f"  📅 Kayıt: {r['registered_on'] or '?'}\n"
                    if r['risk_reasons']:
                        msg += f"  ⚡ {' | '.join(r['risk_reasons'])}\n"
                    msg += "\n"

        msg += f"💡 *NICENIC domainler için ClientHold talep et!*\n"
        msg += f"📧 abuse@nicenic.net | support@nicenic.net"

        await send_telegram(msg)
        print(f"✅ {len(suspicious)} şüpheli domain tespit edildi!")
    else:
        print("Temiz — şüpheli domain bulunamadı.")

if __name__ == "__main__":
    asyncio.run(main())
