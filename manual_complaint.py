import asyncio
import aiohttp
import os
import json
import socket
import time
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
# Panelin bu çalıştırmayı benzersiz tanıyabilmesi için — sonuç JSON'u
# dispatch-results/{INPUT_REQUEST_ID}.json olarak yazılır, panel bunu
# GitHub Contents API üzerinden polling ile bulur.
INPUT_REQUEST_ID = os.environ.get("INPUT_REQUEST_ID", "").strip()

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
        "active_domains": ["superbetin.com", "superbetin2087.com"],
        "signature_email": "yardim@superbetin.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa1V2TXpJM2MyWjFSV0pRYW1OQ1IxcFVkbEJMZGxFOVBTSXNJblpoYkhWbElqb2lMMVpTUXpSbU5XdG9lbkJHVlZSak1EVlJWMmxLZHowOUlpd2liV0ZqSWpvaVpXTXdaak5rWW1NeVlURXlNR1F6WkRFNVlqVmxabVJoTkdWak5qZzBNRGt3WVRVMFpHUmtNakppTXpnMVlUUmpaVFJrTW1JelpEazJZalJrTWpJd1l5SXNJblJoWnlJNklpSjk="
    },
    "betsat": {
        "name": "Betsat",
        "fixed_domain": "betsat.com",
        "active_domains": ["betsat.com", "betsat1610.com"],
        "signature_email": "support@betsat.com",
        "license_url": "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJamRoY1ZkVFdIWnJjbG95T1hkbWFVd3paRUZETWxFOVBTSXNJblpoYkhWbElqb2lSbmxvTVVzelJGRkhWMmh4ZVVFNGJIUkJLM2xoZHowOUlpd2liV0ZqSWpvaU1URmxZamhqTUdVMk1UZzBObUpoTmpkaU5tTXdNR0pqTmpkaFl6Z3pabVk0WVdFMVpUYzJabVF6T0dJeE5qVmtNV1E0WlRVM1pUWTJPV1JrWVdRM01pSXNJblJoWnlJNklpSjk="
    },
    "turkbet": {
        "name": "Turkbet",
        "fixed_domain": "turkbet.io",
        "active_domains": ["turkbet.io", "754turkbet.com"],
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
    "vpsdedicated_flashwisp": {"name": "VPS Dedicated LLC, US (flashwisp.com.ng)", "abuse": ["abuse@flashwisp.com.ng"]},
    "sollutium":       {"name": "Unnamed host (sollutium.com)", "abuse": ["abuse@sollutium.com"]},
    "omegatech":       {"name": "Omegatech LTD",                        "abuse": ["abuse@pitline.net", "abuse@omegatech.sc"]},
    "virtualsystems":  {"name": "Virtual Systems LLC",                  "abuse": ["abuse@wehostservers.com"]},   # YENİ 03 Ağu 2026 — superbetin2522.com, cluster cartman/elma
    "blazedge":        {"name": "Blazedge",                             "abuse": ["abuse@blazedge.com"]},   # YENİ 03-04 Ağu 2026 — superbetin2087.cam, pdns1/pdns2 nameserver'ları. abuse@blazedge.com'a gönderilen mail "Temporary System Problem" ile bouncelandı (Gmail 47 saat tekrar deneyecek) — kalıcı ret değil, izlenmeli.
    "advin":           {"name": "Advin Services LLC",                   "abuse": ["anush@advinservers.com"]},
    "swissnet":        {"name": "SwissNet LLC",                          "abuse": ["abuse@swissnetwork.io"]},
    "prq":             {"name": "PRQ VPN Network SE",                    "abuse": ["abuse@dcs.net"]},
    "fatcat_scrhost":  {"name": "FATCAT-AS / scrhost.com",               "abuse": ["info@scrhost.com"]},
    "fatcat_epikhost": {"name": "FATCAT NETWORK S.A.",                   "abuse": ["abuse@epikhost.org"]},
    "vpsdatacenter":   {"name": "VPS Datacenter Ltd (private-data-center.com)", "abuse": ["abuse@private-data-center.com"]},
    "weridata":        {"name": "WERIDATA-LLC, US", "abuse": ["report@abuseradar.com"]},
    "colocatel":       {"name": "ColocaTel Inc.",                        "abuse": ["abuse@colocatel.com"]},
    "evoxt":           {"name": "Evoxt Sdn. Bhd.",                       "abuse": ["abuse@evoxt.com"]},
    "cloudzy":         {"name": "RouterHosting/Cloudzy",                 "abuse": ["abuse-reports@cloudzy.com"]},
    "gannon_nancy_ambiguous": {"name": "PLAY2GO INTERNATIONAL LIMITED / Omegatech LTD / SYNLINQ (belirsiz — NS rotasyonu, 07 Ağu 2026'da aynı gün içinde üç farklı teyit geldi: Omegatech (superbetin2293.com) ve SYNLINQ (paykodeme.com); önceden Play2Go kayıtlıydı)", "abuse": ["abuse@play2go.cloud", "abuse@pitline.net", "abuse@omegatech.sc", "abuse@ghostnet.de", "abuse@roeth-und-beck.de"]},
    "play2go":         {"name": "PLAY2GO INTERNATIONAL LIMITED",         "abuse": ["abuse@play2go.cloud"]},
    "namecheap":       {"name": "Namecheap, Inc.",                       "abuse": ["abuse@namecheaphosting.com"]},
    "pfcloud":         {"name": "Pfcloud UG (abusehandler.net)",         "abuse": ["abuse@abusehandler.net"]},
    "pfcloud_io":      {"name": "Pfcloud UG (pfcloud.io)",               "abuse": ["abuse@pfcloud.io"]},
    "sahinnetwork":    {"name": "Bursabil Teknoloji A.Ş.",               "abuse": ["abuse@sahinnetwork.com"]},
    "frantech":        {"name": "FranTech Solutions (PONYNET)",          "abuse": ["admin@frantech.ca"]},
    "synlinq":         {"name": "SYNLINQ (Oliver Horscht)",              "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de"]},
    "adaline_chris_ambiguous": {"name": "SYNLINQ / Omegatech LTD (belirsiz — NS rotasyonu, 03 Ağu 2026 Omegatech teyidi geldi ama önceden SYNLINQ kayıtlıydı)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@pitline.net", "abuse@omegatech.sc"]},
    "brady_harmony_ambiguous": {"name": "VPS Dedicated LLC, US (belirsiz — iki farklı abuse kutusu görüldü: abusehandler.net ve flashwisp.com.ng)", "abuse": ["abuse@abusehandler.net", "abuse@flashwisp.com.ng"]},
    "jeremy_kay_ambiguous": {"name": "Omegatech LTD / VPS Dedicated LLC (belirsiz — NS rotasyonu, 03 Ağu 2026 netiface teyidi geldi ama önceden Omegatech kayıtlıydı)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@abusehandler.net"]},
    "mimi_sevki_ambiguous": {"name": "SYNLINQ / VPS Dedicated LLC (belirsiz — NS rotasyonu, 03 Ağu 2026 netiface teyidi geldi ama önceden SYNLINQ kayıtlıydı)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@abusehandler.net"]},
    "corey_lucy_ambiguous": {"name": "SYNLINQ / Omegatech LTD (belirsiz — paykodeme.com'da SYNLINQ, superbetin2344.com'da Omegatech çıktı)", "abuse": ["abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@pitline.net", "abuse@omegatech.sc"]},
    "aisha_langston_ambiguous": {"name": "Omegatech LTD / VPS Dedicated LLC, US (belirsiz — NS rotasyonu, 10 Ağu 2026'da VPS Dedicated LLC teyidi geldi ama önceden hep Omegatech kayıtlıydı)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@abusehandler.net"]},
    "mario_norah_ambiguous": {"name": "FranTech Solutions / VPS Dedicated LLC, US (belirsiz — NS rotasyonu, 10 Ağu 2026'da VPS Dedicated LLC teyidi geldi ama önceden hep FranTech kayıtlıydı)", "abuse": ["admin@frantech.ca", "abuse@vpsdedicated.net"]},
    "luciane_oswald_ambiguous": {"name": "Omegatech LTD / SYNLINQ / VPS Dedicated LLC (belirsiz — üç farklı teyit görüldü)", "abuse": ["abuse@pitline.net", "abuse@omegatech.sc", "abuse@ghostnet.de", "abuse@roeth-und-beck.de", "abuse@abusehandler.net"]},
    "elinore_patrick_ambiguous": {"name": "SwissNet LLC / FROSTYHOSTING-AS RU (belirsiz — farklı günlerde iki farklı teyit geldi)", "abuse": ["abuse@swissnetwork.io", "frostyhosting@proton.me"]},
    "georgia_kobe_ambiguous": {"name": "Netiface LLC / VPS Dedicated LLC, US (belirsiz — iki farklı abuse kutusu görüldü: abusehandler.net ve flashwisp.com.ng)", "abuse": ["abuse@abusehandler.net", "abuse@flashwisp.com.ng"]},
    "digitalocean":    {"name": "DigitalOcean LLC",                     "abuse": ["abuse@digitalocean.com"]},  # YENİ 31 Tem — superbetin-tr.top üzerinden ilk kez görüldü
    "alexhost":        {"name": "AlexHost SRL, MD",                     "abuse": ["noc@alexhost.com"]},  # YENİ 05 Ağu 2026 — tr.turkbet-guncelgiris.cam üzerinden ilk kez görüldü, cluster decker/dolly
    "ovh":             {"name": "OVH SAS, FR",                          "abuse": ["abuse@ovh.net"]},  # YENİ 31 Tem — tr.superbetin-resmi.icu üzerinden ilk kez görüldü
    "knownsrv":        {"name": "KnownSRV Ltd.",                        "abuse": ["abuse@pronect.hr"]},   # YENİ 07 Ağu 2026 — superbetin-girisadresi.cam üzerinden ilk kez görüldü
    "privatelayer":    {"name": "Private Layer INC, PA",                 "abuse": ["abuse@privatelayer.com"]},   # YENİ 09 Ağu 2026 — superbetinlive.co üzerinden ilk kez görüldü
}

