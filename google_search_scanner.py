import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone, timedelta, date
from urllib.parse import urlparse, quote_plus

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

# ============================================================
# BEYAZ LİSTE — v3 güncel (17 Haziran 2026)
# ============================================================
def _expand(domain):
    """Bir domain için www., m., tr. ve bare hallerini üret"""
    variants = {domain, f"www.{domain}", f"m.{domain}", f"tr.{domain}"}
    return variants


NEW_AFFILIATES = set()
for d in [
    # Turkbet güncel giriş affiliate
    "turkbet-guncelgiris.com",
    "turkbet-guncelgiris.net",
    "turkbet-guncelgiris.co",
    "turkbet-guncelgiris.vip",
    "turkbet-guncelgiris.xyz",
    "turkbet-guncelgiris.sbs",
    # Superbetin güncel giriş affiliate
    "superbetin-guncelgiris1.vip",
    "superbetin-guncelgiris.co",
    "superbetin-guncelgiris.club",
    "superbetin-guncelgiris1.com",
    "superbetin-guncelgiris1.net",
    "superbetin-guncelgiris1.co",
    # Betsat güncel giriş affiliate
    "betsat-guncelgiris1.xyz",
    "betsat-guncelgiris1.com",
    "betsat-guncelgiris1.net",
    "betsat-guncelgiris1.co",
    "betsat-guncelgiris1.vip",
    "betsat-guncelgiris1.online",
]:
    NEW_AFFILIATES.update(_expand(d))

# ── 07 Temmuz 2026 eklemeleri — vip_scanner.py ile aynı 58 domain,
# bu scriptte de tutarlılık için ekleniyor. ──────────────────────
JULY07_NEW_ENTRIES = set()
for d in [
    "superbetinbahissite.vip", "superbetinbahissite.org", "superbetinbahissite.sbs",
    "superbetinbahissite.xyz", "superbetinbahissite.club", "superbetinbahissite.online",
    "superbetinbahissite.cyou",
    "superbetinbahissite1.vip", "superbetinbahissite1.org", "superbetinbahissite1.com",
    "superbetinbahissite1.net", "superbetinbahissite1.sbs", "superbetinbahissite1.us",
    "superbetinbahissite1.xyz", "superbetinbahissite1.club", "superbetinbahissite1.online",
    "superbetinbahissite1.click", "superbetinbahissite1.cyou", "superbetinbahissite1.cfd",
    "turkbet-turkgiris.sbs", "turkbet-turkgiris.vip", "turkbet-turkgiris.com",
    "turkbet-turkgiris.net", "turkbet-turkgiris.xyz", "turkbet-turkgiris.club",
    "turkbet-turkgiris.online",
    "1turkbet-turkgiris.vip", "1turkbet-turkgiris.org", "1turkbet-turkgiris.com",
    "1turkbet-turkgiris.net", "1turkbet-turkgiris.sbs", "1turkbet-turkgiris.us",
    "1turkbet-turkgiris.xyz", "1turkbet-turkgiris.club", "1turkbet-turkgiris.online",
    "1turkbet-turkgiris.cyou", "1turkbet-turkgiris.cfd",
    "2turkbet-turkgiris.vip", "turkiyebet.net",
    "betsatbahisgiris.vip", "betsatbahisgiris.xyz", "betsatbahisgiris.online",
    "betsatbahisgiris.cyou", "betsatbahisgiris.cfd",
    "betsatbahisgirisim.vip", "betsatbahisgirisim.org", "betsatbahisgirisim.com",
    "betsatbahisgirisim.net", "betsatbahisgirisim.sbs", "betsatbahisgirisim.club",
    "betsatbahisgirisim.online", "betsatbahisgirisim.click",
    "betsatbahisgirisimyap.vip", "betsatbahisgirisimyap.org", "betsatbahisgirisimyap.com",
    "betsatbahisgirisimyap.sbs", "betsatbahisgirisimyap.xyz", "betsatbahisgirisimyap.net",
    "betsatbahisgirisimyap.club",
]:
    JULY07_NEW_ENTRIES.update(_expand(d))

