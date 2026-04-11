import asyncio
import aiohttp
import os
import json
import re
from datetime import datetime, timezone, timedelta

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

REPORTED_FILE = "reported.json"
WHOIS_REPORTED_FILE = "whois_reported.json"

SUSPICIOUS_KEYWORDS = [
    "nicenic", "batumi", "georgia",
]

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

async def get_whois_rdap(session, domain):
    """RDAP protokolü ile WHOIS — en güvenilir yöntem"""
    # TLD'ye göre RDAP endpoint seç
    tld = domain.split(".")[-1].lower()
    
    rdap_urls = [
        f"https://rdap.org/domain/{domain}",
        f"https://rdap.verisign.com/com/v1/domain/{domain}",
        f"https://rdap.nic.vip/domain/{domain}",
    ]
    
    for url in rdap_urls:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
        except:
            continue
    return None

async def get_whois_api(session, domain):
    """whoisfreaks.com ücretsiz API"""
    api_key = os.environ.get("WHOIS_API_KEY", "")
    
    # API key olmadan da çalışan endpoint
    url = f"https://api.whoisfreaks.com/v1.0/whois?apiKey={api_key}&whois=live&domainName={domain}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
    except:
        pass
    return None

def analyze_domain(domain, rdap_data):
    """RDAP verisinden registrar ve lokasyon bilgisi çıkar"""
    result = {
        "domain": domain,
        "registrar": "",
        "location": "",
        "registered_on": "",
        "is_nicenic": False,
        "is_suspicious": False,
        "risk_level": "LOW",
        "risk_reasons": [],
    }
    
    if not rdap_data:
        return result
    
    raw = json.dumps(rdap_data).lower()
    
    # NICENIC kontrolü
    if "nicenic" in raw:
        result["registrar"] = "NICENIC"
        result["is_nicenic"] = True
        result["risk_reasons"].append("NICENIC registrar")
    
    # Registrar entity'den isim çek
    for entity in rdap_data.get("entities", []):
        roles = entity.get("roles", [])
        if "registrar" in roles:
            vcard = entity.get("vcardArray", [])
            if vcard and len(vcard) > 1:
                for item in vcard[1]:
                    if item[0] == "fn":
                        result["registrar"] = item[3] if len(item) > 3 else result["registrar"]
    
    # Lokasyon kontrolü — registrant entity
    for entity in rdap_data.get("entities", []):
        roles = entity.get("roles", [])
        if "registrant" in roles:
            vcard = entity.get("vcardArray", [])
            if vcard and len(vcard) > 1:
                for item in vcard[1]:
                    if item[0] == "adr":
                        addr = str(item).lower()
                        if "batumi" in addr or "georgia" in addr:
                            result["location"] = "Batumi, Georgia"
                            result["risk_reasons"].append("Batumi/Georgia registrant")
                        elif "istanbul" in addr or ("turkey" in addr and "batumi" not in addr):
                            result["location"] = "Istanbul, Turkey"
                            result["risk_reasons"].append("Istanbul registrant")
    
    # Raw tarama — entity yoksa
    if not result["location"]:
        if "batumi" in raw:
            result["location"] = "Batumi, Georgia"
            result["risk_reasons"].append("Batumi/Georgia (raw)")
        elif "istanbul" in raw:
            result["location"] = "Istanbul, Turkey"
            result["risk_reasons"].append("Istanbul (raw)")
    
    # Kayıt tarihi
    events = rdap_data.get("events", [])
    for event in events:
        if event.get("eventAction") == "registration":
            date_str = event.get("eventDate", "")[:10]
            result["registered_on"] = date_str
            try:
                reg_date = datetime.strptime(date_str, "%Y-%m-%d")
                days_old = (datetime.now() - reg_date).days
                if days_old <= 14:
                    result["risk_reasons"].append(f"Yeni kayıt ({days_old} gün önce)")
            except:
                pass
            break
    
    # Risk seviyesi belirle
    if result["is_nicenic"] and result["location"]:
        result["risk_level"] = "CRITICAL"
        result["is_suspicious"] = True
    elif result["is_nicenic"]:
        result["risk_level"] = "HIGH"
        result["is_suspicious"] = True
    elif result["location"] in ["Batumi, Georgia", "Istanbul, Turkey"]:
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
    reported_domains = load_json(REPORTED_FILE)
    whois_done = set(load_json(WHOIS_REPORTED_FILE))

    new_domains = [d for d in reported_domains if d not in whois_done]

    if not new_domains:
        print("WHOIS kontrolü yapılacak yeni domain yok.")
        return

    print(f"{len(new_domains)} domain WHOIS kontrolü yapılacak...")

    suspicious = []

    async with aiohttp.ClientSession() as session:
        for domain in new_domains[:50]:
            # Subdomain ise root domain al
            parts = domain.split(".")
            if len(parts) > 2:
                root_domain = ".".join(parts[-2:])
            else:
                root_domain = domain
            
            print(f"WHOIS: {root_domain}")
            data = await get_whois_rdap(session, root_domain)
            result = analyze_domain(root_domain, data)

            if result["is_suspicious"]:
                print(f"  🚨 {result['risk_level']}: {', '.join(result['risk_reasons'])}")
                # Ana domain zaten yoksa ekle
                if root_domain not in [s["domain"] for s in suspicious]:
                    suspicious.append(result)
            else:
                reg = result["registrar"] or "bilinmiyor"
                print(f"  ✅ Temiz ({reg})")

            whois_done.add(domain)
            await asyncio.sleep(1)

    save_json(WHOIS_REPORTED_FILE, list(whois_done))

    if suspicious:
        now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
        msg = f"🕵️ *[WHOIS ALARM] Şüpheli Domain!* — {now}\n\n"

        critical = [r for r in suspicious if r["risk_level"] == "CRITICAL"]
        high = [r for r in suspicious if r["risk_level"] == "HIGH"]
        medium = [r for r in suspicious if r["risk_level"] == "MEDIUM"]

        for group, icon, label in [
            (critical, "🚨", "KRİTİK — NICENIC + Batumi/Istanbul"),
            (high, "⚠️", "YÜKSEK — NICENIC"),
            (medium, "🟡", "ORTA — Şüpheli Lokasyon"),
        ]:
            if not group:
                continue
            msg += f"{icon} *{label}*\n"
            for r in group:
                msg += f"  🌐 `{r['domain']}`\n"
                msg += f"  📋 {r['registrar'] or '?'} | {r['location'] or '?'}\n"
                msg += f"  📅 {r['registered_on'] or '?'}\n"
                msg += f"  ⚡ {' | '.join(r['risk_reasons'])}\n\n"

        msg += "💡 *NICENIC domainler için ClientHold talep et!*\n"
        msg += "📧 `abuse@nicenic.net` | `support@nicenic.net`"

        await send_telegram(msg)
        print(f"✅ {len(suspicious)} şüpheli domain!")
    else:
        print("Temiz — şüpheli domain bulunamadı.")

if __name__ == "__main__":
    asyncio.run(main())
