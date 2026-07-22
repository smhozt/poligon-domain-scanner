import asyncio
import aiohttp
import os
import json
import re
from datetime import datetime, timezone, timedelta

# ============================================================
# AYARLAR
# ============================================================
TZ_SOFIA = timezone(timedelta(hours=3))
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SAFE_BROWSING_API_KEY = os.environ.get("SAFE_BROWSING_API_KEY", "")

REPORTED_FILES = ["reported.json", "betsat_reported.json", "turkbet_reported.json"]

# Her platform için ayrı "gönderildi" dosyası
SB_REPORTED_FILE          = "safe_browsing_reported.json"
SPAM_REPORTED_FILE        = "google_spam_reported.json"
NETCRAFT_REPORTED_FILE    = "netcraft_reported.json"
SMARTSCREEN_REPORTED_FILE = "smartscreen_reported.json"
SPAM404_REPORTED_FILE     = "spam404_reported.json"
# CF_REPORTED_FILE kaldırıldı — Cloudflare'in public API'si yok, sadece manuel form
# Phishing: https://abuse.cloudflare.com/phishing
# Trademark: https://abuse.cloudflare.com/trademark

SAFE_BROWSING_API = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

# ============================================================
# MARKA AYARLARI — GÜNCEL (02 Temmuz 2026 itibarıyla)
# ============================================================
# NOT: Bu, host_auto_complaint.py / nicenic_complaint.py ile AYNI kaynak
# yapısı. Yeni bir resmi domain eklendiğinde/çıkarıldığında sadece burayı
# güncellemek yeterli — WHITELIST otomatik türüyor, elle range YAZILMAZ.
# Geniş numara aralıkları (range(1539,1701) gibi) fraud domainleri
# (ör. betsat1594.com) yanlışlıkla koruma altına alabiliyor — bu yüzden
# artık sadece gerçek, tek tek doğrulanmış resmi domainler kullanılıyor.
BRANDS = {
    "superbetin": {
        "name": "SUPERBETIN",
        "official_site": "superbetin.com",
        "active_domains": ["superbetin.com", "superbetin2077.com"],
    },
    "betsat": {
        "name": "BETSAT",
        "official_site": "betsat.com",
        "active_domains": ["betsat.com", "betsat1605.com"],
    },
    "turkbet": {
        "name": "TURKBET",
        "official_site": "turkbet.io",
        "active_domains": ["turkbet.io", "745turkbet.com"],
    },
}
WHITELIST = set()
for _brand in BRANDS.values():
    WHITELIST.update(_brand["active_domains"])

# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def get_root(domain):
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else domain

def is_whitelisted(domain):
    return domain in WHITELIST or get_root(domain) in WHITELIST

def load_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else list(data)
    except:
        return []

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(list(data), f, indent=2)

def get_new_domains(all_domains, done_set):
    return [d for d in all_domains if not is_whitelisted(d) and d not in done_set]

def detect_brand_key(domain):
    """BUG FIX (22 Tem 2026): Öncesinde tüm platform raporlarında marka
    hardcoded 'SUPERBETIN' yazıyordu — betsat/turkbet domainleri bile
    yanlış markayla bildiriliyordu. Artık domain string'inden marka
    tespit edilip doğru marka adı/resmi site kullanılıyor."""
    d = domain.lower()
    if "betsat" in d or "besat" in d or "bestsat" in d:
        return "betsat"
    elif "turkbet" in d or "turcbet" in d or "trkbet" in d:
        return "turkbet"
    return "superbetin"

def brand_reason_text(domain, brand_key):
    brand = BRANDS[brand_key]
    return (
        f"Phishing site impersonating {brand['name']} ({brand['official_site']}), "
        f"licensed betting brand operated by Poligon Entertainment N.V. "
        f"(Curaçao OGL/2024/815/0653). Domain {domain} fraudulently "
        f"collects user credentials and/or bank transfers from "
        f"Turkish-speaking users."
    )

# ============================================================
# YAYGIN PHISHING PATH / SUBDOMAIN KEŞFİ (v2 — 22 Tem 2026)
# host_auto_complaint_v2.py ile aynı mantık: domain'in bilinen fraud
# path/subdomain kombinasyonlarında canlı yanıt olup olmadığı
# kontrol edilir, gerçekten yanıt veren URL'ler kanıt olarak
# platform raporlarına eklenir (sadece kök domain yerine).
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