WHITELIST_DOMAINS = {
    # ana + GÜNCEL resmi (8 Eki 2026)
    "turkbet.io", "betsat.com", "superbetin.com",
    "superbetin2904.com", "superbetin2903.com", "betsat1840.com", "776turkbet.com",
    "betsat1842.com", "777turkbet.com",   # 9 Eki 2026 yeni güncel resmi
    "bahiskazani.com",   # Semih'in kendi Betsat güncel giriş/rehber sitesi
    # yakın zamanda emekli resmi (ikinci el sonuçlarda hâlâ görünür)
    "superbetin2902.com", "superbetin2109.com", "superbetin2108.com",
    "superbetin2106.com", "superbetin2111.com",
    "betsat1839.com", "betsat1838.com", "betsat1837.com",
    "775turkbet.com", "774turkbet.com", "773turkbet.com", "772turkbet.com",
    "superbetin1834.com",
    "betsat1578.com", "730turkbet.com",
    "betsat1577.com", "728turkbet.com",
    # GÜNCEL resmi (16 Eki 2026)
    "superbetin2907.com", "betsat1844.com", "778turkbet.com",
    # yakın zamanda emekli resmi (16 Eki 2026'ya kadar)
    "superbetin2906.com", "betsat1843.com",
    # GÜNCEL resmi (5 Eki 2026)
    "superbetin2111.com", "betsat1838.com", "773turkbet.com",
    # ── Superbetin SEO / Affiliate ───────────────────────────
    "superbetingiris724.co", "www.superbetingiris724.co",
    "superbetinegiris.com", "www.superbetinegiris.com",
    "superbetinmobil.com", "www.superbetinmobil.com",
    "superbetingiris.mobi", "www.superbetingiris.mobi",
    "superbetinyeniadres.online", "www.superbetinyeniadres.online",
    "superbetinresmi.com", "www.superbetinresmi.com",
    "superbetingiris724.org", "www.superbetingiris724.org",
    "superbetingiris724.info", "www.superbetingiris724.info",
    "superbetingeliyor.com", "www.superbetingeliyor.com",
    "superbetingir.com", "www.superbetingir.com",
    "superbetincasino.com", "www.superbetincasino.com",
    "superbetincanli.org", "www.superbetincanli.org",
    "superbetingirisyap.com", "www.superbetingirisyap.com",
    "superbetinyeniadresi.net", "www.superbetinyeniadresi.net",
    "superbetinim.com", "www.superbetinim.com",
    "superbetinadresim.com", "www.superbetinadresim.com",
    "superbetinegir.com", "www.superbetinegir.com",
    "superbetingirisi.co", "www.superbetingirisi.co",
    "superbetino.com", "www.superbetino.com",
    "superbetine.com", "www.superbetine.com",
    "girissuperbetin.net", "www.girissuperbetin.net",
    "724superbetinresmi.net", "www.724superbetinresmi.net",
    "m.724superbetinresmi.net",
    "superbetpicks.com", "www.superbetpicks.com",
    "superiorforexsignals.com", "www.superiorforexsignals.com",
    "betinsuper.com", "www.betinsuper.com",
    "superbetintr.online", "www.superbetintr.online",
    "superbetintr.net",    "www.superbetintr.net",
    "superbetintr.com",    "www.superbetintr.com",
    "mobile.superbetintr.com", "app.superbetintr.com",
    "superbetinyeniadres.co", "www.superbetinyeniadres.co",
    "superbetinyeniadres.app", "www.superbetinyeniadres.app",
    "superbetintr.org", "www.superbetintr.org",
    "superbetingirisi.com", "www.superbetingirisi.com",
    "superbetingiris.com", "www.superbetingiris.com",
    "m.superbetingiris.com",
    "s1.superbetingiris.com", "s2.superbetingiris.com", "s3.superbetingiris.com",
    "superbetinyeniadresi.com", "www.superbetinyeniadresi.com",
    "www.superbetingiris.mobi",
    "superbetin-giris.com", "www.superbetin-giris.com",
    "superbetintr.live", "www.superbetintr.live",
    "www.superbetingir.com",
    "superbettingiris.com", "www.superbettingiris.com",
    "superbetin-giris.org",    "www.superbetin-giris.org",
    "superbetin-giris.net",    "www.superbetin-giris.net",
    "superbetin-giris1.com",   "www.superbetin-giris1.com",
    "superbetin-giris1.org",   "www.superbetin-giris1.org",
    "superbetin-giris2.com",   "www.superbetin-giris2.com",
    "superbetin-giris2.org",   "www.superbetin-giris2.org",
    # ── Betsat SEO / Affiliate ───────────────────────────────
    "betsatgiris1.com", "www.betsatgiris1.com",
    "betsatturkiye.com", "www.betsatturkiye.com",
    "betsatresmigiris.com", "www.betsatresmigiris.com",
    "m.betsatresmigiris.com",
    "betsatguncelgiris2026.com", "www.betsatguncelgiris2026.com",
    "betsatyenigiris2026.com", "www.betsatyenigiris2026.com",
    "betsat-bahis.site", "www.betsat-bahis.site",
    "betsatbahis.info", "www.betsatbahis.info",
    "betsatrs.com", "www.betsatrs.com",
    "betsatdestek.com", "www.betsatdestek.com",
    "betsatur.com", "www.betsatur.com",
    "cubetsat.com", "www.cubetsat.com",
    "nobetsat.com", "www.nobetsat.com",
    "betsatadres.com", "www.betsatadres.com",
    "betsation.com", "www.betsation.com",
    "betsatan.com", "www.betsatan.com",
    "betsatcasino.net", "www.betsatcasino.net",
    "betsatyeniadresi.com", "www.betsatyeniadresi.com",
    "betsatgirisadresi.xyz", "www.betsatgirisadresi.xyz",
    "betsat-giris.org", "www.betsat-giris.org",
    "betsatonlinecasino.com", "www.betsatonlinecasino.com",
    "betsat.mobi", "www.betsat.mobi",
    "muhtesembetsat.com", "www.muhtesembetsat.com",
    "betsatgiris.online", "www.betsatgiris.online",
    "m.betsatgiris.online",
    "mobilbetsat.com", "www.mobilbetsat.com",
    "betsatofficial.com", "www.betsatofficial.com",
    "betsat.tv", "www.betsat.tv",
    "betsatguncelgirisi.com", "www.betsatguncelgirisi.com",
    "betsat-giris.com", "www.betsat-giris.com",
    "betsathizligiris.com", "www.betsathizligiris.com",
    "betsatgunceladresi.com", "www.betsatgunceladresi.com",
    "betsatgirisadresim.com", "www.betsatgirisadresim.com",
    "betsatmobilgiris.com", "www.betsatmobilgiris.com",
    "betsatamp.top", "www.betsatamp.top",
    "betsatonline.com", "www.betsatonline.com",
    "betsatonlinegiris.com", "www.betsatonlinegiris.com",
    "betsat.xyz", "www.betsat.xyz",
    "betsat.pro", "www.betsat.pro",
    "betsatgiris.casino", "www.betsatgiris.casino",
    "betsatadresi.io", "www.betsatadresi.io",
    "betsattr.net", "www.betsattr.net",
    "betsatguncel.me", "www.betsatguncel.me",
    "betsat-girisim.com", "www.betsat-girisim.com",
    "betsatgirisim.co", "www.betsatgirisim.co",
    "betsat.co", "www.betsat.co",
    "girisbetsat.top", "www.girisbetsat.top",
    "betsatgiris.org", "www.betsatgiris.org",
    "betsatgiris.net", "www.betsatgiris.net",
    "betsatgir.net", "www.betsatgir.net",
    "betsatgirisi.net", "www.betsatgirisi.net",
    "betsatgirisi.org", "www.betsatgirisi.org",
    "betsat-vip.com", "www.betsat-vip.com",
    "betsat-giris.online",  "www.betsat-giris.online",
    "betsat-giris1.com",    "www.betsat-giris1.com",
    "betsat-giris1.org",    "www.betsat-giris1.org",
    "betsat-giris2.com",    "www.betsat-giris2.com",
    "betsat-giris2.org",    "www.betsat-giris2.org",
    # ── Turkbet SEO / Affiliate ──────────────────────────────
    "turkbet.cam", "www.turkbet.cam",
    "soloturkbet.com", "www.soloturkbet.com",
    "asyaturkbet.com", "www.asyaturkbet.com",
    "turkbetturkiye.com", "www.turkbetturkiye.com",
    "turkbet2026.net", "www.turkbet2026.net",
    "turkbetcanli.com", "www.turkbetcanli.com",
    "turkbet.es", "www.turkbet.es",
    "turkbet2026.com", "www.turkbet2026.com",
    "turkbetgir.com", "www.turkbetgir.com",
    "m.turkbetgir.com",
    "turkbet.info", "www.turkbet.info",
    "turkbetborsa.com", "www.turkbetborsa.com",
    "turkbetsitesi.com", "www.turkbetsitesi.com",
    "turkbetspor.com", "www.turkbetspor.com",
    "turkbetbayilik.com", "www.turkbetbayilik.com",
    "turkbetik.com", "www.turkbetik.com",
    "turkbetsson.com", "www.turkbetsson.com",
    "hititturkbet.com", "www.hititturkbet.com",
    "turkbetyeniadres.com", "www.turkbetyeniadres.com",
    "turkbet-girisi.com", "www.turkbet-girisi.com",
    "turkbetgirisin.co", "www.turkbetgirisin.co",
    "turkbetadresi.me", "www.turkbetadresi.me",
    "turkbet.cx", "www.turkbet.cx",
    "turkbetyeni.site", "www.turkbetyeni.site",
    "turkbetadresim.com", "www.turkbetadresim.com",
    "turkbettr.com", "www.turkbettr.com",
    "turkbetadres.io", "www.turkbetadres.io",
    "turkbetguncel.com", "www.turkbetguncel.com",
    "turkbetgunceladresi.com", "www.turkbetgunceladresi.com",
    "turkbetgirisi.co", "www.turkbetgirisi.co",
    "turkbetgirisi.com", "www.turkbetgirisi.com",
    "turkbetgo.com", "www.turkbetgo.com",
    "turk-bets.com", "www.turk-bets.com",
    "trturkbet.com", "www.trturkbet.com",
    "turkbetadresim.co", "www.turkbetadresim.co",
    "turkbetgiris.pro", "www.turkbetgiris.pro",
    "turkgirisim.com", "www.turkgirisim.com",
    "turkbetadresi.co", "www.turkbetadresi.co",
    "turkbetgiris.online", "www.turkbetgiris.online",
    "turkbetadres.com", "www.turkbetadres.com",
    "turkbetgirisim.com", "www.turkbetgirisim.com",
    "turkbetgir.cc",
    "turkbet-giris.org",    "www.turkbet-giris.org",
    "turkbet-giris.online", "www.turkbet-giris.online",
    "turkbet-giris.xyz",    "www.turkbet-giris.xyz",
    "turkbet-giris1.org",   "www.turkbet-giris1.org",
    "turkbet-giris1.com",   "www.turkbet-giris1.com",
    # ── Genel güvenilir ──────────────────────────────────────
    "kacoldu.xyz", "yonleniyoramp.com", "yonelamp123.com", "googlecdnservice.net",
    "supetbetingirisadresim.vip", "turkbetgirisadresim.vip",
    "betsatgirisadresim.vip",
    "sikayetvar.com", "eksisozluk.com",
    "google.com", "youtube.com", "twitter.com",
    "facebook.com", "instagram.com", "t.me",
    "wikipedia.org", "reddit.com", "x.com",
    "bahisanaliz.com", "betanaliz.com",
    "askgamblers.com", "casinocity.com",
    "bojoko.com", "casinocity.com", "lcb.org",
    "optimobet.com", "casino.guru", "gamblersanonymous.org",
}

