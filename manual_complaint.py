import asyncio
import aiohttp
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

try:
    import dns.resolver
except ImportError:
    raise SystemExit("dnspython gerekli: pip install dnspython --break-system-packages")

TZ_SOFIA = timezone(timedelta(hours=3))
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SAFE_BROWSING_API_KEY = os.environ.get("SAFE_BROWSING_API_KEY", "")

# ============================================================
# PANELDEN GELEN GİRDİLER (GitHub Actions workflow_dispatch inputs)
# ============================================================
INPUT_DOMAINS        = os.environ.get("INPUT_DOMAINS", "")
INPUT_BRAND          = os.environ.get("INPUT_BRAND", "auto").strip().lower()
INPUT_TARGETS        = os.environ.get("INPUT_TARGETS", "all").strip().lower()
INPUT_CUSTOM_EMAIL   = os.environ.get("INPUT_CUSTOM_EMAIL", "").strip()
INPUT_ACTIVE_OVERRIDE = os.environ.get("INPUT_ACTIVE_OVERRIDE", "").strip()
INPUT_NOTES          = os.environ.get("INPUT_NOTES", "").strip()
# "Bu şikayeti biz olarak hangi mailden bildiriyoruz" — Netcraft'ın
# formundaki 'email' (reporter contact) alanını ve giden maillerin
# Reply-To başlığını belirler. Boş bırakılırsa markanın kendi
# signature_email'i kullanılır (mevcut davranış).
INPUT_REPORTER_EMAIL = os.environ.get("INPUT_REPORTER_EMAIL", "").strip()

# Bu manuel tetiklemenin de otomatik taramalarla çakışmaması için aynı
# "reported" dosyalarına eklenir (varsa) — böylece batch script'ler bu
# domaini tekrar rapor etmeye çalışmaz.
REPORTED_FILES_TO_UPDATE = ["reported.json", "betsat_reported.json", "turkbet_reported.json"]

# ============================================================
# MARKA AYARLARI
# ============================================================
BRANDS = {
    "superbetin": {
        "name": "Superbetin",
        "fixed_domain": "superbetin.com",
        "active_domains": ["superbetin.com", "superbetin2082.com"],
        "signature_email": "yardim@superbetin.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa1V2TXpJM2MyWjFSV0pRYW1OQ1IxcFVkbEJMZGxFOVBTSXNJblpoYkhWbElqb2lMMVpTUXpSbU5XdG9lbkJHVlZSak1EVlJWMmxLZHowOUlpd2liV0ZqSWpvaVpXTXdaak5rWW1NeVlURXlNR1F6WkRFNVlqVmxabVJoTkdWak5qZzBNRGt3WVRVMFpHUmtNakppTXpnMVlUUmpaVFJrTW1JelpEazJZalJrTWpJd1l5SXNJblJoWnlJNklpSjk="
    },
    "betsat": {
        "name": "Betsat",
        "fixed_domain": "betsat.com",
        "active_domains": ["betsat.com", "betsat1605.com"],
        "signature_email": "support@betsat.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJamRoY1ZkVFdIWnJjbG95T1hkbWFVd3paRUZETWxFOVBTSXNJblpoYkhWbElqb2lSbmxvTVVzelJGRkhWMmh4ZVVFNGJIUkJLM2xoZHowOUlpd2liV0ZqSWpvaU1URmxZamhqTUdVMk1UZzBObUpoTmpkaU5tTXdNR0pqTmpkaFl6Z3pabVk0WVdFMVpUYzJabVF6T0dJeE5qVmtNV1E0WlRVM1pUWTJPV1JrWVdRM01pSXNJblJoWnlJNklpSjk="
    },
    "turkbet": {
        "name": "Turkbet",
        "fixed_domain": "turkbet.io",
        "active_domains": ["turkbet.io", "749turkbet.com"],
        "signature_email": "support@turkbet.co",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa3ROY2xoWFUyUTBWbXR1WkV0cGMzQndUek16Y1djOVBTSXNJblpoYkhWbElqb2lVRVZhVGsxWmJUSTNWV1ZCTnpkMGMySXJUVGQxZHowOUlpd2liV0ZqSWpvaU1EYzBZVGc1TmpCallUZzBZbVF3TlRRMVpHTTRNVEJrTkRBeE56WXpOemRsTlROaFkyVTBaR1JrWkdNNE1XWXdaR0ZsTVRBNU1HUTJOVFkxWmpJek5DSXNJblJoWnlJNklpSjk=",
        "signature_footer": (
            "Turkbet, Curaçao yasalarına göre kurulmuş olan Poligon Entertainment N.V. "
            "tarafından işletilmektedir. 132517 şirket numarasıyla kayıtlı olan bu şirket, "
            "Curaçao Oyun Otoritesi tarafından verilen OGL/2024/815/0653 numaralı lisans "
            "kapsamında şans oyunları sunma yetkisine sahiptir."
        ),
    },
}

