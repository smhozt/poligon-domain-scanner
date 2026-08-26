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
REPORTED_FILES = [
    "reported.json",
    "betsat_reported.json",
    "turkbet_reported.json",
]
# NiceNIC scriptinden AYRI bir complaint-done dosyası — aynı domain hem
# registrar (NiceNIC) hem host seviyesinde şikayet edilebilir, bunlar
# birbirini engellemez.
COMPLAINT_FILE = "host_complaint_reported.json"
UNKNOWN_CLUSTER_FILE = "unknown_clusters.json"
# İsteğe bağlı: Cloudflare raporundan host'u zaten elle öğrendiğimiz ama
# NS lookup'a güvenmek istemediğimiz domainler için manuel override.
# Format: {"domain.com": "host_key"}
MANUAL_HOST_OVERRIDE_FILE = "manual_host_overrides.json"
# ============================================================
# MARKA AYARLARI — GÜNCEL (26 Ağustos 2026 itibarıyla)
# ============================================================
BRANDS = {
    "superbetin": {
        "name": "Superbetin",
        "active_domains": ["superbetin.com", "superbetin2097.com"],
        "signature_email": "yardim@superbetin.com",
    },
    "betsat": {
        "name": "Betsat",
        "active_domains": ["betsat.com", "betsat1618.com"],
        "signature_email": "support@betsat.com",
    },
    "turkbet": {
        "name": "Turkbet",
        "active_domains": ["turkbet.io", "759turkbet.com"],
        "signature_email": "support@turkbet.co",
        "signature_footer": (
            "Turkbet, Curaçao yasalarına göre kurulmuş olan Poligon Entertainment N.V. "
            "tarafından işletilmektedir. 132517 şirket numarasıyla kayıtlı olan bu şirket, "
            "Curaçao Oyun Otoritesi tarafından verilen OGL/2024/815/0653 numaralı lisans "
            "kapsamında şans oyunları sunma yetkisine sahiptir ve bu faaliyetlerini Şans "
            "Oyunları Ulusal Yönetmeliği (LOK) doğrultusunda yürütmektedir."
        ),
    },
}
WHITELIST = set()
for _brand in BRANDS.values():
    WHITELIST.update(_brand["active_domains"])
