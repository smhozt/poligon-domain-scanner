import asyncio
import aiohttp
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

TZ_SOFIA = timezone(timedelta(hours=3))
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

REPORTED_FILES = [
    "reported.json",
    "betsat_reported.json",
    "turkbet_reported.json",
]
COMPLAINT_FILE = "complaint_reported.json"
NICENIC_ABUSE = "abuse@nicenic.net"
NICENIC_SUPPORT = "support@nicenic.net"

# ============================================================
# MARKA AYARLARI — GÜNCEL (02 Temmuz 2026 itibarıyla)
# ============================================================
# NOT: active_domains listesi WHITELIST'i otomatik besler (aşağıya bakın).
# Yeni bir resmi domain eklendiğinde SADECE burayı güncellemek yeterli.
BRANDS = {
    "superbetin": {
        "name": "Superbetin",
        "fixed_domain": "superbetin.com",
        "active_domains": [
            "superbetin.com",
            "superbetin2077.com",
        ],
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa1V2TXpJM2MyWjFSV0pRYW1OQ1IxcFVkbEJMZGxFOVBTSXNJblpoYkhWbElqb2lMMVpTUXpSbU5XdG9lbkJHVlZSak1EVlJWMmxLZHowOUlpd2liV0ZqSWpvaVpXTXdaak5rWW1NeVlURXlNR1F6WkRFNVlqVmxabVJoTkdWak5qZzBNRGt3WVRVMFpHUmtNakppTXpnMVlUUmpaVFJrTW1JelpEazJZalJrTWpJd1l5SXNJblJoWnlJNklpSjk="
    },
    "betsat": {
        "name": "Betsat",
        "fixed_domain": "betsat.com",
        "active_domains": [
            "betsat.com",
            "betsat1606.com",
        ],
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJamRoY1ZkVFdIWnJjbG95T1hkbWFVd3paRUZETWxFOVBTSXNJblpoYkhWbElqb2lSbmxvTVVzelJGRkhWMmh4ZVVFNGJIUkJLM2xoZHowOUlpd2liV0ZqSWpvaU1URmxZamhqTUdVMk1UZzBObUpoTmpkaU5tTXdNR0pqTmpkaFl6Z3pabVk0WVdFMVpUYzJabVF6T0dJeE5qVmtNV1E0WlRVM1pUWTJPV1JrWVdRM01pSXNJblJoWnlJNklpSjk="
    },
    "turkbet": {
        "name": "Turkbet",
        "fixed_domain": "turkbet.io",
        "active_domains": [
            "turkbet.io",
            "749turkbet.com",
        ],
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa3ROY2xoWFUyUTBWbXR1WkV0cGMzQndUek16Y1djOVBTSXNJblpoYkhWbElqb2lVRVZhVGsxWmJUSTNWV1ZCTnpkMGMySXJUVGQxZHowOUlpd2liV0ZqSWpvaU1EYzBZVGc1TmpCallUZzBZbVF3TlRRMVpHTTRNVEJrTkRBeE56WXpOemRsTlROaFkyVTBaR1JrWkdNNE1XWXdaR0ZsTVRBNU1HUTJOVFkxWmpJek5DSXNJblJoWnlJNklpSjk="
    }
}

# ============================================================
# WHİTELİST — otomatik türetilir (elle range YOK)
# ============================================================
# ÖNEMLİ: Fraud domainler resmi numaralara kasıtlı olarak çok yakın
# seçiliyor (ör. betsat1594.com — resmi betsat1596.com'a bir basamak
# yakın). Geniş numara aralıkları (range(1539, 1701) gibi) bu yüzden
# KULLANILMAZ — bir fraud domain kolayca aralığa düşüp yanlışlıkla
# korunabilir. Whitelist SADECE BRANDS içinde tek tek listelenen
# gerçek resmi domainlerden oluşur.
WHITELIST = set()
for _brand in BRANDS.values():
    WHITELIST.add(_brand["fixed_domain"])
    WHITELIST.update(_brand["active_domains"])

# ============================================================
# YAYGIN PHISHING PATH / SUBDOMAIN KEŞFİ (v2 — 22 Tem 2026)
# host_auto_complaint_v2.py / multi_reporter_v3.py ile aynı mantık.
# NiceNIC bugün defalarca "tam URL + sayfa içeriği + timestamp kanıtı"
# istedi (RFI süreci) — ilk şikayet mailine canlı doğrulanmış URL'ler
# eklenerek bu geri-dönüş döngüsü azaltılmaya çalışılıyor.
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

async def discover_phishing_urls(session, root_domain, max_results=10):
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

def get_root(domain):
    """Subdomain varsa root domain'i döndür: tr.foo.vip → foo.vip"""
    parts = domain.split(".")
    if len(parts) > 2:
        return ".".join(parts[-2:])
    return domain

def detect_brand_key(domain):
    d = domain.lower()
    if "betsat" in d or "besat" in d or "bestsat" in d or "betsatm" in d:
        return "betsat"
    elif "turkbet" in d or "turcbet" in d or "trkbet" in d:
        return "turkbet"
    else:
        return "superbetin"

def is_whitelisted(domain):
    root = get_root(domain)
    return domain in WHITELIST or root in WHITELIST