# Turkbet'in kayıtlı (registrar listesinde olan) kendi domainleri: 517-824turkbet.com + diğerleri.
# 825+ listede yok, bilerek eklenmedi.
WHITELIST_DOMAINS.update(f"{num}turkbet.com" for num in range(517, 825))
WHITELIST_DOMAINS.update([
    "copyrightturkbet.com", "officialturkbet.com",
    "likerto.com", "lilikom.com", "putukma.com", "tuklida.com",
    "tb.belloatech.dev",
])

# Yeni affiliate domainleri ekle (www + m + bare)
WHITELIST_DOMAINS.update(NEW_AFFILIATES)
WHITELIST_DOMAINS.update(JULY07_NEW_ENTRIES)

# ============================================================
# BÜTÇE — SerpAPI Production plan: 15.000 arama/ay, yenileme 12 Eki 2026
# ============================================================
RENEWAL_DATE      = date(2026, 10, 12)
RUNS_PER_DAY      = int(os.environ.get("SERP_RUNS_PER_DAY", "1"))   # günde kaç kez çalışıyor
BOOST_DAILY       = 2000    # yenilemeye kadar: kalan kota boşa gitmesin
NORMAL_DAILY      = 450     # yenileme sonrası: 15.000 / 30 ≈ 500, biraz pay bırak