# Panelden "güncel site adresimiz" olarak girilen ek domainleri bu
# çalıştırma için active_domains listelerine ekle (kod değiştirmeden
# anlık override imkanı — resmi domain değiştiğinde script'i
# güncellemeden panelden geçici olarak düzeltebilmek için).
if INPUT_ACTIVE_OVERRIDE:
    override_domains = [d.strip() for d in INPUT_ACTIVE_OVERRIDE.split(",") if d.strip()]
    for brand_key in BRANDS:
        for od in override_domains:
            if brand_key in od.lower() and od not in BRANDS[brand_key]["active_domains"]:
                BRANDS[brand_key]["active_domains"].append(od)
    # Marka tespit edilemeyen override'lar (örn. yeni bir TLD) her
    # markanın whitelist'ine de eklenir, güvenli taraf seçildi.
    for brand_key in BRANDS:
        for od in override_domains:
            if od not in BRANDS[brand_key]["active_domains"] and not any(
                bk in od.lower() for bk in BRANDS
            ):
                pass  # marka belirsiz override'lar sadece bilgi amaçlı, dokunulmuyor

# ============================================================
# HOSTLAR — abuse adresleri + NS cluster haritası (host_auto_complaint_v2.py
# ile aynı kaynak)
# ============================================================
HOSTS = {
    "netiface":        {"name": "Netiface LLC / VPS Dedicated LLC",     "abuse": ["abuse@abusehandler.net", "abuse@vpsdedicated.net"]},
    "omegatech":       {"name": "Omegatech LTD",                        "abuse": ["abuse@pitline.net", "abuse@omegatech.sc"]},
    "advin":           {"name": "Advin Services LLC",                   "abuse": ["anush@advinservers.com"]},
    "swissnet":        {"name": "SwissNet LLC",                          "abuse": ["abuse@swissnetwork.io"]},
    "prq":             {"name": "PRQ VPN Network SE",                    "abuse": ["abuse@dcs.net"]},
    "fatcat_scrhost":  {"name": "FATCAT-AS / scrhost.com",               "abuse": ["info@scrhost.com"]},
    "fatcat_epikhost": {"name": "FATCAT NETWORK S.A.",                   "abuse": ["abuse@epikhost.org"]},
    "vpsdatacenter":   {"name": "VPS Datacenter Ltd (private-data-center.com)", "abuse": ["abuse@private-data-center.com"]},
    "colocatel":       {"name": "ColocaTel Inc.",                        "abuse": ["abuse@colocatel.com"]},
    "evoxt":           {"name": "Evoxt Sdn. Bhd.",                       "abuse": ["abuse@evoxt.com"]},
    "cloudzy":         {"name": "RouterHosting/Cloudzy",                 "abuse": ["abuse-reports@cloudzy.com"]},
    "play2go":         {"name": "PLAY2GO INTERNATIONAL LIMITED",         "abuse": ["abuse@play2go.cloud"]},
    "namecheap":       {"name": "Namecheap, Inc.",                       "abuse": ["abuse@namecheaphosting.com"]},
    "pfcloud":         {"name": "Pfcloud UG (abusehandler.net)",         "abuse": ["abuse@abusehandler.net"]},
    "pfcloud_io":      {"name": "Pfcloud UG (pfcloud.io)",               "abuse": ["abuse@pfcloud.io"]},
    "sahinnetwork":    {"name": "Bursabil Teknoloji A.Ş.",               "abuse": ["abuse@sahinnetwork.com"]},
    "frantech":        {"name": "FranTech Solutions (PONYNET)",          "abuse": ["admin@frantech.ca"]},
}