CLUSTER_MAP = {
    # ── Netiface LLC / VPS Dedicated LLC (abusehandler.net ailesi) ──
    frozenset({"drew", "leia"}):        "pfcloud",   # DÜZELTİLDİ 29 Tem — eskiden netiface kayıtlıydı, bugün defalarca tekrarlanan taze Cloudflare teyidi PFCLOUD gösterdi
    frozenset({"george", "treasure"}):  "pfcloud",   # YENİ 29 Tem — superbetin2244.com üzerinden teyit edildi
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
    frozenset({"georgia", "kobe"}):     "georgia_kobe_ambiguous",   # DÜZELTİLDİ 05 Ağu 2026 — 07 Tem'de flashwisp.com.ng teyidi geldi, önceden netiface/abusehandler.net kayıtlıydı — bugün defalarca gördüğümüz "aynı şirket iki abuse kutusu" pattern'i
    frozenset({"alexia", "greg"}):      "vpsdatacenter",   # YENİ 05 Ağu 2026 — superbetingirisin.live: 31 Tem'de james/maeve (VPS Datacenter) teyit edilmişti, aynı domain şimdi bu farklı cluster'ı gösteriyor — muhtemelen NS rotasyonu, aynı host
    frozenset({"devin", "nucum"}):      "netiface",
    frozenset({"brady", "harmony"}):    "brady_harmony_ambiguous",   # DÜZELTİLDİ 03 Ağu 2026 — "VPS Dedicated LLC, US" adı aynı ama Cloudflare bugün abuse@flashwisp.com.ng gösterdi, önceden abuse@abusehandler.net (netiface) kayıtlıydı — aynı şirketin iki farklı abuse kutusu olabilir, ikisine birden gönderiliyor
    frozenset({"colin", "nena"}):       "netiface",   # DÜZELTİLDİ (önceden yanlışlıkla vpsdatacenter'dı)

    # ── Omegatech LTD ──
    frozenset({"syeef", "tina"}):       "omegatech",
    frozenset({"isla", "nolan"}):       "omegatech",
    frozenset({"aisha", "langston"}):   "aisha_langston_ambiguous",   # DÜZELTİLDİ 10 Ağu 2026 — superbetineresmigir724.co üzerinden VPS Dedicated LLC teyidi geldi, önceden hep Omegatech kayıtlıydı
    frozenset({"archer", "melissa"}):   "omegatech",
    frozenset({"dane", "alice"}):       "omegatech",
    frozenset({"aleena", "tony"}):      "omegatech",
    frozenset({"luciane", "oswald"}):   "luciane_oswald_ambiguous",   # 27 Tem: aynı gün hem SYNLINQ hem Omegatech teyidi geldi, ikisine birden gönderiliyor
    frozenset({"mimi", "sevki"}):       "mimi_sevki_ambiguous",   # DÜZELTİLDİ 03 Ağu 2026 — eskiden synlinq kayıtlıydı, bugün superbetiningiris724.co üzerinden taze Cloudflare teyidi VPS Dedicated LLC/netiface gösterdi (bu, bugün 5. kez tekrarlanan aynı pattern — bkz. adaline/chris, donovan/melinda, brady/harmony, jeremy/kay)
    frozenset({"ainsley", "tate"}):     "omegatech",
    frozenset({"cruz", "hasslo"}):      "omegatech",
    frozenset({"jeremy", "kay"}):       "jeremy_kay_ambiguous",   # DÜZELTİLDİ 03 Ağu 2026 — eskiden omegatech kayıtlıydı, bugün superbetininadresin724.co üzerinden taze Cloudflare teyidi VPS Dedicated LLC/netiface gösterdi
    frozenset({"aliza", "dean"}):       "netiface",   # YENİ 03 Ağu 2026 — superbetinguncelgiris724.top üzerinden ilk kez görüldü (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"chad", "lucy"}):        "netiface",   # YENİ 03 Ağu 2026 — superbetinineris724.co üzerinden ilk kez görüldü (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"cartman", "elma"}):     "virtualsystems",   # YENİ 03 Ağu 2026 — superbetin2522.com üzerinden ilk kez görüldü (Virtual Systems LLC, abuse@wehostservers.com)
    frozenset({"maya", "uriah"}):       "virtualsystems",   # YENİ 05 Ağu 2026 — wwwbetsat1604.com (aynı host Virtual Systems LLC, farklı cluster)
    frozenset({"alexia", "burt"}):      "sollutium",

    # ── Advin Services LLC ──
    frozenset({"ruben", "ariella"}):    "advin",
    frozenset({"raegan", "gabe"}):      "advin",

    # ── SwissNet LLC ──
    frozenset({"penny", "tanner"}):     "swissnet",
    frozenset({"elliot", "marlowe"}):   "swissnet",
    frozenset({"ainsley", "lamar"}):    "swissnet",
    frozenset({"lee", "aida"}):         "swissnet",
    frozenset({"delilah", "jack"}):     "swissnet",
    frozenset({"eloise", "peter"}):     "swissnet",
    frozenset({"corey", "teresa"}):     "swissnet",
    frozenset({"elinore", "patrick"}):  "elinore_patrick_ambiguous",   # 29 Tem: önce SwissNet teyit edilmişti, bugün FROSTYHOSTING-AS RU teyidi geldi, ikisine birden gönderiliyor
    frozenset({"stevie", "wilson"}):    "netiface",
    frozenset({"jen", "paul"}):         "pfcloud",

    # ── PRQ VPN Network SE ──
    frozenset({"decker", "liberty"}):   "prq",
    frozenset({"paris", "porter"}):     "prq",

    # ── FATCAT ailesi (DİKKAT: iki farklı abuse adresi var) ──
    frozenset({"gail", "lennox"}):      "fatcat_scrhost",
    frozenset({"candy", "nico"}):       "fatcat_scrhost",
    frozenset({"robin", "ram"}):        "fatcat_scrhost",
    frozenset({"alice", "seamus"}):     "fatcat_epikhost",
    frozenset({"ara", "mark"}):         "fatcat_epikhost",   # YENİ 07 Ağu 2026 — superbetin-resmigiris.icu (FATCAT NETWORK S.A., abuse@epikhost.org)

    # ── VPS Datacenter Ltd GB (private-data-center.com) ──
    frozenset({"ophelia", "theo"}):     "vpsdatacenter",
    frozenset({"garrett", "indie"}):    "vpsdatacenter",
    frozenset({"kipp", "penny"}):       "vpsdatacenter",
    frozenset({"eve", "sean"}):         "vpsdatacenter",
    frozenset({"jewel", "vin"}):        "vpsdatacenter",
    frozenset({"james", "maeve"}):      "vpsdatacenter",
    frozenset({"harlee", "tim"}):       "vpsdatacenter",
    frozenset({"leanna", "patrick"}):   "vpsdedicated_flashwisp",
    frozenset({"achiel", "nicole"}):    "weridata",   # DÜZELTİLDİ 28 Tem — panel VPS Datacenter tahmin etmişti, Cloudflare'in taze teyidi WERIDATA-LLC gösterdi
    frozenset({"andronicus", "emely"}): "vpsdatacenter",

    # ── Diğer host'lar ──
    frozenset({"opal", "ricardo"}):     "evoxt",
    frozenset({"sreeni", "zahir"}):     "evoxt",   # YENİ 05 Ağu 2026 — msuperbetin2085.com (aynı host Evoxt, farklı cluster)
    frozenset({"aron", "javier"}):      "colocatel",
    frozenset({"bowen", "rosemary"}):   "colocatel",
    frozenset({"paityn", "titan"}):     "cloudzy",
    frozenset({"gannon", "nancy"}):     "gannon_nancy_ambiguous",   # DÜZELTİLDİ 07 Ağu 2026 — superbetin2293.com üzerinden Omegatech teyidi geldi, önceden Play2Go kayıtlıydı
    frozenset({"daniella", "felipe"}):  "play2go",
    frozenset({"brenda", "leif"}):      "namecheap",
    frozenset({"candy", "edward"}):     "pfcloud",
    frozenset({"huxley", "kami"}):      "pfcloud_io",
    frozenset({"bonnie", "fred"}):      "sahinnetwork",
    frozenset({"katja", "tosana"}):     "frantech",
    frozenset({"khalid", "suzanne"}):   "frantech",
    frozenset({"kate", "ed"}):          "frantech",
    frozenset({"cosmin", "melany"}):    "frantech",
    frozenset({"mario", "norah"}):      "mario_norah_ambiguous",   # DÜZELTİLDİ 10 Ağu 2026 — superbetin2151.com üzerinden VPS Dedicated LLC teyidi geldi, önceden hep FranTech kayıtlıydı
    frozenset({"burt", "liz"}):          "frantech",   # YENİ 03 Ağu 2026 — superbetinorijinaladres.top, aynı host (FranTech) farklı cluster
    frozenset({"adaline", "joaquin"}):   "netiface",   # YENİ 03 Ağu 2026 — superbetinguncelgirisadrsi724.top üzerinden ilk kez görüldü (VPS Dedicated LLC, abuse@abusehandler.net) — adaline/chris'ten FARKLI bir cluster, karıştırılmasın
    frozenset({"pdns1", "pdns2"}):        "blazedge",   # YENİ 03-04 Ağu 2026 — superbetin2087.cam (jenerik PowerDNS isimlendirmesi, Blazedge'e ait)
    frozenset({"ezra", "veda"}):          "swissnet",   # YENİ 04 Ağu 2026 — 2087superbetin.com (SwissNet LLC, abuse@swissnetwork.io)
    frozenset({"adel", "albert"}):        "netiface",   # YENİ 04 Ağu 2026 — betsat-adresii2026.cam (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"elliott", "paloma"}):     "netiface",   # YENİ 06 Ağu 2026 — superbetinguncellgiris724.top (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"jack", "nora"}):          "netiface",   # YENİ 07 Ağu 2026 — betsat-2026.icu (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"emerson", "lady"}):       "netiface",   # YENİ 09 Ağu 2026 — superbetinsiteadresi.icu (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"corey", "lucy"}):          "corey_lucy_ambiguous",   # DÜZELTİLDİ 05 Ağu 2026 — paykodeme.com'da SYNLINQ, superbetin2344.com'da Omegatech çıktı, ikisine birden gönderiliyor
    frozenset({"aleena", "andronicus"}):   "frantech",   # YENİ 05 Ağu 2026 — superbetin-freeadres.vip (FranTech Solutions, admin@frantech.ca)
    frozenset({"luciane", "fattouche"}):    "swissnet",   # YENİ 05 Ağu 2026 — betin-aktif.vip (SwissNet LLC, abuse@swissnetwork.io) — luciane/oswald'dan FARKLI cluster, karıştırılmasın
    frozenset({"igor", "ziggy"}):           "netiface",   # YENİ 05 Ağu 2026 — superbetingunceladresi724.top (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"ernest", "oaklyn"}):    "netiface",
    frozenset({"bowen", "lauryn"}):     "netiface",
    frozenset({"adi", "langston"}):     "vpsdatacenter",
    frozenset({"kurt", "leah"}):        "colocatel",
    frozenset({"emely", "ishaan"}):     "colocatel",
    frozenset({"melody", "armando"}):   "colocatel",
    frozenset({"gene", "hans"}):        "colocatel",   # YENİ 10 Ağu 2026 — superbetinew-adresi.icu (ColocaTel Inc., abuse@colocatel.com)
    frozenset({"elaine", "emerson"}):   "colocatel",   # YENİ 07 Ağu 2026 — superbetin-son-bonusu.icu (ColocaTel Inc., abuse@colocatel.com)
    frozenset({"donovan", "melinda"}):  "netiface",   # DÜZELTİLDİ 03 Ağu 2026 — eskiden omegatech kayıtlıydı, bugün superbetiningercekgiris724.co üzerinden İKİ ayrı Cloudflare teyidi (Trademark + Phishing) tutarlı şekilde VPS Dedicated LLC/abusehandler.net gösterdi
    frozenset({"braden", "priscilla"}): "netiface",   # YENİ 03 Ağu 2026 — superbetin-resmi-giris.vip üzerinden ilk kez görüldü (VPS Dedicated LLC, abuse@abusehandler.net)
    frozenset({"aiden", "naya"}):       "synlinq",
    frozenset({"adaline", "chris"}):    "adaline_chris_ambiguous",   # DÜZELTİLDİ 03 Ağu 2026 — superbetin2342.com üzerinden Omegatech teyidi geldi, önceden SYNLINQ kayıtlıydı; ilk oturumdan beri şüphelenilen NS rotasyonu doğrulandı, ikisine birden gönderiliyor
    frozenset({"archer", "lana"}):      "digitalocean",   # YENİ 31 Tem — superbetin-tr.top (Aliyun/Dominet HK kayıtlı), archer/melissa'dan (omegatech) farklı
    frozenset({"paityn", "rick"}):      "ovh",            # YENİ 31 Tem — tr.superbetin-resmi.icu, paityn/titan'dan (cloudzy) farklı
    frozenset({"emerie", "kai"}):       "knownsrv",       # YENİ 07 Ağu 2026 — superbetin-girisadresi.cam (KnownSRV Ltd., abuse@pronect.hr)
    frozenset({"conrad", "veda"}):      "privatelayer",   # YENİ 09 Ağu 2026 — superbetinlive.co (Private Layer INC, abuse@privatelayer.com) — conrad/leia'dan (netiface) FARKLI cluster, karıştırılmasın
    frozenset({"decker", "dolly"}):     "alexhost",       # YENİ 05 Ağu 2026 — tr.turkbet-guncelgiris.cam (AlexHost SRL, noc@alexhost.com) — decker/liberty'den (PRQ) FARKLI cluster, karıştırılmasın
    frozenset({"burt", "kiki"}):        "alexhost",       # YENİ 06 Ağu 2026 — superbetin2249.com (aynı host AlexHost, farklı cluster)
    frozenset({"edna", "shane"}):       "swissnet",       # YENİ 06 Ağu 2026 — betsat1910.com (SwissNet LLC, abuse@swissnetwork.io)
    frozenset({"martha", "rex"}):       "netiface",       # YENİ 06 Ağu 2026 — bet.sat-girisleri.com (VPS Dedicated LLC, abuse@abusehandler.net) — önceki "guvenligirisler.co" vakasında host bilinmiyordu, şimdi teyit edildi
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
    """Dönüş: (cluster_pair, host_key, observed_ns_labels). observed_ns_labels
    her zaman (eşleşse de eşleşmese de) gerçek DNS sorgusundan gözlemlenen ham
    NS etiketlerini döndürür — böylece "cluster tespit edilemedi" durumunda bile
    domain'in GERÇEKTE hangi NS'lere sahip olduğunu görüp, bunun yeni bir
    cluster mı yoksa bilinen bir cluster'ın (örn. DNS'in geçici hata vermesi ya
    da domain NS'ini gerçekten değiştirmiş olması) sonucu mu olduğunu ayırt
    edebiliriz."""
    ns_labels = get_ns_labels(domain)
    if ns_labels == "NXDOMAIN":
        return None, DEAD_DOMAIN, None
    cluster_pair, host_key = match_cluster(ns_labels)
    return cluster_pair, host_key, ns_labels

# ============================================================
# REGISTRAR TESPİTİ (RDAP öncelikli, WHOIS yedekli) — v3, 23 Tem 2026
# ============================================================
# "nicenic" hedefi seçildiğinde, panel artık körlemesine NiceNIC'e
# göndermiyor — gerçek registrar'ı tespit edip, gerçekten NiceNIC ise
# devam ediyor, değilse doğru bilgiyi (registrar adı + varsa abuse
# maili) sonuçlara yazıp NiceNIC'e göndermeyi ATLIYOR. Bu, bugün
# odemeonay.com'da elle yaptığımız "WHOIS'a bak, doğru registrar'ı
# bul" işini otomatikleştiriyor.
#
# RDAP tüm gTLD'lerde (.com, .net, .icu, .vip, .top, .cam, vb.) ICANN
# tarafından zorunlu, JSON döner, güvenilir. Bazı ccTLD'ler (.io, .co
# gibi bazıları hariç) RDAP desteklemeyebilir — o durumda ham WHOIS'a
# (IANA üzerinden iki adımlı sorgu) düşülüyor. İkisi de başarısız
# olursa "tespit edilemedi" olarak işaretlenir, ASLA sessizce yanlış
# registrar'a gönderilmez.
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
    """IANA üzerinden TLD'nin gerçek WHOIS sunucusunu bulup domaini
    orada sorgular. RDAP başarısız olursa devreye girer."""
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
    # Verisign'in .com/.net WHOIS sunucusu, bulut/CI IP aralıklarından gelen
    # otomatik sorguları agresif şekilde rate-limit'lemesiyle bilinir — bu
    # muhtemelen .com domainlerinde gözlemlenen toplu WHOIS başarısızlığının
    # sebebi. Bu adımda kısa backoff ile 2 deneme yapılıyor.
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
    """RDAP yanıtlarında 'registrar' rolündeki entity bazen üst
    seviyede değil, başka bir entity'nin İÇİNDE (nested) oluyor —
    iç içe entity'lere de bakılıyor (recursive)."""
    for entity in entities or []:
        if "registrar" in entity.get("roles", []):
            return entity
        nested = _find_registrar_entity(entity.get("entities"))
        if nested:
            return nested
    return None

def _rdap_endpoints_for(domain):
    """Tek bir bootstrap redirector'a (rdap.org) güvenmek yerine birkaç
    endpoint sırayla denenir — 23 Tem 2026'da rdap.org tek başına
    domainlerin tamamında başarısız olmuştu. .com/.net için Verisign'in
    kendi RDAP sunucusuna DOĞRUDAN gitmek, bootstrap yönlendirmesinden
    daha güvenilir çıktı (mevcut whois_alert.py script'inde de böyle)."""
    tld = domain.rsplit(".", 1)[-1].lower()
    urls = [f"https://rdap.org/domain/{domain}"]
    if tld in ("com", "net"):
        urls.insert(0, f"https://rdap.verisign.com/{tld}/v1/domain/{domain}")
    urls.append(f"https://rdap.nic.vip/domain/{domain}")
    return urls

async def _rdap_registrar(session, domain):
    """Birden fazla RDAP endpoint'ini sırayla dener, ilk başarılı JSON
    yanıtını kullanır. NiceNIC tespiti, hassas entity/vcard ayrıştırması
    yerine ham JSON metninde 'nicenic' arayarak yapılır — yapısal
    farklılıklara (nested entity, farklı vcard sırası vb.) karşı çok
    daha dayanıklı bir yöntem."""
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
            # Registrar entity'si düzgün ayrıştırılamadı ama 200 döndü —
            # yine de "tespit edilemedi" yerine ham metinde bir isim
            # arayışını (nicenic dışında) burada bırakmıyoruz, sonraki
            # endpoint'e/WHOIS'e devrediyoruz.
            print(f"    ⚠️ RDAP {url} 200 döndü ama registrar adı çıkarılamadı ({domain})")
            continue
        return {"name": name, "email": email, "is_nicenic": is_nicenic}
    return None

async def detect_registrar(session, domain):
    """Dönüş: {"name": str|None, "email": str|None, "source": "rdap"|"whois"|None,
    "is_nicenic": bool}. Hem RDAP hem WHOIS başarısız olursa name=None döner —
    bu durumda çağıran kod NiceNIC'e göndermemeli, "tespit edilemedi" demeli."""
    rdap = await _rdap_registrar(session, domain)
    if rdap and rdap.get("name"):
        return {"name": rdap["name"], "email": rdap.get("email"), "source": "rdap", "is_nicenic": rdap["is_nicenic"]}
    whois_name = await asyncio.get_running_loop().run_in_executor(None, _whois_fallback_registrar, domain)
    if whois_name:
        is_nicenic = "nicenic" in whois_name.lower()
        return {"name": whois_name, "email": None, "source": "whois", "is_nicenic": is_nicenic}
    return {"name": None, "email": None, "source": None, "is_nicenic": False}

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
    # DEDUP (23 Tem 2026 bug fix): Aynı domain'in farklı URL varyantları
    # (tr.x.com, yatirim.x.com/havale/, x.com/login.php gibi) hepsi aynı
    # kök domaine indirgeniyor ama önceden tekilleştirilmiyordu — bu
    # yüzden aynı domain NiceNIC/host'a birden fazla kez gönderiliyor,
    # her seferinde ayrı bir ticket açılıyordu (superbetin2082.cam'de
    # görüldüğü gibi 5 ayrı NiceNIC ticket'ı). Artık sırayı koruyarak
    # tekilleştiriliyor.
    seen_domains = set()
    unique_domains = []
    for d in domains:
        if d not in seen_domains:
            seen_domains.add(d)
            unique_domains.append(d)
    domains = unique_domains

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

            found_urls = await discover_phishing_urls(session, domain)
            print(f"  📎 {len(found_urls)} canlı kanıt URL bulundu")
            print(f"  📧 Reporter e-postası: {reporter_email_for(brand_key)}")

            domain_results = []       # Telegram özeti için (isim, ok/fail/None) tuple'ları
            channels_json = []        # JSON çıktısı için yapılandırılmış liste
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
                    note = f"Gerçek registrar: {registrar_info['name']}"
                    if registrar_info.get("email"):
                        note += f" ({registrar_info['email']})"
                    note += f" [{registrar_info['source']}]"
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

            append_to_reported_files(domain)

            status_str = "  ".join(
                f"{'✅' if ok is True else '❌' if ok is False else '⚠️'} {name}"
                for name, ok in domain_results
            )
            summary_lines.append(
                f"🎯 `{domain}` ({brand_name}, {len(found_urls)} kanıt URL, reporter: {reporter_email_for(brand_key)})\n   {status_str}"
            )
            results_json["domains"].append({
                "domain": domain,
                "brand": brand_name,
                "found_urls_count": len(found_urls),
                "reporter_email": reporter_email_for(brand_key),
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