def today_sofia():
    return datetime.now(TZ_SOFIA).date()


def daily_budget():
    env = os.environ.get("SERP_DAILY_BUDGET")
    if env:
        return int(env)
    return BOOST_DAILY if today_sofia() < RENEWAL_DATE else NORMAL_DAILY


BOOST_MODE   = os.environ.get("SERP_DAILY_BUDGET") is None and today_sofia() < RENEWAL_DATE
RUN_BUDGET   = max(20, daily_budget() // max(1, RUNS_PER_DAY))
CORE_PAGES   = 3 if BOOST_MODE else 1     # çekirdek sorgular: kaç sayfa
EXTRA_PAGES  = 3 if BOOST_MODE else 2     # ekstra sorgular: en fazla kaç sayfa
EXTRA_PER_RUN = 10_000 if BOOST_MODE else 25   # bir koşuda kaç ekstra sorgu (rotasyon)
SERP_STRICT  = os.environ.get("SERP_STRICT", "0") == "1"
SERP_TIMEOUT = int(os.environ.get("SERP_TIMEOUT", "75"))
MAX_RUNTIME  = int(os.environ.get("MAX_RUNTIME_MIN", "45")) * 60   # toplam süre sınırı
START_TS     = datetime.now().timestamp()
TIMEOUT_STREAK = 0                        # üst üste timeout sayısı (devre kesici)
SERP_CALLS   = 0                          # bu koşuda harcanan SerpAPI araması


def time_up():
    return datetime.now().timestamp() - START_TS > MAX_RUNTIME


def budget_left():
    return RUN_BUDGET - SERP_CALLS


# ============================================================
# ARAMA SORGULARI
# ============================================================
SEARCH_QUERIES = [
    # Superbetin
    "superbetin", "süperbetin",
    "superbetin giriş", "superbetin güncel adres",
    "superbetin güncel giriş", "superbetin yeni giriş",
    "superbetin mobil", "superbetin bahis",
    "superbetin casino", "superbetin resmi yeni adres",
    "superbetin vip güncel",
    "süperbetin giriş", "süperbetin güncel adres",
    "süperbetin güncel giriş", "süperbetin yeni giriş",
    "süperbetin mobil", "süperbetin bahis",
    "süperbetin casino", "süperbetin resmi yeni adres",
    "süperbetin vip güncel",
    # Betsat
    "betsat", "betsat giriş", "betsat güncel adres",
    "betsat yeni adres", "betsat yeni giriş",
    "betsat bahis", "betsat casino",
    "betsat mobil", "betsat resmi adres",
    "betsat güvenilir adres",
    # Turkbet
    "turkbet", "turkbet giriş", "turkbet güncel adres",
    "turkbet yeni adres", "turkbet yeni giriş",
    "turkbet bahis", "turkbet casino",
    # YENİ 8 Eki 2026 — türkçe karakterli turkbet
    "türkbet", "türkbet giriş", "türkbet güncel adres",
]

# ── EKSTRA SORGULAR (günlük rotasyon) ─────────────────────────
_BRANDS = ["superbetin", "betsat", "turkbet"]
_PHRASES = [
    "giriş linki", "yeni adres 2026", "güncel giriş adresi", "resmi giriş",
    "mobil giriş", "apk indir", "uygulama indir", "bonus", "deneme bonusu",
    "freespin", "canlı destek", "şikayet", "para yatırma", "para çekme",
    "papara", "yatırım bonusu", "telegram", "kayıt ol", "hoşgeldin bonusu",
    "vpn olmadan giriş", "bugün giriş", "anlık giriş", "kesintisiz giriş",
    "yeni giriş adresi bugün",
]
EXTRA_QUERIES = [f"{b} {p}" for b in _BRANDS for p in _PHRASES]

# resmi/pasif numaralar: taklit ve kopya sayfalar
EXTRA_QUERIES += [
    "superbetin2904", "superbetin2903", "superbetin2902", "superbetin2109",
    "betsat1842", "777turkbet", "betsat1842 giriş", "777turkbet giriş",
    "betsat1840", "betsat1839", "776turkbet", "775turkbet",
    "superbetin2904 giriş", "superbetin2903 giriş", "betsat1840 giriş", "776turkbet giriş",
]
# yazım hataları
EXTRA_QUERIES += [
    "supcrbetin giriş", "süpebetin giriş", "super betin giriş", "superbetin gir",
    "betsatt giriş", "betsaat giriş", "bet sat giriş", "turkbett giriş",
    "turk bet giriş",
]
# TLD bazlı site: sorguları (spam TLD'ler)
_SPAM_TLDS = ["cam", "icu", "vip", "cfd", "sbs", "xyz", "click", "top",
              "online", "site", "live", "win", "us", "cyou", "club", "mobi"]
EXTRA_QUERIES += [f'site:.{t} (superbetin OR betsat OR turkbet)' for t in _SPAM_TLDS]
EXTRA_QUERIES = list(dict.fromkeys(EXTRA_QUERIES))

BRAND_KEYWORDS = {
    "superbetin": ["superbetin", "süperbetin", "super-betin", "supberbetin",
                   "supetbetin", "supcrbetin", "süpebetin", "super betin"],
    "betsat":     ["betsat", "bet-sat", "betsatz", "betsatt", "betsaat", "bet sat"],
    "turkbet":    ["turkbet", "turk-bet", "türkbet", "turkbett", "turk bet"],
}

REPORTED_FILE = "google_reported.json"


def load_reported():
    try:
        with open(REPORTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()


def save_reported(reported):
    with open(REPORTED_FILE, "w") as f:
        json.dump(list(reported), f)


def is_whitelisted(url):
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        for w in WHITELIST_DOMAINS:
            w_clean = w.removeprefix("www.")
            if domain == w_clean or domain.endswith("." + w_clean):
                return True
        return False
    except:
        return True


def detect_brand(query):
    q = query.lower()
    if q.startswith("site:"):
        # birden fazla markalı sorgu: tüm anahtar kelimelerle eşle, marka sonuçtan çıkar
        return "multi", sum(BRAND_KEYWORDS.values(), [])
    if "betsat" in q or "bet sat" in q or "betsaat" in q or "betsatt" in q:
        return "betsat", BRAND_KEYWORDS["betsat"]
    elif "turkbet" in q or "türkbet" in q or "turk bet" in q or "turkbett" in q:
        return "turkbet", BRAND_KEYWORDS["turkbet"]
    else:
        return "superbetin", BRAND_KEYWORDS["superbetin"]


def brand_from_hit(domain, title, snippet, default):
    """multi sorgularda markayı sonuçtan belirle"""
    if default != "multi":
        return default
    text = f"{domain} {title} {snippet}".lower()
    for b, kws in BRAND_KEYWORDS.items():
        if any(k in text for k in kws):
            return b
    return "superbetin"


async def search_serpapi(session, query, device="desktop", location="Turkey",
                         hl="tr", gl="tr", pages=1, tbs=None):
    """Sayfalı SerpAPI araması. Yalnızca başarılı (200) çağrılar bütçeden düşer.
    Zaman aşımı/hata olursa 3 kez dener. Bir sayfa 8'den az organik sonuç
    döndürürse sonraki sayfa çekilmez."""
    global SERP_CALLS, TIMEOUT_STREAK
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        print("SERPAPI_KEY eksik!")
        return []
    results = []
    for page in range(pages):
        if budget_left() <= 0:
            print(f"  Bütçe doldu ({SERP_CALLS}/{RUN_BUDGET}) — durduruldu")
            break
        url = (
            f"https://serpapi.com/search.json"
            f"?q={quote_plus(query)}"
            f"&location={quote_plus(location)}&hl={hl}&gl={gl}"
            f"&device={device}"
            f"&start={page * 10}"
            f"&api_key={api_key}"
        )
        if SERP_STRICT:                  # SERP_STRICT=1: otomatik düzeltme + benzer sonuç filtresi kapalı
            url += "&nfpr=1&filter=0"
        if tbs:
            url += f"&tbs={quote_plus(tbs)}"
        data = None
        for attempt in range(2):
            if time_up() or TIMEOUT_STREAK >= 12:
                break
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=SERP_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        SERP_CALLS += 1
                        TIMEOUT_STREAK = 0
                        break
                    print(f"SerpAPI HTTP {resp.status}: {query} (deneme {attempt+1})")
                    if resp.status in (401, 403):
                        break
            except Exception as e:
                TIMEOUT_STREAK += 1
                print(f"SerpAPI {type(e).__name__} ({query}) deneme {attempt+1}: {e}")
            await asyncio.sleep(2 * (attempt + 1))
        if data is None:
            break
        organic = data.get("organic_results", [])
        for item in organic:
            results.append({
                "url":     item.get("link", ""),
                "title":   item.get("title", ""),
                "snippet": item.get("snippet", ""),
            })
        for item in data.get("ads", []):
            results.append({
                "url":     item.get("link", ""),
                "title":   item.get("title", ""),
                "snippet": item.get("snippet", ""),
            })
        if len(organic) < 8:
            break
        await asyncio.sleep(0.5)
    return results


OXYLABS_AUTH_FAILED = False


async def search_oxylabs(session, query):
    global OXYLABS_AUTH_FAILED
    username = "smhscan_FGXOT"
    password = os.environ.get("OXYLABS_PASSWORD", "")
    if not password:
        print("OXYLABS_PASSWORD eksik!")
        return []
    payload = {
        "source":      "google_search",
        "query":       query,
        "geo_location":"Turkey",
        "locale":      "tr-TR",
        "parse":       True,
        "pages":       5,
        "start_page":  1,
    }
    results = []
    try:
        auth = aiohttp.BasicAuth(username, password)
        async with session.post(
            "https://realtime.oxylabs.io/v1/queries",
            json=payload, auth=auth,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                organic = (
                    data.get("results", [{}])[0]
                        .get("content", {})
                        .get("results", {})
                        .get("organic", [])
                )
                for item in organic:
                    results.append({
                        "url":     item.get("url", ""),
                        "title":   item.get("title", ""),
                        "snippet": item.get("desc", ""),
                    })
                print(f"  Oxylabs: {len(results)} sonuç ({query})")
            else:
                print(f"Oxylabs HTTP {resp.status}: {query}")
                if resp.status in (401, 403):
                    OXYLABS_AUTH_FAILED = True
    except Exception as e:
        print(f"Oxylabs hatası ({query}): {e}")
    return results


async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try:
                await session.post(url, json={
                    "chat_id":                  chat_id.strip(),
                    "text":                     message,
                    "parse_mode":               "Markdown",
                    "disable_web_page_preview": True,
                })
            except Exception as e:
                print(f"Telegram hatası: {e}")


async def flush(found, reported, label=""):
    """Bulunanları hemen Telegram'a gönder, reported dosyasını kaydet, listeyi boşalt."""
    save_reported(reported)
    if not found:
        return
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    by_brand = {}
    for item in sorted(found, key=lambda x: x.get("conf") != "high"):
        by_brand.setdefault(item["brand"], []).append(item)
    brand_icons = {"superbetin": "🔵", "betsat": "🟠", "turkbet": "🟢"}
    n_high = sum(1 for i in found if i.get("conf") == "high")
    msg = (f"🖥️ *[GOOGLE ALARM] Sahte Site Tespit!* — {now} ({label})\n"
           f"🌐 domain'de marka: {n_high} | 🔍 sadece içerikte marka: {len(found)-n_high}\n\n")
    for brand, items in by_brand.items():
        icon = brand_icons.get(brand, "🔴")
        msg += f"{icon} *{brand.upper()}* — {len(items)} site\n"
        for item in items:
            mark = "🌐" if item.get("conf") == "high" else "🔍"
            msg += f"  {mark} `{item['domain']}`\n"
            msg += f"  📌 _{item['query']}_\n"
            msg += f"  🔗 {item['url']}\n\n"
    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        await send_telegram(chunk)
    print(f"✅ {len(found)} yeni sahte site gönderildi ({label})")
    found.clear()


def process_results(results, brand, keywords, query, reported, found):
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        domain = urlparse(url).netloc.lower()
        if is_whitelisted(url):
            continue
        if domain in reported:
            continue
        title_lower   = r.get("title",   "").lower()
        snippet_lower = r.get("snippet", "").lower()
        domain_lower  = domain.lower()
        domain_hit = any(k in domain_lower for k in keywords)
        text_hit   = any(k in title_lower or k in snippet_lower for k in keywords)
        if domain_hit or text_hit:
            b = brand_from_hit(domain_lower, title_lower, snippet_lower, brand)
            found.append({
                "brand":   b,
                "conf":    "high" if domain_hit else "low",
                "query":   query,
                "url":     url,
                "domain":  domain,
                "title":   r.get("title", ""),
                "snippet": r.get("snippet", "")[:120],
            })
            reported.add(domain)
            print(f"[BULUNDU-{'YUKSEK' if domain_hit else 'DUSUK'}] {domain} ({b.upper()}) — '{query}'")


MOBILE_QUERIES   = ["superbetin", "süperbetin", "betsat", "turkbet", "superbetin giriş", "betsat giriş"]
OXYLABS_QUERIES  = ["superbetin", "süperbetin", "betsat"]
ISTANBUL_QUERIES = ["superbetin", "süperbetin", "betsat", "turkbet", "superbetin giriş", "betsat giriş"]

# Mobil/şehir listeleri (boost modunda ek lokasyonlar)
EXTRA_LOCATIONS = ["Ankara,Turkey", "Izmir,Turkey", "Bursa,Turkey", "Antalya,Turkey"]


def todays_extras():
    """Ekstra sorguları gün sayısına göre döndürerek EXTRA_PER_RUN kadarını seç."""
    n = len(EXTRA_QUERIES)
    if EXTRA_PER_RUN >= n:
        return EXTRA_QUERIES
    day = today_sofia().toordinal()
    start = (day * EXTRA_PER_RUN) % n
    return [EXTRA_QUERIES[(start + i) % n] for i in range(EXTRA_PER_RUN)]


CONCURRENCY = int(os.environ.get("SERP_CONCURRENCY", "8"))   # saatlik limit 200.000; yavaş yanıtlar paralel beklensin


async def run_stage(session, label, queries, reported, found, **kw):
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(query):
        if budget_left() <= 0 or time_up() or TIMEOUT_STREAK >= 12:
            return query, None
        async with sem:
            print(f"Aranıyor ({label}): {query}")
            return query, await search_serpapi(session, query, **kw)

    outs = await asyncio.gather(*[one(q) for q in queries])
    for query, results in outs:
        if results is None:
            continue
        brand, keywords = detect_brand(query)
        process_results(results, brand, keywords, f"{query} [{label}]", reported, found)
    if budget_left() <= 0:
        print(f"Bütçe bitti ({SERP_CALLS}/{RUN_BUDGET})")


async def main():
    reported = load_reported()
    found    = []
    print(f"Bütçe: koşu başına {RUN_BUDGET} arama "
          f"({'BOOST' if BOOST_MODE else 'NORMAL'}, yenileme {RENEWAL_DATE}), "
          f"timeout {SERP_TIMEOUT}s, strict={SERP_STRICT}, süre sınırı {MAX_RUNTIME//60} dk")

    async with aiohttp.ClientSession() as session:
        # Öncelik: çekirdek -> mobil -> İstanbul -> ekstra -> ek şehirler -> Oxylabs
        await run_stage(session, "desktop", SEARCH_QUERIES, reported, found,
                        device="desktop", pages=CORE_PAGES)
        await flush(found, reported, "desktop")
        await run_stage(session, "mobile", MOBILE_QUERIES, reported, found,
                        device="mobile", pages=CORE_PAGES)
        await run_stage(session, "istanbul", ISTANBUL_QUERIES, reported, found,
                        device="desktop", location="Istanbul,Turkey", pages=CORE_PAGES)
        await flush(found, reported, "mobil+istanbul")

        extras = todays_extras()
        print(f"Ekstra sorgu: {len(extras)} / {len(EXTRA_QUERIES)}")
        await run_stage(session, "extra", extras, reported, found,
                        device="desktop", pages=EXTRA_PAGES, tbs="qdr:w")
        await flush(found, reported, "extra")
        if BOOST_MODE:
            await run_stage(session, "extra-mobile", extras, reported, found,
                            device="mobile", pages=2, tbs="qdr:w")
            await flush(found, reported, "extra-mobil")
            for loc in EXTRA_LOCATIONS:
                short = loc.split(",")[0].lower()
                await run_stage(session, f"{short}", ISTANBUL_QUERIES[:4], reported, found,
                                device="desktop", location=loc, pages=1)
            await flush(found, reported, "şehirler")

        # ── Oxylabs — gerçek Türkiye IP (SerpAPI kotasından bağımsız) ──
        for query in OXYLABS_QUERIES:
            if OXYLABS_AUTH_FAILED:
                print("Oxylabs 401 (kimlik doğrulama) — kalan sorgular atlandı, kullanıcı adı/şifreyi kontrol et")
                break
            print(f"Aranıyor (oxylabs-TR): {query}")
            results = await search_oxylabs(session, query)
            brand, keywords = detect_brand(query)
            process_results(results, brand, keywords, f"{query} [oxylabs]", reported, found)
            await asyncio.sleep(2)
        await flush(found, reported, "oxylabs")

    print(f"SerpAPI harcanan: {SERP_CALLS}/{RUN_BUDGET}, timeout serisi: {TIMEOUT_STREAK}")


if __name__ == "__main__":
    asyncio.run(main())