CLUSTER_MAP = {
    # ── Netiface LLC / VPS Dedicated LLC (abusehandler.net ailesi) ──
    frozenset({"drew", "leia"}):        "netiface",
    frozenset({"carol", "mustafa"}):    "netiface",
    frozenset({"conrad", "leia"}):      "netiface",
    frozenset({"remy", "stella"}):      "netiface",
    frozenset({"keaton", "shaz"}):      "netiface",
    frozenset({"venus", "carmelo"}):    "netiface",
    frozenset({"justin", "sierra"}):    "netiface",
    frozenset({"buck", "phoenix"}):     "netiface",
    frozenset({"princess", "rory"}):    "netiface",
    frozenset({"charles", "novalee"}):  "netiface",
    frozenset({"benedict", "ophelia"}): "netiface",
    frozenset({"georgia", "kobe"}):     "netiface",
    frozenset({"devin", "nucum"}):      "netiface",
    frozenset({"brady", "harmony"}):    "netiface",   # DÜZELTİLDİ (önceden yanlışlıkla vpsdatacenter'dı)
    frozenset({"colin", "nena"}):       "netiface",   # DÜZELTİLDİ (önceden yanlışlıkla vpsdatacenter'dı)

    # ── Omegatech LTD ──
    frozenset({"syeef", "tina"}):       "omegatech",
    frozenset({"isla", "nolan"}):       "omegatech",
    frozenset({"aisha", "langston"}):   "omegatech",
    frozenset({"archer", "melissa"}):   "omegatech",
    frozenset({"dane", "alice"}):       "omegatech",
    frozenset({"aleena", "tony"}):      "omegatech",
    frozenset({"luciane", "oswald"}):   "omegatech",

    # ── Advin Services LLC ──
    frozenset({"ruben", "ariella"}):    "advin",
    frozenset({"raegan", "gabe"}):      "advin",

    # ── SwissNet LLC ──
    frozenset({"penny", "tanner"}):     "swissnet",
    frozenset({"elliot", "marlowe"}):   "swissnet",
    frozenset({"ainsley", "lamar"}):    "swissnet",
    frozenset({"lee", "aida"}):         "swissnet",

    # ── PRQ VPN Network SE ──
    frozenset({"decker", "liberty"}):   "prq",
    frozenset({"paris", "porter"}):     "prq",

    # ── FATCAT ailesi (DİKKAT: iki farklı abuse adresi var) ──
    frozenset({"gail", "lennox"}):      "fatcat_scrhost",
    frozenset({"candy", "nico"}):       "fatcat_scrhost",
    frozenset({"robin", "ram"}):        "fatcat_scrhost",
    frozenset({"alice", "seamus"}):     "fatcat_epikhost",

    # ── VPS Datacenter Ltd GB (private-data-center.com) ──
    frozenset({"ophelia", "theo"}):     "vpsdatacenter",
    frozenset({"garrett", "indie"}):    "vpsdatacenter",
    frozenset({"kipp", "penny"}):       "vpsdatacenter",
    frozenset({"eve", "sean"}):         "vpsdatacenter",
    frozenset({"jewel", "vin"}):        "vpsdatacenter",
    frozenset({"achiel", "nicole"}):    "vpsdatacenter",
    frozenset({"andronicus", "emely"}): "vpsdatacenter",

    # ── Diğer host'lar ──
    frozenset({"opal", "ricardo"}):     "evoxt",
    frozenset({"aron", "javier"}):      "colocatel",
    frozenset({"bowen", "rosemary"}):   "colocatel",
    frozenset({"paityn", "titan"}):     "cloudzy",
    frozenset({"gannon", "nancy"}):     "play2go",
    frozenset({"brenda", "leif"}):      "namecheap",
    frozenset({"candy", "edward"}):     "pfcloud",
    frozenset({"huxley", "kami"}):      "pfcloud_io",
    frozenset({"bonnie", "fred"}):      "sahinnetwork",
    frozenset({"katja", "tosana"}):     "frantech",
    frozenset({"ernest", "oaklyn"}):    "netiface",
    frozenset({"adi", "langston"}):     "vpsdatacenter",
    frozenset({"kurt", "leah"}):        "colocatel",
    frozenset({"donovan", "melinda"}):  "omegatech",
}

