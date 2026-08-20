import asyncio
import aiohttp
import os
import json
import socket
import time
import hashlib
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
SPAMHAUS_API_TOKEN = os.environ.get("SPAMHAUS_API_TOKEN", "")
INPUT_DOMAINS        = os.environ.get("INPUT_DOMAINS", "")
INPUT_BRAND          = os.environ.get("INPUT_BRAND", "auto").strip().lower()
INPUT_TARGETS        = os.environ.get("INPUT_TARGETS", "all").strip().lower()
INPUT_CUSTOM_EMAIL   = os.environ.get("INPUT_CUSTOM_EMAIL", "").strip()
INPUT_ACTIVE_OVERRIDE = os.environ.get("INPUT_ACTIVE_OVERRIDE", "").strip()
INPUT_NOTES          = os.environ.get("INPUT_NOTES", "").strip()
INPUT_REPORTER_EMAIL = os.environ.get("INPUT_REPORTER_EMAIL", "").strip()
INPUT_REQUEST_ID = os.environ.get("INPUT_REQUEST_ID", "").strip()
REPORTED_FILES_TO_UPDATE = ["reported.json", "betsat_reported.json", "turkbet_reported.json"]
# ============================================================
# MARKA AYARLARI
# ============================================================
BRANDS = {
    "superbetin": {
        "name": "Superbetin",
        "fixed_domain": "superbetin.com",
        # GÜNCELLENDİ 20 Ağu 2026 — superbetin2093.com artık pasif, aktif adres superbetin2094.com
        "active_domains": ["superbetin.com", "superbetin2094.com"],
        "signature_email": "yardim@superbetin.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa1V2TXpJM2MyWjFSV0pRYW1OQ1IxcFVkbEJMZGxFOVBTSXNJblpoYkhWbElqb2lMMVpTUXpSbU5XdG9lbkJHVlZSak1EVlJWMmxLZHowOUlpd2liV0ZqSWpvaVpXTXdaak5rWW1NeVlURXlNR1F6WkRFNVlqVmxabVJoTkdWak5qZzBNRGt3WVRVMFpHUmtNakppTXpnMVlUUmpaVFJrTW1JelpEazJZalJrTWpJd1l5SXNJblJoWnlJNklpSjk="
    },
    "betsat": {
        "name": "Betsat",
        "fixed_domain": "betsat.com",
        # GÜNCELLENDİ 19 Ağu 2026 — aktif adres betsat1615.com
        "active_domains": ["betsat.com", "betsat1615.com"],
        "signature_email": "support@betsat.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJamRoY1ZkVFdIWnJjbG95T1hkbWFVd3paRUZETWxFOVBTSXNJblpoYkhWbElqb2lSbmxvTVVzelJGRkhWMmh4ZVVFNGJIUkJLM2xoZHowOUlpd2liV0ZqSWpvaU1URmxZamhqTUdVMk1UZzBObUpoTmpkaU5tTXdNR0pqTmpkaFl6Z3pabVk0WVdFMVpUYzJabVF6T0dJeE5qVmtNV1E0WlRVM1pUWTJPV1JrWVdRM01pSXNJblJoWnlJNklpSjk="
    },
    "turkbet": {
        "name": "Turkbet",
        "fixed_domain": "turkbet.io",
        "active_domains": ["turkbet.io", "757turkbet.com"],
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
if INPUT_ACTIVE_OVERRIDE:
    override_domains = [d.strip() for d in INPUT_ACTIVE_OVERRIDE.split(",") if d.strip()]
    for brand_key in BRANDS:
        for od in override_domains:
            if brand_key in od.lower() and od not in BRANDS[brand_key]["active_domains"]:
                BRANDS[brand_key]["active_domains"].append(od)
# ============================================================
# HOSTLAR
# ============================================================
HOSTS = {
    "netiface":        {"name": "Netiface LLC / VPS Dedicated LLC",     "abuse": ["abuse@abusehandler.net", "abuse@vpsdedicated.net"]},
    "vpsdedicated_flashwisp": {"name": "VPS Dedicated LLC, US (flashwisp.com.ng)", "abuse": ["abuse@flashwisp.com.ng"]},
    "sollutium":       {"name": "Unnamed host (sollutium.com)", "abuse": ["abuse@sollutium.com"]},
    "omegatech":       {"name": "Omegatech LTD",                        "abuse": ["abuse@pitline.net", "abuse@omegatech.sc"]},
    "virtualsystems":  {"name": "Virtual Systems LLC",                  "abuse": ["abuse@wehostservers.com"]},
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
    "koddos":          {"name": "KoDDoS / Amarutu Technology Ltd",       "abuse": ["abuse@koddos.com", "abuse@koddos.net"]},
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
}
WEB_FORM_ONLY_REGISTRARS = {
    "fewmoretaps": {"display": "Trustname / Fewmoretaps OU", "form_url": "https://trustname.com/help/report-abuse"},
    "dynadot":     {"display": "Dynadot Inc.",                "form_url": "https://dynadot.com/report-abuse"},
    "hosting concepts": {"display": "Openprovider / Hosting Concepts B.V.", "form_url": "https://abuse.registrar.eu"},
    "namesilo":    {"display": "NameSilo, LLC",               "form_url": "https://www.namesilo.com/phishing-report"},
    "squarespace": {"display": "Squarespace Domains",         "form_url": "https://support.squarespace.com/hc/en-us/requests/new?ticket_form_id=23532118441357"},
    "dominet":     {"display": "Dominet (HK) / Alibaba Cloud", "form_url": "https://report.alibabacloud.com/#/reportCenter/home"},
    "gname":       {"display": "Gname.com Pte. Ltd.",         "form_url": "https://www.gname.com/abuse/category/2"},
}
def web_form_only_match(registrar_name):
    if not registrar_name:
        return None
    low = registrar_name.lower()
    for key, info in WEB_FORM_ONLY_REGISTRARS.items():
        if key in low:
            return info
    return None
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
    frozenset({"ruben", "ariella"}):    "ruben_ariella_ambiguous",
    frozenset({"raegan", "gabe"}):      "advin",
    frozenset({"penny", "tanner"}):     "swissnet",
    frozenset({"elliot", "marlowe"}):   "swissnet",
    frozenset({"ainsley", "lamar"}):    "swissnet",
    frozenset({"lee", "aida"}):         "swissnet",
    frozenset({"delilah", "jack"}):     "swissnet",
    frozenset({"eloise", "peter"}):     "swissnet",
    frozenset({"corey", "teresa"}):     "swissnet",
    frozenset({"elinore", "patrick"}):  "elinore_patrick_ambiguous",
    frozenset({"stevie", "wilson"}):    "netiface",
    frozenset({"jen", "paul"}):         "pfcloud",
    frozenset({"fattouche", "luciane"}): "swissnet",
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
    frozenset({"leanna", "patrick"}):   "vpsdedicated_flashwisp",
    frozenset({"achiel", "nicole"}):    "weridata",
    frozenset({"andronicus", "emely"}): "vpsdatacenter",
    frozenset({"opal", "ricardo"}):     "evoxt",
    frozenset({"sreeni", "zahir"}):     "evoxt",
    frozenset({"aron", "javier"}):      "colocatel",
    frozenset({"bowen", "rosemary"}):   "colocatel",
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
    frozenset({"luciane", "fattouche"}):    "swissnet",
    frozenset({"igor", "ziggy"}):           "netiface",
    frozenset({"ernest", "oaklyn"}):    "netiface",
    frozenset({"bowen", "lauryn"}):     "netiface",
    frozenset({"adi", "langston"}):     "vpsdatacenter",
    frozenset({"kurt", "leah"}):        "colocatel",
    frozenset({"emely", "ishaan"}):     "colocatel",
    frozenset({"melody", "armando"}):   "colocatel",
    frozenset({"gene", "hans"}):        "colocatel",
    frozenset({"elaine", "emerson"}):   "colocatel",
    frozenset({"donovan", "melinda"}):  "netiface",
    frozenset({"braden", "priscilla"}): "netiface",
    frozenset({"aiden", "naya"}):       "synlinq",
    frozenset({"adaline", "chris"}):    "adaline_chris_ambiguous",
    frozenset({"archer", "lana"}):      "digitalocean",
    frozenset({"paityn", "rick"}):      "ovh",
    frozenset({"emerie", "kai"}):       "knownsrv",
    frozenset({"conrad", "veda"}):      "privatelayer",
    frozenset({"nitin", "selah"}):      "privatelayer",
    frozenset({"decker", "dolly"}):     "alexhost",
    frozenset({"burt", "kiki"}):        "alexhost",
    frozenset({"edna", "shane"}):       "swissnet",
    frozenset({"martha", "rex"}):       "netiface",
    frozenset({"kyle", "roxy"}):        "netiface",
    frozenset({"desi", "josh"}):        "desi_josh_ambiguous",
    frozenset({"brodie", "laylah"}):    "vpsdedicated_flashwisp",
    frozenset({"abdullah", "liv"}):     "swissnet",
    frozenset({"marge", "sullivan"}):   "frantech",
    frozenset({"byron", "crystal"}):    "frantech",
    frozenset({"aleena", "art"}):       "frantech",
    frozenset({"dayana", "harlan"}):    "weridata",
    frozenset({"cash", "macy"}):        "weridata",
    frozenset({"cortney", "denver"}):   "privatelayer",
    frozenset({"pedro", "susan"}):      "ipvendetta",
    frozenset({"elmo", "romina"}):      "netiface",
    frozenset({"clayton", "jade"}):     "vpsdatacenter",
    frozenset({"nitin", "raina"}):      "colocatel",
    # YENİ 20 Ağu 2026 — betsat-uefa.icu teyidi
    frozenset({"imani", "kipp"}):       "koddos",
    # TODO: dayana/kurt (superbetinonlinetr.icu) — VPS Dedicated LLC teyit edildi ama
    # "netiface" (abuse@abusehandler.net + abuse@vpsdedicated.net) mi yoksa
    # "vpsdedicated_flashwisp" (abuse@flashwisp.com.ng) mi olduğu netleşmedi.
    # Semih onaylayınca eklenecek.
}
DEAD_DOMAIN = "__dead__"
def get_ns_labels(domain, retries=2):
    last_err = None
    for attempt in range(retries):
        try:
            answers = dns.resolver.resolve(domain, "NS", lifetime=8)
            return {str(r.target).rstrip(".").lower().split(".")[0] for r in answers}
        except dns.resolver.NXDOMAIN:
            return "NXDOMAIN"
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5)
    print(f"    ⚠️ NS lookup başarısız ({domain}), {retries} deneme sonrası: {type(last_err).__name__}: {last_err}")
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
        return None, DEAD_DOMAIN, None
    cluster_pair, host_key = match_cluster(ns_labels)
    return cluster_pair, host_key, ns_labels
