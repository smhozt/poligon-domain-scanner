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
# MARKA AYARLARI — GÜNCEL (02 Temmuz 2026 itibarıyla)
# ============================================================
BRANDS = {
    "superbetin": {
        "name": "Superbetin",
        "active_domains": ["superbetin.com", "superbetin1841.com", "superbetin2052.com", "superbetin2053.com"],
        "signature_email": "yardim@superbetin.com",
    },
    "betsat": {
        "name": "Betsat",
        "active_domains": ["betsat.com", "betsat1596.com", "betsat1597.com"],
        "signature_email": "support@betsat.com",
    },
    "turkbet": {
        "name": "Turkbet",
        "active_domains": ["turkbet.io", "742turkbet.com", "744turkbet.com"],
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
# HOSTLAR — abuse adresleri
# ============================================================
HOSTS = {
    "netiface":      {"name": "Netiface LLC",             "abuse": ["abuse@abusehandler.net", "abuse@vpsdedicated.net"]},
    "omegatech":     {"name": "Omegatech LTD",             "abuse": ["abuse@pitline.net", "abuse@omegatech.sc"]},
    "advin":         {"name": "Advin Services LLC",        "abuse": ["anush@advinservers.com"]},
    "swissnet":      {"name": "SwissNet LLC",               "abuse": ["abuse@swissnetwork.io"]},
    "prq":           {"name": "PRQ VPN Network SE",         "abuse": ["abuse@dcs.net"]},
    "fatcat":        {"name": "FATCAT-AS / scrhost.com",    "abuse": ["info@scrhost.com"]},
    "vpsdatacenter": {"name": "VPS Datacenter Ltd",          "abuse": ["abuse@private-data-center.com"]},
}

# ============================================================
# CLUSTER HARİTASI — NS etiket çifti (frozenset, sırasız) -> host_key
# ============================================================
# Yeni bir cluster Cloudflare raporuyla teyit edildikçe buraya eklenir.
# Bilinmeyen cluster'lar OTOMATİK GÖNDERİLMEZ — unknown_clusters.json'a
# loglanır, Telegram'a bildirilir, elle CF raporuyla host tespiti bekler.
CLUSTER_MAP = {
    frozenset({"drew", "leia"}):        "netiface",
    frozenset({"carol", "mustafa"}):    "netiface",
    frozenset({"keaton", "shaz"}):      "netiface",
    frozenset({"venus", "carmelo"}):    "netiface",
    frozenset({"justin", "sierra"}):    "netiface",
    frozenset({"conrad", "leia"}):      "netiface",
    frozenset({"candy", "edward"}):     "netiface",
    frozenset({"buck", "phoenix"}):     "netiface",
    frozenset({"princess", "rory"}):    "netiface",
    frozenset({"charles", "novalee"}):  "netiface",

    frozenset({"syeef", "tina"}):       "omegatech",
    frozenset({"isla", "nolan"}):       "omegatech",
    frozenset({"aisha", "langston"}):   "omegatech",
    frozenset({"archer", "melissa"}):   "omegatech",
    frozenset({"dane", "alice"}):       "omegatech",

    frozenset({"ruben", "ariella"}):    "advin",

    frozenset({"penny", "tanner"}):     "swissnet",
    frozenset({"elliot", "marlowe"}):   "swissnet",
    frozenset({"ainsley", "lamar"}):    "swissnet",
    frozenset({"lee", "aida"}):         "swissnet",

    frozenset({"decker", "liberty"}):   "prq",
    frozenset({"paris", "porter"}):     "prq",

    frozenset({"gail", "lennox"}):      "fatcat",
    frozenset({"candy", "nico"}):       "fatcat",

    frozenset({"ophelia", "theo"}):     "vpsdatacenter",
    frozenset({"garrett", "indie"}):    "vpsdatacenter",
    frozenset({"kipp", "penny"}):       "vpsdatacenter",
}
# Bilinen ama host'u HALEN tespit edilmemiş cluster'lar (bilgi amaçlı,
# eşleşme yapılmaz — sadece log mesajında "known-unresolved" diye ayırmak için):
KNOWN_UNRESOLVED_CLUSTERS = {
    frozenset({"lovisa", "max"}),
    frozenset({"ainsley", "everton"}),
}

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
    return match_cluster(ns_labels)

# ============================================================
# MAİL İÇERİĞİ
# ============================================================
def build_host_email(domain, host_key, brand_key, cluster_pair):
    host = HOSTS[host_key]
    brand = BRANDS[brand_key]
    active_domains_str = " / ".join(brand["active_domains"])
    cluster_label = "/".join(sorted(cluster_pair)) if cluster_pair else "manually confirmed hosting"

    subject = f"URGENT: Active Phishing & Trademark Infringement — {domain} — {host['name']} Hosted ({cluster_label})"

    signature_block = f"CS Operations & Technology\nPoligon Entertainment N.V.\n{brand['signature_email']}"
    if "signature_footer" in brand:
        signature_block += f"\n\n{brand['signature_footer']}"

    body = f"""Dear {host['name']} Abuse Team,

We are writing on behalf of Poligon Entertainment N.V., the licensed
operator of {brand['name']} (official: {active_domains_str}), under
Curaçao Gaming Authority license OGL/2024/815/0653.

The domain {domain}, hosted on your infrastructure via the {cluster_label}
nameserver cluster, is operating an active phishing site impersonating
our licensed brand, using cloned graphics, trademarked layouts, and fake
login/payment forms to deceive consumers.

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
    sent_roots = set()

    for domain in candidates[:20]:
        root = get_root(domain)
        if root in sent_roots:
            complaint_done.add(domain)
            continue

        print(f"NS kontrol ediliyor: {root}")
        cluster_pair, host_key = resolve_host_for_domain(root, manual_overrides)

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
        subject, body = build_host_email(root, host_key, brand_key, cluster_pair)
        host = HOSTS[host_key]

        print(f"  ✉️  {host['name']} adresine gönderiliyor: {root}")
        success = send_email(
            host["abuse"],
            subject,
            body,
            from_name=f"{BRANDS[brand_key]['name']} Security Team"
        )

        if success:
            success_list.append((root, host["name"]))
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
        for d, hostname in success_list[:10]:
            msg += f"  🔹 `{d}` → {hostname}\n"
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

    msg += f"\n📬 *Gönderen:* `{SMTP_USER}`"

    await send_telegram(msg)
    print(f"\n✅ Tamamlandı! {len(success_list)} mail gönderildi, {len(unknown_list)} domain elle incelemeye düştü.")

if __name__ == "__main__":
    asyncio.run(main())