DEAD_DOMAIN = "__dead__"

def get_ns_labels(domain):
    try:
        answers = dns.resolver.resolve(domain, "NS", lifetime=8)
        return {str(r.target).rstrip(".").lower().split(".")[0] for r in answers}
    except dns.resolver.NXDOMAIN:
        return "NXDOMAIN"
    except Exception as e:
        print(f"    ⚠️ NS lookup başarısız ({domain}): {e}")
        return None

def match_cluster(ns_labels):
    if not ns_labels:
        return None, None
    for pair, host_key in CLUSTER_MAP.items():
        if pair.issubset(ns_labels):
            return pair, host_key
    return None, None

def resolve_host(domain):
    ns_labels = get_ns_labels(domain)
    if ns_labels == "NXDOMAIN":
        return None, DEAD_DOMAIN
    return match_cluster(ns_labels)

# ============================================================
# YAYGIN PHISHING PATH / SUBDOMAIN KEŞFİ (diğer script'lerle aynı)
# ============================================================
COMMON_PHISHING_PATHS = [
    "/", "/login.php", "/spor/", "/spor/?mobile=1", "/casino/", "/canli-bahis/",
    "/modules/payments/deposit/", "/modules/payments/deposit/?payment_type=105",
    "/modules/payments/deposit/?payment_type=109", "/modules/payments/deposit/?payment_type=117",
    "/payment/view/havale.php", "/payment/view/bitcoin.php",
    "/payment/bank/nethavale/", "/payment/bank/otomonay/", "/payment/crypto/kriptopay/",
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
    urls_to_check = [f"https://{root_domain}{p}" for p in COMMON_PHISHING_PATHS]
    for sub in COMMON_PHISHING_SUBDOMAINS:
        for dpath in SUBDOMAIN_DEPOSIT_PATHS:
            urls_to_check.append(f"https://{sub}.{root_domain}{dpath}")
    semaphore = asyncio.Semaphore(URL_CHECK_CONCURRENCY)
    tasks = [_check_url(session, semaphore, u) for u in urls_to_check]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    found = [u for u in results if u]
    found.sort(key=lambda u: (u.rstrip("/").endswith(root_domain.rstrip("/")), len(u)))
    return found[:max_results]

def get_root(domain):
    domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else domain

def detect_brand_key(domain):
    if INPUT_BRAND in BRANDS:
        return INPUT_BRAND
    d = domain.lower()
    if "betsat" in d or "besat" in d or "bestsat" in d:
        return "betsat"
    elif "turkbet" in d or "turcbet" in d or "trkbet" in d:
        return "turkbet"
    return "superbetin"

def evidence_block(found_urls):
    if not found_urls:
        return ""
    urls_block = "\n".join(f"- {u}" for u in found_urls)
    return f"\nReported URLs (live-verified at time of report):\n{urls_block}\n"

def notes_block():
    if not INPUT_NOTES:
        return ""
    return f"\nAdditional context from reporting team:\n{INPUT_NOTES}\n"

# ============================================================
# EMAIL GÖNDERİCİ
# ============================================================
def send_email(to_addresses, subject, body, from_name="Security Team", reply_to=None):
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP bilgileri eksik!")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = f"{from_name} <{SMTP_USER}>"
        msg["To"] = ", ".join(to_addresses)
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_addresses, msg.as_string())
        return True
    except Exception as e:
        print(f"Mail gönderme hatası: {e}")
        return False