def _whois_raw_query(server, query, timeout=6):
    with socket.create_connection((server, 43), timeout=timeout) as s:
        s.sendall((query + "\r\n").encode())
        chunks = []
        while True:
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks).decode(errors="ignore")
def _whois_fallback_registrar(domain):
    tld = domain.rsplit(".", 1)[-1]
    try:
        iana_resp = _whois_raw_query("whois.iana.org", tld, timeout=6)
    except Exception as e:
        print(f"    ⚠️ WHOIS: IANA sorgusu başarısız ({domain}, tld={tld}): {type(e).__name__}: {e}")
        return None
    server = None
    for line in iana_resp.splitlines():
        if line.lower().startswith("whois:"):
            server = line.split(":", 1)[1].strip()
            break
    if not server:
        print(f"    ⚠️ WHOIS: IANA yanıtında '{tld}' için whois sunucusu bulunamadı ({domain})")
        return None
    resp = None
    last_err = None
    for attempt in range(2):
        try:
            resp = _whois_raw_query(server, domain, timeout=6)
            break
        except Exception as e:
            last_err = e
            if attempt == 0:
                time.sleep(3)
    if resp is None:
        print(f"    ⚠️ WHOIS: {server} sorgusu başarısız ({domain}), 2 deneme sonrası: {type(last_err).__name__}: {last_err}")
        return None
    for line in resp.splitlines():
        low = line.lower()
        if low.startswith("registrar:") or "registrar organization" in low or "sponsoring registrar:" in low:
            return line.split(":", 1)[1].strip()
    print(f"    ⚠️ WHOIS: {server} yanıtında 'Registrar:' alanı bulunamadı ({domain}) — yanıt: {resp[:150]!r}")
    return None