# ============================================================
# HOSTLAR — abuse adresleri (manual_complaint.py ile senkron, 26 Ağu 2026)
# ============================================================
HOSTS = {
    "netiface":        {"name": "Netiface LLC / VPS Dedicated LLC",     "abuse": ["abuse@abusehandler.net", "abuse@vpsdedicated.net"]},
    "vpsdedicated_flashwisp": {"name": "VPS Dedicated LLC, US (flashwisp.com.ng)", "abuse": ["abuse@flashwisp.com.ng"]},
    "sollutium":       {"name": "Unnamed host (sollutium.com)", "abuse": ["abuse@sollutium.com"]},
    "omegatech":       {"name": "Omegatech LTD",                        "abuse": ["abuse@pitline.net", "abuse@omegatech.sc"]},
    "virtualsystems":  {"name": "Virtual Systems LLC",                  "abuse": ["abuse@wehostservers.com"]},
    "virtualsystems_vsys": {"name": "Virtual Systems LLC (v-sys.org)",  "abuse": ["abuse@v-sys.org"]},
    "blazedge":        {"name": "Blazedge",                             "abuse": ["abuse@blazedge.com"]},
    "advin":           {"name": "Advin Services LLC",                   "abuse": ["anush@advinservers.com"]},
    "swissnet":        {"name": "SwissNet LLC",                          "abuse": ["abuse@swissnetwork.io"]},
    "prq":             {"name": "PRQ VPN Network SE",                    "abuse": ["abuse@dcs.net"]},
    "fatcat_scrhost":  {"name": "FATCAT-AS / scrhost.com",               "abuse": ["info@scrhost.com"]},
    "fatcat_epikhost": {"name": "FATCAT NETWORK S.A.",                   "abuse": ["abuse@epikhost.org"]},
    "vpsdatacenter":   {"name": "VPS Datacenter Ltd (private-data-center.com)", "abuse": ["abuse@private-data-center.com"]},
    "weridata":        {"name": "WERIDATA-LLC / VIRTUO - 12651980 Canada Inc., US", "abuse": ["report@abuseradar.com"]},
    "colocatel":       {"name": "ColocaTel Inc.",                        "abuse": ["abuse@colocatel.com"]},
    "evoxt":           {"name": "Evoxt Sdn. Bhd.",                       "abuse": ["abuse@evoxt.com"]},
    "cloudzy":         {"name": "RouterHosting/Cloudzy",                 "abuse": ["abuse-reports@cloudzy.com"]},
    "koddos":          {"name": "KoDDoS / Amarutu Technology Ltd",       "abuse": ["abuse@koddos.net"]},
    "pfcloud_vmheaven": {"name": "Pfcloud UG (vmheaven.io)",              "abuse": ["abuse@vmheaven.io"]},
    "gannon_nancy_ambiguous": {"name": "PLAY2GO INTERNATIONAL LIMITED / Omegatech LTD / SYNLINQ (belirsiz)", "abuse": ["abuse@play2go.cloud", "abuse@pitline.net", "abuse@omegatech.sc", "abuse@ghostnet.de", "abuse@roeth-und-beck.de"]},
    "play2go":         {"name": "PLAY2GO INTERNATIONAL LIMITED",         "abuse": ["abuse@play2go.cloud"]},
    "namecheap":       {"name": "Namecheap, Inc.",                       "abuse": ["abuse@namecheaphosting.com"]},
    "pfcloud":         {"name": "Pfcloud UG (abusehandler.net)",         "abuse": ["abuse@abusehandler.net"]},
    "pfcloud_io":      {"name": "Pfcloud UG (pfcloud.io)",               "abuse": ["abuse@pfcloud.io"]},
    "sahinnetwork":    {"name": "Bursabil Teknoloji A.Ş.",               "abuse": ["abuse@sahinnetwork.com"]},
    "frantech":        {"name": "FranTech Solutions (PONYNET)",          "abuse": ["admin@frantech.ca"]},
    "synlinq":         {"name": "SYNLINQ (Oliver Horscht)",              "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de"]},
    "adaline_chris_ambiguous": {"name": "SYNLINQ / Omegatech LTD (belirsiz)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@pitline.net", "abuse@omegatech.sc"]},
    "brady_harmony_ambiguous": {"name": "VPS Dedicated LLC, US (belirsiz)", "abuse": ["abuse@abusehandler.net", "abuse@flashwisp.com.ng"]},
    "jeremy_kay_ambiguous": {"name": "Omegatech LTD / VPS Dedicated LLC (belirsiz)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@abusehandler.net"]},
    "mimi_sevki_ambiguous": {"name": "SYNLINQ / VPS Dedicated LLC (belirsiz)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@abusehandler.net"]},
    "corey_lucy_ambiguous": {"name": "SYNLINQ / Omegatech LTD (belirsiz)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@pitline.net", "abuse@omegatech.sc"]},
    "aisha_langston_ambiguous": {"name": "Omegatech LTD / VPS Dedicated LLC, US (belirsiz)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@abusehandler.net"]},
    "mario_norah_ambiguous": {"name": "FranTech Solutions / VPS Dedicated LLC, US (belirsiz)", "abuse": ["admin@frantech.ca", "abuse@vpsdedicated.net"]},
    "ezra_veda_ambiguous": {"name": "SwissNet LLC / Pfcloud UG (belirsiz)", "abuse": ["abuse@swissnetwork.io", "abuse@abusehandler.net"]},
    "luciane_oswald_ambiguous": {"name": "Omegatech LTD / SYNLINQ / VPS Dedicated LLC (belirsiz)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@abusehandler.net"]},
    "elinore_patrick_ambiguous": {"name": "SwissNet LLC / FROSTYHOSTING-AS RU / VPS Dedicated LLC (belirsiz)", "abuse": ["abuse@swissnetwork.io", "frostyhosting@proton.me", "abuse@vpsdedicated.net"]},
    "georgia_kobe_ambiguous": {"name": "Netiface LLC / VPS Dedicated LLC, US (belirsiz)", "abuse": ["abuse@abusehandler.net", "abuse@flashwisp.com.ng"]},
    "ruben_ariella_ambiguous": {"name": "Advin Services LLC / VPS Dedicated LLC, US (belirsiz)", "abuse": ["anush@advinservers.com", "abuse@flashwisp.com.ng"]},
    "digitalocean":    {"name": "DigitalOcean LLC",                     "abuse": ["abuse@digitalocean.com"]},
    "alexhost":        {"name": "AlexHost SRL, MD",                     "abuse": ["noc@alexhost.com"]},
    "ovh":             {"name": "OVH SAS, FR",                          "abuse": ["abuse@ovh.net"]},
    "knownsrv":        {"name": "KnownSRV Ltd.",                        "abuse": ["abuse@pronect.hr"]},
    "privatelayer":    {"name": "Private Layer INC, PA / Digitale Suisse AG, CH", "abuse": ["abuse@privatelayer.com"]},
    "frostyhosting":   {"name": "FrostyHosting (Belenkii Ivan Alexandrovich, RU)", "abuse": ["frostyhosting@proton.me"]},
    "ipvendetta":      {"name": "IP Vendetta Inc.",                      "abuse": ["abuse@ipvendetta.com"]},
    "desi_josh_ambiguous": {"name": "SwissNet LLC / VPS Datacenter Ltd (belirsiz)", "abuse": ["abuse@swissnetwork.io", "abuse@private-data-center.com"]},
    "dayana_kurt_ambiguous": {"name": "Netiface LLC / VPS Dedicated LLC, US (flashwisp.com.ng) (belirsiz)", "abuse": ["abuse@abusehandler.net", "abuse@vpsdedicated.net", "abuse@flashwisp.com.ng"]},
}
# ============================================================
# CLUSTER HARİTASI — NS etiket çifti (frozenset, sırasız) -> host_key
# manual_complaint.py ile senkron (26 Ağu 2026). Bilinmeyen cluster'lar
# OTOMATİK GÖNDERİLMEZ — unknown_clusters.json'a loglanır, Telegram'a
# bildirilir, elle CF raporuyla host tespiti bekler.
# ============================================================
CLUSTER_MAP = {
    frozenset({"drew", "leia"}):        "pfcloud",
    frozenset({"george", "treasure"}):  "pfcloud",
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
    frozenset({"georgia", "kobe"}):     "georgia_kobe_ambiguous",
    frozenset({"alexia", "greg"}):      "vpsdatacenter",
    frozenset({"devin", "nucum"}):      "netiface",
    frozenset({"brady", "harmony"}):    "brady_harmony_ambiguous",
    frozenset({"colin", "nena"}):       "netiface",
    frozenset({"brady", "cora"}):       "pfcloud",
    frozenset({"candy", "edward"}):     "pfcloud",
    frozenset({"syeef", "tina"}):       "omegatech",
    frozenset({"isla", "nolan"}):       "omegatech",
    frozenset({"aisha", "langston"}):   "aisha_langston_ambiguous",
    frozenset({"archer", "melissa"}):   "omegatech",
    frozenset({"dane", "alice"}):       "omegatech",
    frozenset({"aleena", "tony"}):      "omegatech",
    frozenset({"luciane", "oswald"}):   "luciane_oswald_ambiguous",
    frozenset({"mimi", "sevki"}):       "mimi_sevki_ambiguous",
    frozenset({"ainsley", "tate"}):     "omegatech",
    frozenset({"cruz", "hasslo"}):      "omegatech",
    frozenset({"jeremy", "kay"}):       "jeremy_kay_ambiguous",
    frozenset({"aliza", "dean"}):       "netiface",
    frozenset({"chad", "lucy"}):        "netiface",
    frozenset({"cartman", "elma"}):     "virtualsystems",
    frozenset({"maya", "uriah"}):       "virtualsystems",
    frozenset({"alexia", "burt"}):      "sollutium",
    frozenset({"kanye", "magnolia"}):   "omegatech",
    frozenset({"ruben", "ariella"}):    "vpsdedicated_flashwisp",
    frozenset({"raegan", "gabe"}):      "advin",
    frozenset({"penny", "tanner"}):     "swissnet",
    frozenset({"elliot", "marlowe"}):   "swissnet",
    frozenset({"ainsley", "lamar"}):    "swissnet",
    frozenset({"lee", "aida"}):         "swissnet",
    frozenset({"delilah", "jack"}):     "swissnet",
    frozenset({"eloise", "peter"}):     "swissnet",
    frozenset({"corey", "teresa"}):     "swissnet",
    frozenset({"fattouche", "luciane"}): "swissnet",
    frozenset({"luciane", "fattouche"}): "swissnet",
    frozenset({"edna", "shane"}):       "swissnet",
    frozenset({"abdullah", "liv"}):     "swissnet",
    frozenset({"elinore", "patrick"}):  "elinore_patrick_ambiguous",
    frozenset({"stevie", "wilson"}):    "netiface",
    frozenset({"jen", "paul"}):         "pfcloud",
    frozenset({"decker", "liberty"}):   "prq",
    frozenset({"paris", "porter"}):     "prq",
    frozenset({"gail", "lennox"}):      "fatcat_scrhost",
    frozenset({"candy", "nico"}):       "fatcat_scrhost",
    frozenset({"robin", "ram"}):        "fatcat_scrhost",
    frozenset({"alice", "seamus"}):     "fatcat_epikhost",
    frozenset({"ara", "mark"}):         "fatcat_epikhost",
    frozenset({"ophelia", "theo"}):     "vpsdatacenter",
    frozenset({"garrett", "indie"}):    "vpsdatacenter",
    frozenset({"kipp", "penny"}):       "vpsdatacenter",
    frozenset({"eve", "sean"}):         "vpsdatacenter",
    frozenset({"jewel", "vin"}):        "vpsdatacenter",
    frozenset({"james", "maeve"}):      "vpsdatacenter",
    frozenset({"harlee", "tim"}):       "vpsdatacenter",
    frozenset({"clayton", "jade"}):     "vpsdatacenter",
    frozenset({"adi", "langston"}):     "vpsdatacenter",
    frozenset({"andronicus", "emely"}): "vpsdatacenter",
    frozenset({"leanna", "patrick"}):   "vpsdedicated_flashwisp",
    frozenset({"brodie", "laylah"}):    "vpsdedicated_flashwisp",
    frozenset({"achiel", "nicole"}):    "weridata",
    frozenset({"dayana", "harlan"}):    "weridata",
    frozenset({"cash", "macy"}):        "weridata",
    frozenset({"opal", "ricardo"}):     "evoxt",
    frozenset({"sreeni", "zahir"}):     "evoxt",
    # DÜZELTİLDİ 25 Ağu 2026 — panel host tespiti (m-superbetin2096.com)
    # bunu Evoxt olarak teyit etti, eskiden yanlışlıkla netiface'ti
    frozenset({"elmo", "romina"}):      "evoxt",
    frozenset({"aron", "javier"}):      "colocatel",
    frozenset({"bowen", "rosemary"}):   "colocatel",
    frozenset({"kurt", "leah"}):        "colocatel",
    frozenset({"emely", "ishaan"}):     "colocatel",
    frozenset({"melody", "armando"}):   "colocatel",
    frozenset({"gene", "hans"}):        "colocatel",
    frozenset({"elaine", "emerson"}):   "colocatel",
    frozenset({"nitin", "raina"}):      "colocatel",
    frozenset({"paityn", "titan"}):     "cloudzy",
    frozenset({"gannon", "nancy"}):     "gannon_nancy_ambiguous",
    frozenset({"daniella", "felipe"}):  "play2go",
    frozenset({"brenda", "leif"}):      "namecheap",
    frozenset({"huxley", "kami"}):      "pfcloud_io",
    frozenset({"bonnie", "fred"}):      "sahinnetwork",
    frozenset({"katja", "tosana"}):     "frantech",
    frozenset({"khalid", "suzanne"}):   "frantech",
    frozenset({"kate", "ed"}):          "frantech",
    frozenset({"cosmin", "melany"}):    "frantech",
    frozenset({"mario", "norah"}):      "mario_norah_ambiguous",
    frozenset({"burt", "liz"}):          "frantech",
    frozenset({"fred", "ivy"}):          "frantech",
    frozenset({"hal", "lola"}):          "frantech",
    frozenset({"adaline", "joaquin"}):   "netiface",
    frozenset({"pdns1", "pdns2"}):        "blazedge",
    frozenset({"ezra", "veda"}):          "ezra_veda_ambiguous",
    frozenset({"adel", "albert"}):        "netiface",
    frozenset({"elliott", "paloma"}):     "netiface",
    frozenset({"jack", "nora"}):          "netiface",
    frozenset({"emerson", "lady"}):       "netiface",
    frozenset({"corey", "lucy"}):          "corey_lucy_ambiguous",
    frozenset({"aleena", "andronicus"}):   "frantech",
    frozenset({"igor", "ziggy"}):           "netiface",
    frozenset({"ernest", "oaklyn"}):    "netiface",
    frozenset({"bowen", "lauryn"}):     "netiface",
    frozenset({"donovan", "melinda"}):  "netiface",
    frozenset({"braden", "priscilla"}): "netiface",
    frozenset({"aiden", "naya"}):       "synlinq",
    frozenset({"adaline", "chris"}):    "adaline_chris_ambiguous",
    frozenset({"archer", "lana"}):      "digitalocean",
    frozenset({"paityn", "rick"}):      "ovh",
    frozenset({"emerie", "kai"}):       "knownsrv",
    frozenset({"conrad", "veda"}):      "privatelayer",
    frozenset({"nitin", "selah"}):      "privatelayer",
    frozenset({"cortney", "denver"}):   "privatelayer",
    frozenset({"evangeline", "sullivan"}): "privatelayer",
    frozenset({"decker", "dolly"}):     "alexhost",
    frozenset({"burt", "kiki"}):        "alexhost",
    frozenset({"martha", "rex"}):       "netiface",
    frozenset({"kyle", "roxy"}):        "netiface",
    frozenset({"desi", "josh"}):        "desi_josh_ambiguous",
    frozenset({"marge", "sullivan"}):   "frantech",
    frozenset({"byron", "crystal"}):    "frantech",
    frozenset({"aleena", "art"}):       "frantech",
    frozenset({"pedro", "susan"}):      "ipvendetta",
    frozenset({"imani", "kipp"}):       "koddos",
    frozenset({"dayana", "kurt"}):      "dayana_kurt_ambiguous",
    frozenset({"elma", "salvador"}):    "frostyhosting",
    frozenset({"kehlani", "yahir"}):    "frostyhosting",
    frozenset({"crystal", "marty"}):    "frostyhosting",
    frozenset({"elsa", "norm"}):        "pfcloud",
    frozenset({"damiete", "elisa"}):    "pfcloud_vmheaven",
    frozenset({"elinore", "julio"}):    "vpsdatacenter",
    frozenset({"camilo", "hera"}):      "netiface",
    # YENİ 25 Ağu 2026 — Cloudflare trademark host teyidiyle netleşti
    frozenset({"julio", "piper"}):      "virtualsystems_vsys",
    frozenset({"jim", "sneh"}):         "alexhost",
}
# Bilinen ama host'u HALEN tespit edilmemiş cluster'lar (bilgi amaçlı,
# eşleşme yapılmaz — sadece log mesajında "known-unresolved" diye ayırmak için):
KNOWN_UNRESOLVED_CLUSTERS = {
    frozenset({"lovisa", "max"}),
    frozenset({"ainsley", "everton"}),
    frozenset({"drake", "paris"}),
    frozenset({"donald", "eve"}),
    frozenset({"karl", "nova"}),
}
# NXDOMAIN (artık kayıtlı olmayan) domainler için sentinel değer
DEAD_DOMAIN = "__dead__"
# ============================================================
# YAYGIN PHISHING PATH / SUBDOMAIN KEŞFİ (v2 — 22 Tem 2026)
# Host şikayetlerini somut kanıt (gerçek çalışan URL listesi) ile
# göndermek için, tespit edilen domain'in bilinen fraud path'lerinde
# ve subdomain'lerinde canlı yanıt olup olmadığı kontrol edilir.
# Sadece gerçekten yanıt veren (200/301/302/403) URL'ler mail
# içeriğine eklenir — var olmayan path'ler listelenmez.
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
# Yaygın deposit/gateway subdomain'leri — kök sayfası + kendi deposit
# path'leri kontrol edilir (yatirim.domain.cam/havale/ gibi)
COMMON_PHISHING_SUBDOMAINS = ["m", "tr", "www", "yatirim", "payment", "odeme", "cryptopay", "pay", "crypto"]
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
async def discover_phishing_urls(session, root_domain, max_results=12):
    """Kök domain + bilinen subdomain/path kombinasyonlarını canlı test
    eder, gerçekten yanıt veren URL'leri döndürür. Bu liste host abuse
    mailine 'Reported URLs' bölümü olarak eklenir."""
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
    # "/" ile biten kök path'leri çıkarıp, daha spesifik olanları önce
    # göster (spesifik fraud path'leri daha güçlü kanıt niteliğinde)
    found.sort(key=lambda u: (u.rstrip("/").endswith(root_domain.rstrip("/")), len(u)))
    return found[:max_results]