def reporter_email_for(brand_key):
    """Panelden girilen reporter e-postası varsa onu, yoksa markanın
    kendi signature_email'ini döndürür."""
    return INPUT_REPORTER_EMAIL or BRANDS[brand_key]["signature_email"]

# ============================================================
# HEDEF: NICENIC
# ============================================================
def send_nicenic(domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    subject = f"URGENT: Phishing Domain - {domain} - Immediate ClientHold Required"
    body = f"""Dear NiceNIC Abuse Team,

We are reporting a fraudulent domain registered through your services:

Domain: {domain}

This domain is an active phishing site cloning our licensed brand ({brand['name']}), designed to steal user credentials and collect fraudulent bank transfers from Turkish users.
{evidence_block(found_urls)}{notes_block()}
We are a licensed operator: {brand['fixed_domain']} is operated by Poligon Entertainment N.V., licensed by the Curaçao Gaming Authority under license OGL/2024/815/0653 (Company Number 132517). Status: Active.
License verification: {brand['license_url']}
Our official domains: {' / '.join(brand['active_domains'])}

We urgently request:
1. Immediate ClientHold suspension of {domain}
2. Investigation of all domains registered by the same registrant account

Best regards,
{brand['name']} Security Team
"""
    return send_email(
        ["abuse@nicenic.net", "support@nicenic.net"], subject, body,
        f"{brand['name']} Security Team", reply_to=reporter_email_for(brand_key)
    )

# ============================================================
# HEDEF: HOST (NS-tespitli)
# ============================================================
def send_host_complaint(domain, brand_key, found_urls, host_key, cluster_pair):
    brand = BRANDS[brand_key]
    host = HOSTS[host_key]
    cluster_label = "/".join(sorted(cluster_pair)) if cluster_pair else "manually confirmed hosting"
    subject = f"URGENT: Active Phishing & Trademark Infringement — {domain} — {host['name']} Hosted ({cluster_label})"
    body = f"""Dear {host['name']} Abuse Team,

We are writing on behalf of Poligon Entertainment N.V., the licensed operator of {brand['name']} (official: {' / '.join(brand['active_domains'])}), under Curaçao Gaming Authority license OGL/2024/815/0653.

The domain {domain}, hosted on your infrastructure via the {cluster_label} nameserver cluster, is operating an active phishing site impersonating our licensed brand, using cloned graphics, trademarked layouts, and fake login/payment forms to deceive consumers.
{evidence_block(found_urls)}{notes_block()}
We formally request immediate suspension of this domain.

Sincerely,
{brand['name']} Security Team
{brand['signature_email']}
"""
    return send_email(
        host["abuse"], subject, body,
        f"{brand['name']} Security Team", reply_to=reporter_email_for(brand_key)
    )

# ============================================================
# HEDEF: ÖZEL MAİL ADRESİ (panelden elle girilen)
# ============================================================
def send_custom_email(domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    recipients = [e.strip() for e in INPUT_CUSTOM_EMAIL.split(",") if e.strip()]
    if not recipients:
        return False
    subject = f"URGENT: Active Phishing / Trademark Infringement — {domain}"
    body = f"""Dear Abuse Team,

We are reporting an active phishing domain impersonating our licensed brand {brand['name']} (official: {' / '.join(brand['active_domains'])}), operated by Poligon Entertainment N.V. under Curaçao Gaming Authority license OGL/2024/815/0653.

Domain: {domain}
{evidence_block(found_urls)}{notes_block()}
We request immediate suspension/takedown of this domain.

Sincerely,
{brand['name']} Security Team
{brand['signature_email']}
"""
    return send_email(
        recipients, subject, body,
        f"{brand['name']} Security Team", reply_to=reporter_email_for(brand_key)
    )


def send_compromise_notice(domain, brand_key):
    """Hacklenmiş/ele geçirilmiş meşru üçüncü taraf siteler için — bunlar
    dolandırıcılık şüphelisi DEĞİL, kendileri de mağdur. Marka ihlali
    suçlaması yerine nazik bir güvenlik uyarısı gönderilir, suspension
    talebi YAPILMAZ. Alıcı adresi INPUT_CUSTOM_EMAIL'den alınır (site
    sahibinin kendi iletişim adresi, host/registrar abuse kutusu değil)."""
    brand = BRANDS[brand_key]
    recipients = [e.strip() for e in INPUT_CUSTOM_EMAIL.split(",") if e.strip()]
    if not recipients:
        return False
    subject = f"Security Notice — Your Website ({domain}) Appears to Be Compromised and Redirecting to Phishing Content"
    body = f"""Dear Site Owner,

We are writing on behalf of Poligon Entertainment N.V., operator of the licensed platform {brand['name']} (official site: {' / '.join(brand['active_domains'])}), under Curaçao Gaming Authority license OGL/2024/815/0653.

We wanted to alert you, as a courtesy, that your website ({domain}) appears to have been compromised and is currently being used — likely without your knowledge — as part of a phishing operation impersonating our brand.

We observed that visitors arriving at your domain via Google organic search referrals were being redirected to a credential-harvesting page impersonating {brand['name']}. This type of attack typically works by injecting malicious redirect code into a compromised website's files or CMS, exploiting the site's existing search engine trust to funnel victims toward fraudulent content — your business itself is not the target; your website's reputation is simply being abused as a delivery mechanism.
{notes_block()}
We recommend you check your website for unrecognized or recently modified files, unfamiliar plugins/scripts/admin accounts, and any unexpected redirect rules or injected JavaScript.

We are not asking anything of you regarding our brand — this is purely a security courtesy notice, as your own customers and search visibility may also be at risk from this compromise. Please feel free to reach out if you'd like further technical details we observed.

Kind regards,
CS Operations & Technology
Poligon Entertainment N.V.
{brand['signature_email']}
"""
    return send_email(recipients, subject, body, "Security Team", reply_to=reporter_email_for(brand_key))

# ============================================================
# HEDEF: PLATFORM RAPORLARI (Netcraft / Safe Browsing / Google Spam / SmartScreen / Spam404)
# ============================================================
async def report_netcraft(session, domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    reason = (
        f"Phishing site impersonating {brand['name'].upper()} ({brand['fixed_domain']}), "
        f"operated by Poligon Entertainment N.V. (Curaçao OGL/2024/815/0653)."
    )
    if INPUT_NOTES:
        reason += f" Notes: {INPUT_NOTES}"
    urls_payload = [{"url": u, "reason": reason} for u in found_urls] or [{"url": f"https://{domain}/", "reason": reason}]
    try:
        async with session.post(
            "https://report.netcraft.com/api/v3/report/urls",
            json={"email": reporter_email_for(brand_key), "urls": urls_payload},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return resp.status in (200, 201, 204)
    except Exception as e:
        print(f"Netcraft hatası: {e}")
        return False

async def report_safe_browsing(session, domain, found_urls):
    target = found_urls[0] if found_urls else f"https://{domain}"
    try:
        async with session.get(
            "https://safebrowsing.google.com/safebrowsing/report_phish/",
            params={"url": target}, timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            return resp.status in (200, 204, 302)
    except Exception:
        return False

async def report_google_spam(session, domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    comments = (
        f"Phishing site impersonating {brand['name'].upper()} ({brand['fixed_domain']}), "
        f"operated by Poligon Entertainment N.V. (Curaçao OGL/2024/815/0653)."
    )
    if found_urls:
        comments += "\n\nVerified live evidence URLs:\n" + "\n".join(found_urls)
    if INPUT_NOTES:
        comments += f"\n\nNotes: {INPUT_NOTES}"
    try:
        async with session.post(
            "https://www.google.com/webmasters/tools/spamreportform",
            data={"hl": "en", "url": f"https://{domain}/", "ts": "1", "comments": comments},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.google.com/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True,
        ) as resp:
            return resp.status in (200, 204, 302)
    except Exception as e:
        print(f"Google Spam hatası: {e}")
        return False

async def report_smartscreen(session, domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    comments = (
        f"Phishing site impersonating {brand['name'].upper()} ({brand['fixed_domain']}), "
        f"operated by Poligon Entertainment N.V. (Curaçao OGL/2024/815/0653)."
    )
    if found_urls:
        comments += "\n\nVerified live evidence URLs:\n" + "\n".join(found_urls)
    target = found_urls[0] if found_urls else f"https://{domain}/"
    try:
        async with session.post(
            "https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site-guest",
            json={"url": target, "typeOfThreat": "Phishing", "comments": comments},
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://www.microsoft.com/en-us/wdsi/support/report-unsafe-site",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            return resp.status in (200, 201, 204)
    except Exception as e:
        print(f"SmartScreen hatası: {e}")
        return False

async def report_spam404(session, domain, found_urls):
    target = found_urls[0] if found_urls else f"https://{domain}/"
    try:
        async with session.get(
            "https://www.spam404.com/report.html", params={"url": target},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.spam404.com/",
            },
            timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True,
        ) as resp:
            text = await resp.text()
            return resp.status in (200, 302) and len(text) > 100
    except Exception as e:
        print(f"Spam404 hatası: {e}")
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
                        "chat_id": chat_id.strip(), "text": message,
                        "parse_mode": "Markdown", "disable_web_page_preview": True,
                    },
                )
            except Exception as e:
                print(f"Telegram hatası: {e}")

# ============================================================
# JSON YARDIMCI (reported dosyalarını güncellemek için)
# ============================================================
def append_to_reported_files(domain):
    for fname in REPORTED_FILES_TO_UPDATE:
        try:
            with open(fname, "r") as f:
                data = set(json.load(f))
        except Exception:
            data = set()
        data.add(domain)
        with open(fname, "w") as f:
            json.dump(list(data), f)

# ============================================================
# ANA FONKSİYON
# ============================================================
async def main():
    if not INPUT_DOMAINS:
        print("INPUT_DOMAINS boş — işlenecek domain yok.")
        return

    domains = [d.strip() for d in INPUT_DOMAINS.replace("\n", ",").split(",") if d.strip()]
    domains = [get_root(d) for d in domains]

    requested_targets = set(INPUT_TARGETS.split(","))
    # compromise_notice bilinçli olarak "all" kısayoluna DAHİL EDİLMEZ —
    # bu, gerçek dolandırıcılık domain'leri için değil, hacklenmiş/ele
    # geçirilmiş meşru 3. taraf siteler için özel bir senaryo. "all"
    # seçilirse bile bu hedef sadece açıkça targets listesine yazılırsa
    # çalışır, yanlışlıkla gerçek bir fraud domain sahibine "üzgünüz
    # sitenizi hackleyen biri var" gibi çelişkili bir mesaj gitmesin diye.
    all_targets = {"nicenic", "host", "netcraft", "safebrowsing", "googlespam", "smartscreen", "spam404", "custom_email"}
    explicit_targets = {"compromise_notice"}
    if "all" in requested_targets:
        targets = all_targets | (requested_targets & explicit_targets)
    else:
        targets = requested_targets & (all_targets | explicit_targets)

    print(f"🎯 {len(domains)} domain, hedefler: {', '.join(sorted(targets))}")

    summary_lines = []

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as session:
        for domain in domains:
            brand_key = detect_brand_key(domain)
            brand_name = BRANDS[brand_key]["name"]
            print(f"\n=== {domain} ({brand_name}) ===")

            found_urls = await discover_phishing_urls(session, domain)
            print(f"  📎 {len(found_urls)} canlı kanıt URL bulundu")
            print(f"  📧 Reporter e-postası: {reporter_email_for(brand_key)}")

            domain_results = []

            if "nicenic" in targets:
                ok = send_email  # placeholder to keep flake happy
                ok = send_nicenic(domain, brand_key, found_urls)
                domain_results.append(("NiceNIC", ok))
                print(f"  {'✅' if ok else '❌'} NiceNIC")

            if "host" in targets:
                cluster_pair, host_key = resolve_host(domain)
                if host_key == DEAD_DOMAIN:
                    domain_results.append(("Host (NXDOMAIN)", None))
                    print("  💀 Domain artık kayıtlı değil (NXDOMAIN)")
                elif host_key is None:
                    domain_results.append(("Host (cluster tespit edilemedi)", None))
                    print("  ❓ Host tespit edilemedi — manuel inceleme gerekiyor")
                else:
                    ok = send_host_complaint(domain, brand_key, found_urls, host_key, cluster_pair)
                    domain_results.append((f"Host ({HOSTS[host_key]['name']})", ok))
                    print(f"  {'✅' if ok else '❌'} Host ({HOSTS[host_key]['name']})")

            if "custom_email" in targets:
                if INPUT_CUSTOM_EMAIL:
                    ok = send_custom_email(domain, brand_key, found_urls)
                    domain_results.append((f"Özel mail ({INPUT_CUSTOM_EMAIL})", ok))
                    print(f"  {'✅' if ok else '❌'} Özel mail")
                else:
                    print("  ⚠️ custom_email hedefi seçildi ama e-posta adresi verilmedi, atlandı")

            if "compromise_notice" in targets:
                if INPUT_CUSTOM_EMAIL:
                    ok = send_compromise_notice(domain, brand_key)
                    domain_results.append((f"Hacklenmiş Site Bildirimi ({INPUT_CUSTOM_EMAIL})", ok))
                    print(f"  {'✅' if ok else '❌'} Hacklenmiş site bildirimi")
                else:
                    print("  ⚠️ compromise_notice hedefi seçildi ama e-posta adresi verilmedi, atlandı")

            if "netcraft" in targets:
                ok = await report_netcraft(session, domain, brand_key, found_urls)
                domain_results.append(("Netcraft", ok))
                print(f"  {'✅' if ok else '❌'} Netcraft")

            if "safebrowsing" in targets:
                ok = await report_safe_browsing(session, domain, found_urls)
                domain_results.append(("Safe Browsing", ok))
                print(f"  {'✅' if ok else '❌'} Safe Browsing")

            if "googlespam" in targets:
                ok = await report_google_spam(session, domain, brand_key, found_urls)
                domain_results.append(("Google Spam", ok))
                print(f"  {'✅' if ok else '❌'} Google Spam")

            if "smartscreen" in targets:
                ok = await report_smartscreen(session, domain, brand_key, found_urls)
                domain_results.append(("SmartScreen", ok))
                print(f"  {'✅' if ok else '❌'} SmartScreen")

            if "spam404" in targets:
                ok = await report_spam404(session, domain, found_urls)
                domain_results.append(("Spam404", ok))
                print(f"  {'✅' if ok else '❌'} Spam404")

            append_to_reported_files(domain)

            status_str = "  ".join(
                f"{'✅' if ok is True else '❌' if ok is False else '⚠️'} {name}"
                for name, ok in domain_results
            )
            summary_lines.append(
                f"🎯 `{domain}` ({brand_name}, {len(found_urls)} kanıt URL, reporter: {reporter_email_for(brand_key)})\n   {status_str}"
            )

    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"📋 *[PANEL] Manuel Şikayet Dispatch* — {now}\n\n"
    msg += "\n\n".join(summary_lines)
    if INPUT_NOTES:
        msg += f"\n\n📝 *Not:* {INPUT_NOTES}"
    await send_telegram(msg)
    print("\n✅ Tamamlandı, Telegram'a bildirildi.")

if __name__ == "__main__":
    asyncio.run(main())
