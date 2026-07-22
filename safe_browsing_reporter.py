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
# MARKA AYARLARI — GÜNCEL (02 Temmuz 2026 itibarıyla)
# ============================================================
# host_auto_complaint_v2.py / nicenic_complaint_v2.py / multi_reporter_v3.py
# ile AYNI kaynak yapısı — tutarlılık için buraya da taşındı.
BRANDS = {
    "superbetin": {
        "active_domains": ["superbetin.com", "superbetin2077.com"],
    },
    "betsat": {
        "active_domains": ["betsat.com", "betsat1606.com"],
    },
    "turkbet": {
        "active_domains": ["turkbet.io", "749turkbet.com"],
    },
}

# ============================================================
# WHİTELİST — otomatik türetilir (elle range YOK)
# ============================================================
# ÖNEMLİ: Fraud domainler resmi numaralara kasıtlı olarak çok yakın
# seçiliyor (ör. betsat1594.com — resmi betsat1606.com'a yakın,
# superbetin1974.com gibi bir fraud domain de eskiden range(1700,1975)
# içine düşüp yanlışlıkla korunuyordu). Geniş numara aralıkları
# (range(1539, 1701) gibi) bu yüzden KULLANILMAZ — bir fraud domain
# kolayca aralığa düşüp Safe Browsing'e hiç bildirilmeden atlanabilir.
# Whitelist SADECE BRANDS içinde tek tek listelenen gerçek resmi
# domainlerden oluşur.
WHITELIST = set()
for _brand in BRANDS.values():
    WHITELIST.update(_brand["active_domains"])

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

# ============================================================
# YAYGIN PHISHING PATH / SUBDOMAIN KEŞFİ (v2 — 22 Tem 2026)
# Diğer script'lerle (host_auto_complaint_v2.py, multi_reporter_v3.py,
# nicenic_complaint_v2.py) aynı mantık. Safe Browsing'e bare domain
# yerine varsa en spesifik canlı kanıt URL'i (ör. /login.php) bildirilir
# — bu, tek başına domain adından daha güçlü/doğrudan kanıt niteliğinde.
# ============================================================
COMMON_PHISHING_PATHS = [
    "/",
    "/login.php",
    "/spor/",
    "/spor/?mobile=1",
    "/casino/",
    "/canli-bahis/",
    "/modules/payments/deposit/",
    "/modules/payments/deposit/?payment_type=105",
    "/modules/payments/deposit/?payment_type=109",
    "/modules/payments/deposit/?payment_type=117",
    "/payment/view/havale.php",
    "/payment/view/bitcoin.php",
    "/payment/bank/nethavale/",
    "/payment/bank/otomonay/",
    "/payment/crypto/kriptopay/",
    "/paraylan/",
]
COMMON_PHISHING_SUBDOMAINS = ["m", "tr", "www", "yatirim", "payment", "odeme", "cryptopay"]
SUBDOMAIN_DEPOSIT_PATHS = ["/", "/havale/", "/crypto/", "/login.php"]

URL_CHECK_TIMEOUT = aiohttp.ClientTimeout(total=4)
URL_CHECK_CONCURRENCY = 30

async def _check_url(session, semaphore, url):
    async with semaphore:
        try:
            async with session.get(url, timeout=URL_CHECK_TIMEOUT, allow_redirects=True, ssl=False) as resp:
                if resp.status in (200, 301, 302, 403):
                    return url
        except Exception:
            pass
    return None

async def discover_phishing_urls(session, root_domain, max_results=5):
    urls_to_check = []
    for path in COMMON_PHISHING_PATHS:
        urls_to_check.append(f"https://{root_domain}{path}")
    for sub in COMMON_PHISHING_SUBDOMAINS:
        for dpath in SUBDOMAIN_DEPOSIT_PATHS:
            urls_to_check.append(f"https://{sub}.{root_domain}{dpath}")

    semaphore = asyncio.Semaphore(URL_CHECK_CONCURRENCY)
    tasks = [_check_url(session, semaphore, u) for u in urls_to_check]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    found = [u for u in results if u]
    found.sort(key=lambda u: (u.rstrip("/").endswith(root_domain.rstrip("/")), len(u)))
    return found[:max_results]

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

async def report_to_safe_browsing(session, domain, found_urls=None):
    """Varsa en spesifik kanıt URL'ini (ör. /login.php), yoksa bare
    domain'i Google Safe Browsing'e phishing olarak bildirir."""
    target = found_urls[0] if found_urls else f"https://{domain}"
    if not target.startswith("http"):
        target = f"https://{target}"
    report_url = "https://safebrowsing.google.com/safebrowsing/report_phish/"
    params = {"url": target}
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
    evidence_counts = {}

    batch_size = 500
    batches = [new_domains[i:i+batch_size] for i in range(0, len(new_domains), batch_size)]

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as session:
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
            found_urls = await discover_phishing_urls(session, get_root(domain))
            evidence_counts[domain] = len(found_urls)

            success = await report_to_safe_browsing(session, domain, found_urls)
            if success:
                newly_reported.append(domain)
                evidence_note = f" [{len(found_urls)} kanıt URL]" if found_urls else ""
                print(f"  📤 Bildirildi: {domain}{evidence_note}")
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
            url_count = evidence_counts.get(d, 0)
            evidence_note = f" ({url_count} URL kanıtı)" if url_count else ""
            msg += f"  • `{d}`{evidence_note}\n"
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