# Domain başına keşfedilen URL'leri önbelleğe alır — aynı domain birden
# fazla platform döngüsünde tekrar taranmasın diye (performans).
_url_cache = {}

async def _check_url(session, semaphore, url):
    async with semaphore:
        try:
            async with session.get(url, timeout=URL_CHECK_TIMEOUT, allow_redirects=True, ssl=False) as resp:
                if resp.status in (200, 301, 302, 403):
                    return url
        except Exception:
            pass
    return None

async def discover_phishing_urls(session, root_domain, max_results=8):
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

async def get_found_urls(session, domain):
    root = get_root(domain)
    if root in _url_cache:
        return _url_cache[root]
    urls = await discover_phishing_urls(session, root)
    _url_cache[root] = urls
    return urls

# ============================================================
# 1. GOOGLE SAFE BROWSING — Kontrol + Bildir
# ============================================================
async def check_safe_browsing(session, urls):
    if not SAFE_BROWSING_API_KEY:
        return []
    payload = {
        "client": {"clientId": "poligon-phishing-scanner", "clientVersion": "2.0.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": f"https://{u}"} for u in urls]
        }
    }
    try:
        async with session.post(
            f"{SAFE_BROWSING_API}?key={SAFE_BROWSING_API_KEY}",
            json=payload, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("matches", [])
    except Exception as e:
        print(f"Safe Browsing API hatası: {e}")
    return []

async def report_safe_browsing(session, domain, found_urls=None, brand_key=None):
    """Google Safe Browsing phishing bildir. En spesifik kanıt URL'i
    (ör. /login.php) varsa onu, yoksa kök domain'i bildirir."""
    target = found_urls[0] if found_urls else f"https://{domain}"
    if not target.startswith("http"):
        target = f"https://{target}"
    try:
        async with session.get(
            "https://safebrowsing.google.com/safebrowsing/report_phish/",
            params={"url": target},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            return resp.status in [200, 204, 302]
    except:
        return False

# ============================================================
# 2. GOOGLE SPAM REPORT
# ============================================================
async def report_google_spam(session, domain, found_urls=None, brand_key=None):
    """
    Google Search Console spam bildir.
    POST ile form submission — captcha gerektirmiyor.
    """
    brand_key = brand_key or detect_brand_key(domain)
    comments = brand_reason_text(domain, brand_key)
    if found_urls:
        urls_list = "\n".join(found_urls)
        comments += f"\n\nVerified live evidence URLs:\n{urls_list}"

    url = "https://www.google.com/webmasters/tools/spamreportform"
    data = {
        "hl": "en",
        "url": f"https://{domain}/",
        "ts": "1",          # spam type: deceptive page
        "comments": comments,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.google.com/",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        async with session.post(
            url, data=data, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True
        ) as resp:
            return resp.status in [200, 204, 302]
    except Exception as e:
        print(f"Google Spam hatası ({domain}): {e}")
        return False

# ============================================================
# 3. NETCRAFT
# ============================================================
async def report_netcraft(session, domain, found_urls=None, brand_key=None):
    """Netcraft phishing report API — birden fazla kanıt URL'i tek
    raporda gönderilebiliyor, bulunan tüm URL'ler eklenir."""
    brand_key = brand_key or detect_brand_key(domain)
    reason = brand_reason_text(domain, brand_key)

    urls_payload = [{"url": f"https://{domain}/", "reason": reason}]
    if found_urls:
        urls_payload = [{"url": u, "reason": reason} for u in found_urls]

    url = "https://report.netcraft.com/api/v3/report/urls"
    payload = {
        "email": "yardim@superbetin.com",
        "urls": urls_payload,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            return resp.status in [200, 201, 204]
    except Exception as e:
        print(f"Netcraft hatası ({domain}): {e}")
        return False

# ============================================================
# 4. MICROSOFT SMARTSCREEN
# ============================================================
async def report_smartscreen(session, domain, found_urls=None, brand_key=None):
    """Microsoft SmartScreen unsafe site report"""
    brand_key = brand_key or detect_brand_key(domain)
    comments = brand_reason_text(domain, brand_key)
    if found_urls:
        urls_list = "\n".join(found_urls)
        comments += f"\n\nVerified live evidence URLs:\n{urls_list}"

    target = found_urls[0] if found_urls else f"https://{domain}/"

    url = "https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site-guest"
    payload = {
        "url": target,
        "typeOfThreat": "Phishing",
        "comments": comments,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site"
    }
    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            return resp.status in [200, 201, 204]
    except Exception as e:
        print(f"SmartScreen hatası ({domain}): {e}")
        return False

# ============================================================
# 5. SPAM404
# ============================================================
async def report_spam404(session, domain, found_urls=None, brand_key=None):
    """
    Spam404 — online abuse reporting API.
    GET request ile bildirim yapılır, captcha yok. En spesifik kanıt
    URL'i (varsa) bildirilir.
    """
    target = found_urls[0] if found_urls else f"https://{domain}/"
    try:
        url = "https://www.spam404.com/report.html"
        params = {"url": target}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.spam404.com/",
            "Accept": "text/html,application/xhtml+xml"
        }
        async with session.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True
        ) as resp:
            text = await resp.text()
            if resp.status in [200, 302] and len(text) > 100:
                return True
            return False
    except Exception as e:
        print(f"Spam404 hatası ({domain}): {e}")
        return False

# ============================================================
# TELEGRAM
# ============================================================
async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            try:
                await session.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id.strip(),
                        "text": message,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    }
                )
            except Exception as e:
                print(f"Telegram hatası: {e}")