def _find_registrar_entity(entities):
    for entity in entities or []:
        if "registrar" in entity.get("roles", []):
            return entity
        nested = _find_registrar_entity(entity.get("entities"))
        if nested:
            return nested
    return None
def _rdap_endpoints_for(domain):
    tld = domain.rsplit(".", 1)[-1].lower()
    urls = [f"https://rdap.org/domain/{domain}"]
    if tld in ("com", "net"):
        urls.insert(0, f"https://rdap.verisign.com/{tld}/v1/domain/{domain}")
    urls.append(f"https://rdap.nic.vip/domain/{domain}")
    return urls
async def _rdap_registrar(session, domain):
    for url in _rdap_endpoints_for(domain):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
        except Exception as e:
            print(f"    ⚠️ RDAP {url} başarısız ({domain}): {type(e).__name__}: {e}")
            continue
        raw = json.dumps(data).lower()
        is_nicenic = "nicenic" in raw
        name, email = None, None
        entity = _find_registrar_entity(data.get("entities"))
        if entity:
            vcard = entity.get("vcardArray")
            if vcard and len(vcard) > 1:
                for item in vcard[1]:
                    if item[0] == "fn":
                        name = item[3]
                    if item[0] == "email":
                        email = item[3]
            if not name:
                name = entity.get("handle")
        if not name and is_nicenic:
            name = "NICENIC INTERNATIONAL GROUP CO., LIMITED"
        if not name:
            print(f"    ⚠️ RDAP {url} 200 döndü ama registrar adı çıkarılamadı ({domain})")
            continue
        return {"name": name, "email": email, "is_nicenic": is_nicenic}
    return None