def build_nicenic_email(domain, brand_key, found_urls=None):
    brand_info = BRANDS[brand_key]
    brand_name = brand_info["name"]
    fixed_domain = brand_info["fixed_domain"]
    active_domains_str = " / ".join(brand_info["active_domains"])
    license_url = brand_info["license_url"]

    subject = f"URGENT: Phishing Domain - {domain} - Immediate ClientHold Required"

    if found_urls:
        urls_block = "\n".join(f"- {u}" for u in found_urls)
        evidence_section = f"\nReported URLs (live-verified at time of report):\n{urls_block}\n"
    else:
        evidence_section = ""

    body = f"""Dear NiceNIC Abuse Team,

We are reporting a fraudulent domain registered through your services:

Domain: {domain}

This domain is an active phishing site cloning our licensed brand ({brand_name}), designed to steal user credentials and collect fraudulent bank transfers from Turkish users.
{evidence_section}
This is part of an ongoing serial fraud operation using your platform. Multiple domains from the same registrant cluster have already been placed on ClientHold by NiceNIC based on our previous reports.

We are a licensed operator: {fixed_domain} is operated by Poligon Entertainment N.V., licensed by the Curaçao Gaming Authority under license OGL/2024/815/0653 (Company Number 132517). Status: Active.
License verification: {license_url}
Our official domains: {active_domains_str}

We urgently request:
1. Immediate ClientHold suspension of {domain}
2. Investigation of all domains registered by the same registrant account

Best regards,
{brand_name} Security Team
security@{fixed_domain.replace('.io', '.com')}
"""
    return subject, body

def send_email(to_addresses, subject, body, from_name="Security Team"):
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP bilgileri eksik!")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = f"{from_name} <{SMTP_USER}>"
        msg["To"] = ", ".join(to_addresses)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_addresses, msg.as_string())
        return True
    except Exception as e:
        print(f"Mail gönderme hatası: {e}")
        return False

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
    all_reported = []
    for f in REPORTED_FILES:
        all_reported.extend(load_json(f))

    complaint_done = set(load_json(COMPLAINT_FILE))
    new_domains = []
    skipped_whitelist = []
    for d in all_reported:
        root = get_root(d)
        if is_whitelisted(d):
            skipped_whitelist.append(d)
            print(f"  🛡️ Whitelist'te, atlandı: {d}")
            continue
        if d not in complaint_done and root not in complaint_done:
            new_domains.append(d)

    if skipped_whitelist:
        print(f"\n⚠️ {len(skipped_whitelist)} domain whitelist'te — şikayet edilmedi.")

    if not new_domains:
        print("Şikayet gönderilecek yeni domain yok.")
        return

    print(f"{len(new_domains)} domain için şikayet gönderilecek...")

    success_list = []
    failed_list = []
    sent_roots = set()

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as http_session:
        for domain in new_domains[:20]:
            root = get_root(domain)
            if root in sent_roots:
                print(f"  ⏭️ Atlandı (duplicate root): {root}")
                complaint_done.add(domain)
                continue

            brand_key = detect_brand_key(domain)
            brand_name = BRANDS[brand_key]["name"]

            print(f"  🔎 Bilinen fraud path/subdomain kombinasyonları test ediliyor: {root}")
            found_urls = await discover_phishing_urls(http_session, root)
            if found_urls:
                print(f"    📎 {len(found_urls)} canlı URL bulundu, mail'e eklenecek")
            else:
                print(f"    (canlı path/subdomain bulunamadı — genel şablonla gönderiliyor)")

            subject, body = build_nicenic_email(root, brand_key, found_urls)
            print(f"Şikayet gönderiliyor: {root} ({brand_name})")
            success = send_email(
                [NICENIC_ABUSE, NICENIC_SUPPORT],
                subject,
                body,
                from_name=f"{brand_name} Security Team"
            )
            if success:
                success_list.append((domain, len(found_urls)))
                complaint_done.add(domain)
                complaint_done.add(root)
                sent_roots.add(root)
                print(f"  ✅ Gönderildi: {root}")
            else:
                failed_list.append(domain)
                print(f"  ❌ Başarısız: {root}")

            await asyncio.sleep(5)

    save_json(COMPLAINT_FILE, list(complaint_done))

    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"📧 *[OTO-ŞİKAYET] NICENIC Mail Raporu* — {now}\n\n"
    if success_list:
        msg += f"✅ *Gönderilen:* {len(success_list)} şikayet\n"
        for d, url_count in success_list[:10]:
            b_key = detect_brand_key(d)
            icon = "🔵" if b_key == "superbetin" else "🟠" if b_key == "betsat" else "🟢"
            evidence_note = f" ({url_count} URL kanıtı)" if url_count else ""
            msg += f"  {icon} `{d}`{evidence_note}\n"
        if len(success_list) > 10:
            msg += f"  ... ve {len(success_list)-10} tane daha\n"
        msg += "\n"
    if failed_list:
        msg += f"❌ *Başarısız:* {len(failed_list)} şikayet\n"
    if skipped_whitelist:
        msg += f"🛡️ *Whitelist (atlandı):* {len(skipped_whitelist)} domain\n"
    msg += f"\n📬 *Gönderen:* `{SMTP_USER}`\n"
    msg += f"📮 *Alıcı:* `{NICENIC_ABUSE}`\n"
    msg += f"📮 *Alıcı:* `{NICENIC_SUPPORT}`"

    await send_telegram(msg)
    print(f"\n✅ Tamamlandı! {len(success_list)} mail gönderildi.")

if __name__ == "__main__":
    asyncio.run(main())