# ============================================================
# PLATFORM RUNNER — Tek domain için tüm platformları çalıştır
# ============================================================
async def run_platform(session, platform_name, report_func, domain, done_set, results):
    """Bir domain için tek platform bildir, sonucu kaydet.
    Önce (önbellekli) kanıt URL'leri ve marka tespit edilir, sonra
    report_func'a iletilir."""
    if domain in done_set:
        return "skipped"

    brand_key = detect_brand_key(domain)
    found_urls = await get_found_urls(session, domain)

    success = await report_func(session, domain, found_urls, brand_key)
    status = "ok" if success else "fail"
    results[platform_name]["ok" if success else "fail"].append(domain)
    done_set.add(domain)
    icon = "📤" if success else "❌"
    evidence_note = f" [{len(found_urls)} kanıt URL]" if found_urls else ""
    print(f"  {icon} [{platform_name}] {domain}{evidence_note}")
    return status

# ============================================================
# ANA FONKSİYON
# ============================================================
async def main():
    # Tüm reported domainleri topla
    all_domains = []
    for f in REPORTED_FILES:
        all_domains.extend(load_json(f))
    all_domains = list(set(all_domains))

    # Whitelist filtresi
    whitelisted = [d for d in all_domains if is_whitelisted(d)]
    candidates  = [d for d in all_domains if not is_whitelisted(d)]
    if whitelisted:
        print(f"🛡️ {len(whitelisted)} domain whitelist'te, atlandı.")

    # Her platform için "daha önce gönderildi" setleri
    sb_done       = set(load_json(SB_REPORTED_FILE))
    spam_done     = set(load_json(SPAM_REPORTED_FILE))
    netcraft_done = set(load_json(NETCRAFT_REPORTED_FILE))
    ss_done       = set(load_json(SMARTSCREEN_REPORTED_FILE))
    s404_done     = set(load_json(SPAM404_REPORTED_FILE))

    # Sonuç sayaçları
    results = {
        "safe_browsing": {"ok": [], "fail": [], "already_flagged": []},
        "google_spam":   {"ok": [], "fail": []},
        "netcraft":      {"ok": [], "fail": []},
        "smartscreen":   {"ok": [], "fail": []},
        "spam404":       {"ok": [], "fail": []},
    }

    print(f"\n🚀 {len(candidates)} domain işlenecek...\n")

    async with aiohttp.ClientSession() as session:
        # ── Safe Browsing: önce flagli mi kontrol et ──
        new_sb = get_new_domains(candidates, sb_done)
        if not SAFE_BROWSING_API_KEY:
            print("⚠️ SAFE_BROWSING_API_KEY eksik — Safe Browsing atlandı!")
            results["safe_browsing"]["fail"].extend(new_sb[:5])
        elif new_sb:
            print(f"[Safe Browsing] {len(new_sb)} domain kontrol ediliyor...")
            batch_size = 500
            for i in range(0, len(new_sb), batch_size):
                batch = new_sb[i:i+batch_size]
                matches = await check_safe_browsing(session, batch)
                for match in matches:
                    flagged = match.get("threat", {}).get("url", "").replace("https://", "")
                    if flagged:
                        results["safe_browsing"]["already_flagged"].append(flagged)
                        sb_done.add(flagged)
                        print(f"  ✅ [Safe Browsing] Zaten flagli: {flagged}")

            # Flagli olmayanları bildir
            not_flagged = [d for d in new_sb if d not in sb_done]
            print(f"[Safe Browsing] {len(not_flagged)} domain bildiriliyor...")
            for domain in not_flagged[:200]:
                await run_platform(
                    session, "safe_browsing",
                    report_safe_browsing, domain,
                    sb_done, results
                )
                await asyncio.sleep(0.5)

        # ── Diğer platformlar ──
        platforms = [
            ("google_spam", report_google_spam, spam_done,     SPAM_REPORTED_FILE),
            ("netcraft",    report_netcraft,    netcraft_done, NETCRAFT_REPORTED_FILE),
            ("smartscreen", report_smartscreen, ss_done,       SMARTSCREEN_REPORTED_FILE),
            ("spam404",     report_spam404,     s404_done,     SPAM404_REPORTED_FILE),
        ]
        for platform_name, report_func, done_set, _ in platforms:
            new_for_platform = get_new_domains(candidates, done_set)
            if not new_for_platform:
                print(f"[{platform_name}] Yeni domain yok, atlandı.")
                continue
            print(f"\n[{platform_name}] {len(new_for_platform)} domain bildiriliyor...")
            for domain in new_for_platform[:200]:
                await run_platform(
                    session, platform_name,
                    report_func, domain,
                    done_set, results
                )
                await asyncio.sleep(0.3)

    # ── Tüm setleri kaydet ──
    save_json(SB_REPORTED_FILE,          list(sb_done))
    save_json(SPAM_REPORTED_FILE,        list(spam_done))
    save_json(NETCRAFT_REPORTED_FILE,    list(netcraft_done))
    save_json(SMARTSCREEN_REPORTED_FILE, list(ss_done))
    save_json(SPAM404_REPORTED_FILE,     list(s404_done))

    # ── Telegram Raporu ──
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"🛡️ *[MULTI REPORTER] Rapor* — {now}\n\n"

    if not SAFE_BROWSING_API_KEY:
        msg += "⚠️ *SAFE_BROWSING_API_KEY eksik!* Safe Browsing atlandı.\n\n"

    platform_labels = {
        "safe_browsing": "🔴 Google Safe Browsing",
        "google_spam":   "📛 Google Spam",
        "netcraft":      "🌐 Netcraft",
        "smartscreen":   "🪟 SmartScreen",
        "spam404":       "🚫 Spam404",
    }

    for key, label in platform_labels.items():
        r = results[key]
        ok_count   = len(r["ok"])
        fail_count = len(r["fail"])
        flagged    = len(r.get("already_flagged", []))
        total      = ok_count + fail_count + flagged
        if total == 0:
            continue
        msg += f"{label}:\n"
        if flagged:
            msg += f"  ✅ Zaten flagli: {flagged}\n"
        if ok_count:
            msg += f"  📤 Bildirilen: {ok_count}\n"
            for d in r["ok"][:3]:
                msg += f"    • `{d}`\n"
            if ok_count > 3:
                msg += f"    • ... +{ok_count-3} domain\n"
        if fail_count:
            msg += f"  ❌ Başarısız: {fail_count}\n"
            for d in r["fail"][:3]:
                msg += f"    • `{d}`\n"
        msg += "\n"

    if whitelisted:
        msg += f"🛡️ *Whitelist (atlandı):* {len(whitelisted)} domain\n\n"

    total_ok   = sum(len(results[k]["ok"])   for k in results)
    total_fail = sum(len(results[k]["fail"]) for k in results)
    msg += f"📊 *Toplam:* {total_ok} başarılı / {total_fail} başarısız"

    await send_telegram(msg)

    print(f"\n✅ Tamamlandı!")
    for key, label in platform_labels.items():
        r = results[key]
        print(f"  {label}: ✅{len(r['ok'])} ❌{len(r['fail'])}")

if __name__ == "__main__":
    asyncio.run(main())