async def detect_registrar(session, domain):
    rdap = await _rdap_registrar(session, domain)
    if rdap and rdap.get("name"):
        return {"name": rdap["name"], "email": rdap.get("email"), "source": "rdap", "is_nicenic": rdap["is_nicenic"]}
    whois_name = await asyncio.get_running_loop().run_in_executor(None, _whois_fallback_registrar, domain)
    if whois_name:
        is_nicenic = "nicenic" in whois_name.lower()
        return {"name": whois_name, "email": None, "source": "whois", "is_nicenic": is_nicenic}
    return {"name": None, "email": None, "source": None, "is_nicenic": False}
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
def load_reported():
    reported = set()
    for fname in REPORTED_FILES_TO_UPDATE:
        try:
            with open(fname, "r") as f:
                reported |= set(json.load(f))
        except Exception:
            pass
    return reported
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
    return INPUT_REPORTER_EMAIL or BRANDS[brand_key]["signature_email"]
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
def send_apwg(domain, brand_key, found_urls):
    brand = BRANDS[brand_key]
    subject = f"Phishing URL Report - {domain}"
    target_url = found_urls[0] if found_urls else f"https://{domain}/"
    body = f"""Reported URL: {target_url}
This domain impersonates our licensed brand {brand['name']} (official: {' / '.join(brand['active_domains'])}), operated by Poligon Entertainment N.V. under Curaçao Gaming Authority license OGL/2024/815/0653, using cloned branding and/or credential-harvesting forms to deceive consumers.
{evidence_block(found_urls)}{notes_block()}
Sincerely,
{brand['name']} Security Team
{brand['signature_email']}
"""
    return send_email(
        ['reportphishing@apwg.org'], subject, body,
        f"{brand['name']} Security Team", reply_to=reporter_email_for(brand_key)
    )