def load_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else list(data)
    except Exception:
        return []
def load_json_dict(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except Exception:
        return {}
def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(list(data), f)
def save_json_dict(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
def get_root(domain):
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
    return "superbetin"
def is_whitelisted(domain):
    root = get_root(domain)
    return domain in WHITELIST or root in WHITELIST
# ============================================================
# NS CLUSTER TESPİTİ
# ============================================================
def get_ns_labels(domain):
    """Domainin NS kayıtlarındaki ilk etiketleri döndürür (drew.ns.cloudflare.com -> 'drew')"""
    try:
        answers = dns.resolver.resolve(domain, "NS", lifetime=8)
        labels = set()
        for r in answers:
            host = str(r.target).rstrip(".").lower()
            label = host.split(".")[0]
            labels.add(label)
        return labels
    except dns.resolver.NXDOMAIN:
        # Domain artık hiç kayıtlı değil — ölü, tekrar tekrar denemeye gerek yok
        return "NXDOMAIN"
    except Exception as e:
        print(f"    ⚠️ NS lookup başarısız ({domain}): {e}")
        return None
def match_cluster(ns_labels):
    """NS etiketlerini bilinen cluster çiftleriyle eşleştirir."""
    if not ns_labels:
        return None, None
    for pair, host_key in CLUSTER_MAP.items():
        if pair.issubset(ns_labels):
            return pair, host_key
    for pair in KNOWN_UNRESOLVED_CLUSTERS:
        if pair.issubset(ns_labels):
            return pair, None  # bilinen ama host'u belirsiz cluster
    return None, None
def resolve_host_for_domain(domain, manual_overrides):
    """Manuel override varsa onu kullan, yoksa NS lookup ile cluster tespiti yap."""
    if domain in manual_overrides:
        host_key = manual_overrides[domain]
        return None, host_key  # cluster_pair None -> build_host_email "manually confirmed" yazar
    root = get_root(domain)
    ns_labels = get_ns_labels(root)
    if ns_labels == "NXDOMAIN":
        return None, DEAD_DOMAIN
    return match_cluster(ns_labels)
# ============================================================
# MAİL İÇERİĞİ
# ============================================================
def build_host_email(domain, host_key, brand_key, cluster_pair, found_urls=None):
    host = HOSTS[host_key]
    brand = BRANDS[brand_key]
    active_domains_str = " / ".join(brand["active_domains"])
    cluster_label = "/".join(sorted(cluster_pair)) if cluster_pair else "manually confirmed hosting"
    subject = f"URGENT: Active Phishing & Trademark Infringement — {domain} — {host['name']} Hosted ({cluster_label})"
    signature_block = f"CS Operations & Technology\nPoligon Entertainment N.V.\n{brand['signature_email']}"
    if "signature_footer" in brand:
        signature_block += f"\n\n{brand['signature_footer']}"
    if found_urls:
        urls_block = "\n".join(f"- {u}" for u in found_urls)
        reported_urls_section = f"\nReported URLs (live-verified at time of report):\n{urls_block}\n"
    else:
        reported_urls_section = ""
    body = f"""Dear {host['name']} Abuse Team,
We are writing on behalf of Poligon Entertainment N.V., the licensed
operator of {brand['name']} (official: {active_domains_str}), under
Curaçao Gaming Authority license OGL/2024/815/0653.
The domain {domain}, hosted on your infrastructure via the {cluster_label}
nameserver cluster, is operating an active phishing site impersonating
our licensed brand, using cloned graphics, trademarked layouts, and fake
login/payment forms to deceive consumers.
{reported_urls_section}
This domain is part of a known recurring fraud pattern on your
infrastructure. We formally request immediate suspension of this domain.
Sincerely,
{signature_block}
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
    manual_overrides = load_json_dict(MANUAL_HOST_OVERRIDE_FILE)
    unknown_clusters = load_json_dict(UNKNOWN_CLUSTER_FILE)
    candidates = []
    for d in all_reported:
        root = get_root(d)
        if is_whitelisted(d):
            continue
        if d not in complaint_done and root not in complaint_done:
            candidates.append(d)
    if not candidates:
        print("Host şikayeti gönderilecek yeni domain yok.")
        return
    print(f"{len(candidates)} domain için host tespiti yapılacak...")
    success_list = []
    failed_list = []
    unresolved_list = []
    unknown_list = []
    dead_list = []
    sent_roots = set()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as http_session:
        for domain in candidates[:20]:
            root = get_root(domain)
            if root in sent_roots:
                complaint_done.add(domain)
                continue
            print(f"NS kontrol ediliyor: {root}")
            cluster_pair, host_key = resolve_host_for_domain(root, manual_overrides)
            if host_key == DEAD_DOMAIN:
                print(f"  💀 NXDOMAIN — domain artık kayıtlı değil, bir daha kontrol edilmeyecek")
                complaint_done.add(domain)
                complaint_done.add(root)
                unknown_clusters.pop(root, None)
                dead_list.append(root)
                await asyncio.sleep(1)
                continue
            if host_key is None:
                if cluster_pair:
                    cluster_label = "/".join(sorted(cluster_pair))
                    print(f"  ❓ Bilinen ama host'u belirsiz cluster: {cluster_label}")
                    unknown_clusters[root] = {
                        "cluster": cluster_label,
                        "status": "known-unresolved",
                        "detected_at": datetime.now(TZ_SOFIA).isoformat(),
                    }
                else:
                    print(f"  ❓ Tanınmayan cluster / NS lookup başarısız")
                    unknown_clusters[root] = {
                        "cluster": None,
                        "status": "unrecognized",
                        "detected_at": datetime.now(TZ_SOFIA).isoformat(),
                    }
                unresolved_list.append(root)
                unknown_list.append(root)
                await asyncio.sleep(2)
                continue
            brand_key = detect_brand_key(domain)
            print(f"  🔎 Bilinen fraud path/subdomain kombinasyonları test ediliyor...")
            found_urls = await discover_phishing_urls(http_session, root)
            if found_urls:
                print(f"    📎 {len(found_urls)} canlı URL bulundu, mail'e eklenecek")
            else:
                print(f"    (canlı path/subdomain bulunamadı — genel şablonla gönderiliyor)")
            subject, body = build_host_email(root, host_key, brand_key, cluster_pair, found_urls)
            host = HOSTS[host_key]
            print(f"  ✉️  {host['name']} adresine gönderiliyor: {root}")
            success = send_email(
                host["abuse"],
                subject,
                body,
                from_name=f"{BRANDS[brand_key]['name']} Security Team"
            )
            if success:
                success_list.append((root, host["name"], len(found_urls)))
                complaint_done.add(domain)
                complaint_done.add(root)
                sent_roots.add(root)
                unknown_clusters.pop(root, None)  # artık çözüldü, listeden çıkar
                print(f"    ✅ Gönderildi")
            else:
                failed_list.append(root)
                print(f"    ❌ Başarısız")
            await asyncio.sleep(5)
    save_json(COMPLAINT_FILE, list(complaint_done))
    save_json_dict(UNKNOWN_CLUSTER_FILE, unknown_clusters)
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"📧 *[OTO-ŞİKAYET] Host Bazlı Mail Raporu* — {now}\n\n"
    if success_list:
        msg += f"✅ *Gönderilen:* {len(success_list)} şikayet\n"
        for d, hostname, url_count in success_list[:10]:
            evidence_note = f" ({url_count} URL kanıtı)" if url_count else ""
            msg += f"  🔹 `{d}` → {hostname}{evidence_note}\n"
        if len(success_list) > 10:
            msg += f"  ... ve {len(success_list)-10} tane daha\n"
        msg += "\n"
    if failed_list:
        msg += f"❌ *Mail gönderim hatası:* {len(failed_list)} domain\n\n"
    if unknown_list:
        msg += f"❓ *Cluster tespit edilemedi (elle CF raporu gerekiyor):* {len(unknown_list)} domain\n"
        for d in unknown_list[:10]:
            msg += f"  ⚠️ `{d}`\n"
        if len(unknown_list) > 10:
            msg += f"  ... ve {len(unknown_list)-10} tane daha\n"
        msg += "\n"
    if dead_list:
        msg += f"💀 *Artık kayıtlı değil (NXDOMAIN, atlandı):* {len(dead_list)} domain\n"
    msg += f"\n📬 *Gönderen:* `{SMTP_USER}`"
    await send_telegram(msg)
    print(f"\n✅ Tamamlandı! {len(success_list)} mail gönderildi, {len(unknown_list)} domain elle incelemeye düştü, {len(dead_list)} ölü domain atlandı.")
if __name__ == "__main__":
    asyncio.run(main())