def send_compromise_notice(domain, brand_key):
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
            if resp.status in (200, 201, 204):
                return True
            body_snippet = (await resp.text())[:200]
            print(f"    ⚠️ Netcraft HTTP {resp.status} ({domain}) — yanıt: {body_snippet}")
            return False
    except Exception as e:
        print(f"    ⚠️ Netcraft hatası ({domain}): {type(e).__name__}: {e}")
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
# YENİ 19 Ağu 2026 — Spamhaus Threat Intel Community entegrasyonu.
# GitHub Secrets'a SPAMHAUS_API_TOKEN eklenmesi gerekiyor
# (https://auth.spamhaus.org/account -> API Key Creation).
# Domain seviyesinde "Bulletproof Hosting" threat_type seçeneği yok
# (o kategori sadece IP submission'larda var), o yüzden "phish"
# kullanıyoruz — asıl detay reason alanında zaten belirtiliyor.
# ============================================================
async def report_spamhaus(session, domain, brand_key, found_urls):
    if not SPAMHAUS_API_TOKEN:
        print("    ⚠️ Spamhaus: SPAMHAUS_API_TOKEN eksik, atlandı")
        return False
    brand = BRANDS[brand_key]
    reason = (
        f"Phishing site impersonating {brand['name'].upper()} ({brand['fixed_domain']}), "
        f"operated by Poligon Entertainment N.V. under Curaçao license OGL/2024/815/0653. "
        f"Credential harvesting and/or fraudulent payment interception observed."
    )
    if found_urls:
        reason += " Evidence URLs: " + ", ".join(found_urls[:5])
    if INPUT_NOTES:
        reason += f" Notes: {INPUT_NOTES}"
    reason = reason[:255]
    payload = {
        "threat_type": "phish",
        "reason": reason,
        "source": {"object": domain},
    }
    try:
        async with session.post(
            "https://submit.spamhaus.org/portal/api/v1/submissions/add/domain",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SPAMHAUS_API_TOKEN}",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            # 208 = bu domain zaten daha önce Spamhaus'a bildirilmiş — hata değil, başarı sayılır
            if resp.status in (200, 201, 202, 204, 208):
                return True
            body_snippet = (await resp.text())[:200]
            print(f"    ⚠️ Spamhaus HTTP {resp.status} ({domain}) — yanıt: {body_snippet}")
            return False
    except Exception as e:
        print(f"    ⚠️ Spamhaus hatası ({domain}): {type(e).__name__}: {e}")
        return False
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
async def main():
    if not INPUT_DOMAINS:
        print("INPUT_DOMAINS boş — işlenecek domain yok.")
        return
    domains = [d.strip() for d in INPUT_DOMAINS.replace("\n", ",").split(",") if d.strip()]
    domains = [get_root(d) for d in domains]
    seen_domains = set()
    unique_domains = []
    for d in domains:
        if d not in seen_domains:
            seen_domains.add(d)
            unique_domains.append(d)
    domains = unique_domains
    already_reported = load_reported()
    duplicate_domains = [d for d in domains if d in already_reported]
    if duplicate_domains:
        print(f"⚠️  UYARI: Şu domain(ler) daha önce de raporlanmış görünüyor (reported.json'da mevcut):")
        for d in duplicate_domains:
            print(f"     - {d}")
        print("   Kasıtlı bir tekrar gönderim değilse, lütfen kontrol edin.")
        print("   Script yine de devam ediyor (bu bir engelleme değil, sadece bilgilendirme).")
    requested_targets = set(INPUT_TARGETS.split(","))
    all_targets = {"nicenic", "host", "netcraft", "safebrowsing", "googlespam", "smartscreen", "spam404", "custom_email", "spamhaus", "apwg"}
    explicit_targets = {"compromise_notice"}
    if "all" in requested_targets:
        targets = all_targets | (requested_targets & explicit_targets)
    else:
        targets = requested_targets & (all_targets | explicit_targets)
    print(f"🎯 {len(domains)} domain, hedefler: {', '.join(sorted(targets))}")
    summary_lines = []
    results_json = {
        "request_id": INPUT_REQUEST_ID,
        "generated_at": datetime.now(TZ_SOFIA).isoformat(),
        "notes": INPUT_NOTES,
        "domains": [],
    }
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as session:
        for domain in domains:
            brand_key = detect_brand_key(domain)
            brand_name = BRANDS[brand_key]["name"]
            print(f"\n=== {domain} ({brand_name}) ===")
            if domain in already_reported:
                print("  ⚠️  Bu domain daha önce raporlanmış (yukarıdaki uyarıya bak)")
            found_urls = await discover_phishing_urls(session, domain)
            print(f"  📎 {len(found_urls)} canlı kanıt URL bulundu")
            print(f"  📧 Reporter e-postası: {reporter_email_for(brand_key)}")
            domain_results = []
            channels_json = []
            registrar_info = None
            host_info = None
            def _record(channel_key, label, status, detail=None):
                domain_results.append((label, status))
                channels_json.append({
                    "channel": channel_key, "label": label,
                    "status": ("ok" if status is True else "fail" if status is False else "skip"),
                    "detail": detail,
                })
            if "nicenic" in targets:
                print("  🔎 Gerçek registrar tespit ediliyor (RDAP/WHOIS)...")
                registrar_info = await detect_registrar(session, domain)
                if registrar_info["name"] is None:
                    print("  ❓ Registrar tespit edilemedi — NiceNIC'e gönderilmedi, manuel kontrol gerekiyor")
                    _record("nicenic", "NiceNIC", None, "Registrar tespit edilemedi (RDAP+WHOIS başarısız) — manuel kontrol gerekiyor")
                elif not registrar_info["is_nicenic"]:
                    form_info = web_form_only_match(registrar_info["name"])
                    note = f"Gerçek registrar: {registrar_info['name']}"
                    if registrar_info.get("email"):
                        note += f" ({registrar_info['email']})"
                    note += f" [{registrar_info['source']}]"
                    if form_info:
                        note += f" — ⚠️ SADECE WEB FORM kabul ediyor, email gönderilmemeli: {form_info['form_url']}"
                        print(f"  ⚠️ {note}")
                    else:
                        print(f"  ⚠️ {note} — NiceNIC'e gönderilmedi (yanlış hedef önlendi)")
                    _record("nicenic", "NiceNIC", None, note)
                else:
                    ok = send_nicenic(domain, brand_key, found_urls)
                    print(f"  {'✅' if ok else '❌'} NiceNIC (registrar teyitli, {registrar_info['source']})")
                    _record("nicenic", "NiceNIC", ok, f"Registrar teyitli ({registrar_info['source']})")
            if "host" in targets:
                cluster_pair, host_key, observed_ns = resolve_host(domain)
                if host_key == DEAD_DOMAIN:
                    host_info = {"status": "dead"}
                    print("  💀 Domain artık kayıtlı değil (NXDOMAIN)")
                    _record("host", "Host (NXDOMAIN)", None, "Domain artık kayıtlı değil")
                elif host_key is None:
                    observed_str = ", ".join(sorted(observed_ns)) if observed_ns else None
                    host_info = {
                        "status": "unknown_cluster",
                        "cluster": "/".join(sorted(cluster_pair)) if cluster_pair else None,
                        "observed_ns": sorted(observed_ns) if observed_ns else None,
                    }
                    if observed_str:
                        print(f"  ❓ Host tespit edilemedi — gözlemlenen NS: {observed_str} (haritada yok VEYA DNS geçici hata vermiş olabilir)")
                        detail = f"Gözlemlenen NS: {observed_str}"
                    else:
                        print("  ❓ Host tespit edilemedi — DNS sorgusu başarısız oldu (NS hiç okunamadı)")
                        detail = "DNS sorgusu başarısız oldu, NS hiç okunamadı — muhtemelen geçici ağ hatası"
                    _record("host", "Host (cluster tespit edilemedi)", None, detail)
                else:
                    ok = send_host_complaint(domain, brand_key, found_urls, host_key, cluster_pair)
                    host_info = {
                        "status": "known", "host_key": host_key, "host_name": HOSTS[host_key]["name"],
                        "cluster": "/".join(sorted(cluster_pair)) if cluster_pair else None,
                    }
                    print(f"  {'✅' if ok else '❌'} Host ({HOSTS[host_key]['name']})")
                    _record("host", f"Host ({HOSTS[host_key]['name']})", ok)
            if "custom_email" in targets:
                if INPUT_CUSTOM_EMAIL:
                    ok = send_custom_email(domain, brand_key, found_urls)
                    print(f"  {'✅' if ok else '❌'} Özel mail")
                    _record("custom_email", f"Özel mail ({INPUT_CUSTOM_EMAIL})", ok)
                else:
                    print("  ⚠️ custom_email hedefi seçildi ama e-posta adresi verilmedi, atlandı")
            if "compromise_notice" in targets:
                if INPUT_CUSTOM_EMAIL:
                    ok = send_compromise_notice(domain, brand_key)
                    print(f"  {'✅' if ok else '❌'} Hacklenmiş site bildirimi")
                    _record("compromise_notice", f"Hacklenmiş Site Bildirimi ({INPUT_CUSTOM_EMAIL})", ok)
                else:
                    print("  ⚠️ compromise_notice hedefi seçildi ama e-posta adresi verilmedi, atlandı")
            if "netcraft" in targets:
                ok = await report_netcraft(session, domain, brand_key, found_urls)
                print(f"  {'✅' if ok else '❌'} Netcraft")
                _record("netcraft", "Netcraft", ok)
            if "safebrowsing" in targets:
                ok = await report_safe_browsing(session, domain, found_urls)
                print(f"  {'✅' if ok else '❌'} Safe Browsing")
                _record("safebrowsing", "Safe Browsing", ok)
            if "googlespam" in targets:
                ok = await report_google_spam(session, domain, brand_key, found_urls)
                print(f"  {'✅' if ok else '❌'} Google Spam")
                _record("googlespam", "Google Spam", ok)
            if "smartscreen" in targets:
                ok = await report_smartscreen(session, domain, brand_key, found_urls)
                print(f"  {'✅' if ok else '❌'} SmartScreen")
                _record("smartscreen", "SmartScreen", ok)
            if "spam404" in targets:
                ok = await report_spam404(session, domain, found_urls)
                print(f"  {'✅' if ok else '❌'} Spam404")
                _record("spam404", "Spam404", ok)
            if "spamhaus" in targets:
                ok = await report_spamhaus(session, domain, brand_key, found_urls)
                print(f"  {'✅' if ok else '❌'} Spamhaus")
                _record("spamhaus", "Spamhaus", ok)
            if "apwg" in targets:
                ok = send_apwg(domain, brand_key, found_urls)
                print(f"  {'✅' if ok else '❌'} APWG")
                _record("apwg", "APWG", ok)
            append_to_reported_files(domain)
            status_str = "  ".join(
                f"{'✅' if ok is True else '❌' if ok is False else '⚠️'} {name}"
                for name, ok in domain_results
            )
            dup_marker = " 🔁 *(TEKRAR RAPOR — daha önce de gönderilmişti)*" if domain in already_reported else ""
            summary_lines.append(
                f"🎯 `{domain}` ({brand_name}, {len(found_urls)} kanıt URL, reporter: {reporter_email_for(brand_key)}){dup_marker}\n   {status_str}"
            )
            results_json["domains"].append({
                "domain": domain,
                "brand": brand_name,
                "found_urls_count": len(found_urls),
                "reporter_email": reporter_email_for(brand_key),
                "already_reported_before": domain in already_reported,
                "registrar": registrar_info,
                "host": host_info,
                "channels": channels_json,
            })
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"📋 *[PANEL] Manuel Şikayet Dispatch* — {now}\n\n"
    msg += "\n\n".join(summary_lines)
    if INPUT_NOTES:
        msg += f"\n\n📝 *Not:* {INPUT_NOTES}"
    await send_telegram(msg)
    print("\n✅ Tamamlandı, Telegram'a bildirildi.")
    if INPUT_REQUEST_ID:
        os.makedirs("dispatch-results", exist_ok=True)
        result_path = os.path.join("dispatch-results", f"{INPUT_REQUEST_ID}.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(results_json, f, ensure_ascii=False, indent=2)
        print(f"📄 Sonuç dosyası yazıldı: {result_path} (panel bunu polling ile bulacak)")
    else:
        print("⚠️ INPUT_REQUEST_ID verilmedi — sonuç dosyası yazılmadı, panel sadece tetiklemeyi görecek.")
if __name__ == "__main__":
    asyncio.run(main())
