import asyncio
import aiohttp
import socket
import concurrent.futures
import os
import sys
import json
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials
TZ_SOFIA = timezone(timedelta(hours=3))
executor = concurrent.futures.ThreadPoolExecutor(max_workers=500)
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
GCP_CREDENTIALS = os.environ.get("GCP_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
# ============================================================
# TURKBET WHİTELİST — Bizim domainlerimiz
# NOT: Turkbet'in domain formatı [num]turkbet.com (sayı önde!)
# Resmi güncel adres: 777turkbet.com
# SADELEŞTİRİLDİ 12 Eki 2026: eski dosyadaki üç ayrı liste (726/727,
# range(488,600), range(600,700) ve 700-890 elle yazılmış girdiler)
# birleşince tam olarak 488-890 aralığıydı; aynı küme tek range ile
# yazıldı.
# DİKKAT 12 Eki 2026: 876turkbet.com bu aralığın içinde ama bizim
# DEĞİL — aktif phishing (login.php + deposit sayfaları, Cloudflare
# raporları 10 Eki). Beyaz listedeki 778-890 arası numaraların hangileri
# gerçekten bizim, registrar listesiyle doğrulanmalı (Betsat'ta
# 8 Eyl 2026'da yapılan iş). Doğrulanana kadar GRUP C'deki WL-CHECK
# bu numaraları beyaz liste OLMADAN tarar.
# ============================================================
TURKBET_WHITELIST = set([
    "turkbet.com",
    *[f"{num}turkbet.com" for num in range(488, 891)],
])
TURKBET_WHITELIST.discard("876turkbet.com")
# 12 Eki 2026 — Semih doğruladı: 878turkbet.com de sahtecinin (bizim değil).
TURKBET_WHITELIST.discard("878turkbet.com")
TURKBET_WHITELIST.update([
    "turkbet.cam", "soloturkbet.com", "asyaturkbet.com", "turkbetturkiye.com",
    "turkbet2026.net", "turkbetcanli.com", "turkbet.es", "turkbet2026.com",
    "turkbetgir.com", "turkbet.info", "turkbetborsa.com", "turkbetsitesi.com",
    "turkbetspor.com", "turkbetbayilik.com", "turkbetik.com", "turkbetsson.com",
    "hititturkbet.com", "turkbetyeniadres.com", "turkbet-girisi.com",
    "turkbetgirisin.co", "turkbetadresi.me", "turkbet.cx", "turkbetyeni.site",
    "turkbetadresim.com", "turkbettr.com", "turkbetadres.io", "turkbetguncel.com",
    "turkbetgunceladresi.com", "turkbetgirisi.co", "turkbetgo.com", "turk-bets.com",
    "trturkbet.com", "turkbetadresim.co", "turkbetgiris.pro", "turkgirisim.com",
    "yonleniyoramp.com", "googlecdnservice.net", "turkiyebet.net",
    "supetbetingirisadresim.vip", "turkbetgirisadresim.vip",
])
# YENİ 8 Eki 2026 — Semih'in kendi Betsat güncel giriş/rehber sitesi.
TURKBET_WHITELIST.update([
    "bahiskazani.com",
])
TURKBET_RANGE = range(891, 5001)
# ============================================================
# ÜÇE BÖLME (12 Eki 2026) — betsat_scanner ile aynı yöntem.
# PART "a"/"b"/"c" argümanıyla seçilir; argümansız çağrı ("all") TÜMÜNÜ tarar.
# Her PART kendi reported dosyasını kullanır (git commit çakışması olmasın).
#   a : .com sayılar (standart, tarih, typo, ters, 5 haneli, IDN, önekler) + .co + vip/icu/net/org
#   b : .cam (tam 1-9999 + önekler) / .live tam 1-9999 / homoglyph
#   c : YENİ — 5001-9999 .com, 778-890 WL-CHECK, sayı x 16 diğer TLD, 5 haneli 25001-39999
#       + .live önekli varyasyonlar (yük dengesi için buraya taşındı)
# ============================================================
PART = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
if PART not in ("a", "b", "c", "all"):
    PART = "all"
REPORTED_FILE = "turkbet_reported.json" if PART == "all" else f"turkbet_reported_{PART}.json"
def load_reported():
    try:
        with open(REPORTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()
def save_reported(reported):
    with open(REPORTED_FILE, "w") as f:
        json.dump(list(reported), f)
def save_to_google_sheets(found_items):
    if not GCP_CREDENTIALS or not SPREADSHEET_ID:
        return
    try:
        credentials_dict = json.loads(GCP_CREDENTIALS)
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows_to_add = []
        current_time = datetime.now(TZ_SOFIA).strftime("%Y-%m-%d %H:%M:%S")
        for item in found_items:
            row = [current_time, item['domain'], str(item['status']), item['ip'] if item['ip'] else "Bulunamadi"]
            rows_to_add.append(row)
        if rows_to_add:
            sheet.append_rows(rows_to_add)
            print(f"✅ {len(rows_to_add)} domain Google E-Tablolara kaydedildi!")
    except Exception as e:
        print(f"Sheets hatasi: {e}")
async def check_dns_native(domain, retries=2):
    # v2 — 31 Tem 2026: retry eklendi (betsat_scanner.py ile aynı fix —
    # bkz. betsat2610.com vakası). Tek deneme geçici DNS hatalarında
    # domainleri sessizce kaçırıyordu.
    loop = asyncio.get_running_loop()
    for attempt in range(retries):
        try:
            ip = await loop.run_in_executor(executor, socket.gethostbyname, domain)
            return True, ip
        except Exception:
            if attempt < retries - 1:
                await asyncio.sleep(0.3)
    return False, ""
# YENİ 12 Eki 2026 — WL-CHECK ilk koşusunda 51 domain çıktı; 49'u 825-873 arası
# ardışık blok ve hepsi 162.255.119.x / 192.64.119.x (Namecheap park/yönlendirme
# aralığı) IP'sinde = bizim toplu kaydımız. Bu IP'lerdeki WL-CHECK sonuçları artık
# sessiz geçilir. DİKKAT: "reported" hafızasına EKLENMEZ ve hafızadaki eski kayıt
# yok sayılır; yani bu domainlerden biri sonradan başka IP'ye (hijack/phishing)
# dönerse yine yakalanır. Park dışı IP'de alarm bir kez (domain@IP-önek) gider.
NAMECHEAP_PARK_PREFIXES = ("162.255.119.", "192.64.119.")
async def scan_domain(session, domain, dtype, whitelist, reported, found):
    if domain in whitelist:
        return
    if dtype != "WL-CHECK" and domain in reported:
        return
    dns_ok, ip = await check_dns_native(domain)
    if not dns_ok:
        return
    if dtype == "WL-CHECK":
        if ip.startswith(NAMECHEAP_PARK_PREFIXES):
            return
        _wl_key = f"{domain}@{'.'.join(ip.split('.')[:2])}"
        if _wl_key in reported:
            return
        reported.add(_wl_key)
    http_ok, code = False, 0
    try:
        async with session.get(f"http://{domain}", timeout=5, allow_redirects=True) as resp:
            if resp.status in [200, 301, 302, 403]:
                http_ok = True
                code = resp.status
    except:
        pass
    found.append({
        "domain": domain,
        "type": dtype,
        "status": code if http_ok else f"DNS:{ip}",
        "ip": ip,
        "detected_by": "HTTP" if http_ok else "DNS"
    })
    reported.add(domain)
    print(f"[FOUND] {domain} ({ip})")
# ============================================================
# DÜZELTİLDİ 12 Eki 2026 — Telegram mesaj limiti 4096 karakter.
# Çok domain bulununca tek mesaj hata dönüyor, script de durumu
# kontrol etmediği için alarm sessizce kayboluyordu (üstelik
# save_reported Telegram'dan ÖNCE çalışıyordu). Artık 3500
# karakterlik parçalara bölünür, hata yazdırılır ve save_reported
# Telegram'dan SONRA çağrılır.
# ============================================================
async def send_telegram(message):
    chunks, cur = [], ""
    for line in message.split("\n"):
        if len(cur) + len(line) + 1 > 3500:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            for chunk in chunks:
                async with session.post(url, json={"chat_id": chat_id.strip(), "text": chunk, "parse_mode": "Markdown"}) as r:
                    if r.status != 200:
                        print("Telegram hata:", r.status, await r.text())
                await asyncio.sleep(0.5)
# ============================================================
# HOMOGLYPH (RAKAM↔HARF) TYPOSQUAT ÜRETİCİ — YENİ (3 Eyl 2026)
# superbetin2l00.com (rakam "1" → görsel olarak neredeyse ayırt
# edilemeyen küçük harf "l") canlı, aktif bir credential-harvesting
# phishing sitesi olarak bulundu — resmi domain'in birebir homoglyph
# typosquat'ı. Aynı üretici betsat_scanner.py ve superbetin_scanner.py'ye
# de eklendi. Sayının her "1" veya "0" hanesini TEK TEK (bir seferde
# bir hane) değiştirip varyasyon üretir: 761 → 76l, 761 → l61 (ayrı
# varyasyonlar).
# ============================================================
def generate_homoglyph_number_variants(num):
    s = str(num)
    swap_map = {"1": "l", "0": "o"}
    variants = []
    for i, ch in enumerate(s):
        if ch in swap_map:
            variant = s[:i] + swap_map[ch] + s[i + 1:]
            variants.append(variant)
    return list(dict.fromkeys(variants))
# Sayı x diğer TLD taraması için (.cam/.live zaten 1-9999 tam taranıyor)
# co/vip/icu/net/org GRUP A'da zaten 700-2000 taranıyor; çift alarm olmasın diye burada yok.
OTHER_TLDS = ["top", "club", "online", "site", "fun", "xyz", "info", "cfd", "bet", "pro", "app"]
async def main():
    reported = load_reported()
    found = []
    domains_to_scan = []
    # ── GRUP A ────────────────────────────────────────────────
    if PART in ("a", "all"):
        # 1. STANDART TURKBET SAYILARI
        for num in list(TURKBET_RANGE):
            domains_to_scan.append((f"{num}turkbet.com", "YENI", TURKBET_WHITELIST))
        # 2. TARİH FORMATI
        for num in range(100, 1000):
            domains_to_scan.append((f"{num:04d}turkbet.com", "TARIH-FORMAT", set()))
            domains_to_scan.append((f"turkbet{num:04d}.com", "TARIH-TERS", set()))
        # 3. TYPO VARYASYONLARI
        for num in range(700, 2001):
            domains_to_scan.append((f"turkbet{num}.com", "TYPO-TERS", set()))
            domains_to_scan.append((f"{num}trkbet.com", "TYPO-U-EKSIK", set()))
            domains_to_scan.append((f"{num}turkbetm.com", "TYPO-M", set()))
            domains_to_scan.append((f"m{num}turkbet.com", "TYPO-M-ON", set()))
        # 4. TERS PATTERN 4 HANELİ
        print("🔄 4 haneli ters pattern üretiliyor...")
        for num in range(700, 2001):
            domains_to_scan.append((f"{num}turkbet.com", "TERS-PATTERN", TURKBET_WHITELIST))
        # 5. TERS PATTERN 5 HANELİ
        print("5️⃣ 5 haneli ters pattern üretiliyor...")
        for num in range(10000, 25001):
            domains_to_scan.append((f"{num}turkbet.com", "TERS-5HANE", set()))
        # 6. IDN SAHTE HARF
        print("🧬 Sahte harfli (IDN) varyasyonlar üretiliyor...")
        for num in range(700, 2001):
            for variant in [f"{num}türkbet.com", f"{num}turkbét.com"]:
                try:
                    puny = variant.encode("idna").decode("utf-8")
                    domains_to_scan.append((puny, "IDN-SAHTE", set()))
                except:
                    pass
        # 7. TİRELİ ÖNEKLER
        print("🔗 Tireli önek varyasyonları üretiliyor...")
        PREFIXES = ["m-", "tr-", "www-", "vip-", "n-"]
        for num in range(700, 2001):
            for prefix in PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.com", "PREFIX-PATTERN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.com", "PREFIX-PATTERN-TERS", set()))
        # 7b. TİRESİZ ÖNEKLER (v2 — 05 Ağu 2026) — mbetsat1610.com (tiresiz,
        # bitişik) gerçek, aktif bir phishing domain olarak bulundu ama
        # yukarıdaki döngü sadece tireli "m-..." üretiyordu, bu kör
        # noktaydı. Turkbet için de kapatılıyor (m749turkbet.com,
        # mturkbet749.com gibi).
        print("🔗 Tiresiz önek varyasyonları üretiliyor...")
        NOHYPHEN_PREFIXES = ["m", "tr", "www", "vip", "n"]
        for num in range(700, 2001):
            for prefix in NOHYPHEN_PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.com", "PREFIX-NOHYPHEN-PATTERN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.com", "PREFIX-NOHYPHEN-PATTERN-TERS", set()))
        # 8. .CO TLD
        print("🌐 Turkbet .co TLD varyasyonları taranıyor...")
        for num in range(700, 2001):
            domains_to_scan.append((f"{num}turkbet.co", "CO-TYPO", set()))
            domains_to_scan.append((f"turkbet{num}.co", "CO-TERS", set()))
        # 9. DİĞER ALT TLD'LER (vip/icu/net/org) — 700-2001 aralığı.
        # NOT (3 Eyl 2026): .cam ve .live buradan ÇIKARILDI — artık kendi
        # bölümlerinde (10 ve 11) TAM 1-9999 aralığında taranıyorlar.
        # Daha fazla TLD (top/club/online/site/info/fun...) GRUP C'de.
        print("🌐 Turkbet alt TLD varyasyonları taranıyor (vip/icu/net/org)...")
        for num in range(700, 2001):
            for tld in ["vip", "icu", "net", "org"]:
                domains_to_scan.append((f"{num}turkbet.{tld}", f"TURKBET-{tld.upper()}", set()))
                domains_to_scan.append((f"turkbet{num}.{tld}", f"TURKBET-{tld.upper()}-TERS", set()))
    # ── GRUP B ────────────────────────────────────────────────
    if PART in ("b", "all"):
        # ── 10. .CAM TLD-SWAP TARAMASI — GÜNCELLENDİ (3 Eyl 2026) ──
        # betsat_scanner.py / superbetin_scanner.py ile aynı mantık:
        # TAM 1-9999 aralığı, her iki yönde de (NUMturkbet.cam VE
        # turkbetNUM.cam).
        print("📷 Turkbet .cam TLD-swap varyasyonları taranıyor (1-9999 tam aralık, iki yön)...")
        for num in range(1, 10000):
            domains_to_scan.append((f"{num}turkbet.cam", "CAM-TLD-SWAP", set()))
            domains_to_scan.append((f"turkbet{num}.cam", "CAM-TLD-SWAP-TERS", set()))
        # CAM ÖNEK TARAMASI — YENİ (3 Eyl 2026)
        print("🔗 Turkbet .cam önek (m-, tr- vb. + tiresiz) varyasyonları taranıyor...")
        CAM_PREFIXES = ["m-", "tr-", "www-", "vip-", "n-"]
        CAM_NOHYPHEN_PREFIXES = ["m", "tr", "www", "vip", "n"]
        for num in range(700, 2001):
            for prefix in CAM_PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.cam", "CAM-PREFIX-PATTERN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.cam", "CAM-PREFIX-PATTERN-TERS", set()))
            for prefix in CAM_NOHYPHEN_PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.cam", "CAM-PREFIX-NOHYPHEN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.cam", "CAM-PREFIX-NOHYPHEN-TERS", set()))
        # ── 11. .LIVE TLD-SWAP TARAMASI — GÜNCELLENDİ (3 Eyl 2026) ──
        print("🟢 Turkbet .live TLD-swap varyasyonları taranıyor (1-9999 tam aralık, iki yön)...")
        for num in range(1, 10000):
            domains_to_scan.append((f"{num}turkbet.live", "LIVE-TLD-SWAP", set()))
            domains_to_scan.append((f"turkbet{num}.live", "LIVE-TLD-SWAP-TERS", set()))
        # NOT (3 Eyl 2026): deposit-subdomain derin taraması (LIVE_DEPOSIT_
        # CHECK_NUMBERS) kaldırıldı — bulunan her root zaten elle inceleniyor.
        # HOMOGLYPH (RAKAM↔HARF) — .com/.cam/.live üçünde, iki yönde de.
        print("👁️ Homoglyph (1→l, 0→o) varyasyonları üretiliyor (.com/.cam/.live, iki yön)...")
        for num in range(700, 2001):
            for variant_num in generate_homoglyph_number_variants(num):
                domains_to_scan.append((f"{variant_num}turkbet.com", "TYPO-HOMOGLYPH", set()))
                domains_to_scan.append((f"turkbet{variant_num}.com", "TYPO-HOMOGLYPH-TERS", set()))
                domains_to_scan.append((f"{variant_num}turkbet.cam", "CAM-TLD-SWAP-HOMOGLYPH", set()))
                domains_to_scan.append((f"turkbet{variant_num}.cam", "CAM-TLD-SWAP-HOMOGLYPH-TERS", set()))
                domains_to_scan.append((f"{variant_num}turkbet.live", "LIVE-TLD-SWAP-HOMOGLYPH", set()))
                domains_to_scan.append((f"turkbet{variant_num}.live", "LIVE-TLD-SWAP-HOMOGLYPH-TERS", set()))
    # ── GRUP C (YENİ 12 Eki 2026) ─────────────────────────────
    # Anahtar kelimeli domainler (turkbet-giris.com, turkbetgir.net vb.) VIP scanner'ın işi.
    if PART in ("c", "all"):
        # 1. 4 haneli 5001-9999 .com — eski aralık 5000'de bitiyordu.
        # Resmi 777'ye tek rakam eklenince 7777, 5777, 7177... oluşuyor ve
        # çoğu bu aralığa düşüyordu.
        print("4️⃣ 4 haneli 5001-9999 .com taranıyor...")
        for num in range(5001, 10000):
            domains_to_scan.append((f"{num}turkbet.com", "FOUR-DIGIT-HIGH", TURKBET_WHITELIST))
        # 2. WL-CHECK: 778-890 aralığı beyaz listede ama hepsi bizim değil
        # (876turkbet.com phishing çıktı). Beyaz liste OLMADAN taranır; ilk
        # çalıştırmayı SEED=1 ile yapıp Sheets'teki listeyi registrar listesiyle karşılaştır.
        print("🧪 778-890 WL-CHECK (beyaz listesiz) taranıyor...")
        for num in range(778, 891):
            domains_to_scan.append((f"{num}turkbet.com", "WL-CHECK", set()))
        # 3. Sayı x diğer TLD — .vip .top .org .net .club ... (iki yön).
        print("🌍 Turkbet 700-1099 x diğer TLD taranıyor (iki yön)...")
        for num in range(700, 1100):
            for tld in OTHER_TLDS:
                domains_to_scan.append((f"{num}turkbet.{tld}", "NUMERIC-TLD-SWAP", set()))
                domains_to_scan.append((f"turkbet{num}.{tld}", "NUMERIC-TLD-SWAP-TERS", set()))
        # 4. 5 haneli genişletme: 25001-39999.
        print("5️⃣ 5 haneli 25001-39999 taranıyor...")
        for num in range(25001, 40000):
            domains_to_scan.append((f"{num}turkbet.com", "TERS-5HANE-HIGH", set()))
        # ── 12. .LIVE ÖNEKLİ (PREFIX) VARYASYONLAR (23 Ağu 2026'dan beri var) ──
        print("🟢 Turkbet .live önekli varyasyonları üretiliyor...")
        LIVE_PREFIXES = ["m-", "tr-", "www-", "vip-", "n-"]
        LIVE_NOHYPHEN_PREFIXES = ["m", "tr", "www", "vip", "n"]
        for num in range(700, 2001):
            for prefix in LIVE_PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.live", "LIVE-PREFIX-PATTERN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.live", "LIVE-PREFIX-PATTERN-TERS", set()))
            for prefix in LIVE_NOHYPHEN_PREFIXES:
                domains_to_scan.append((f"{prefix}{num}turkbet.live", "LIVE-PREFIX-NOHYPHEN", set()))
                domains_to_scan.append((f"{prefix}turkbet{num}.live", "LIVE-PREFIX-NOHYPHEN-TERS", set()))
    # Tekrar edenleri at (paralel taramada aynı domain iki kez bulunmasın).
    # Sıra korunur: aynı domain hem YENI (beyaz listeli) hem WL-CHECK (beyaz listesiz)
    # olarak üretilirse, WL-CHECK sürümü korunur.
    _best = {}
    for d, t, w in domains_to_scan:
        if d not in _best or (_best[d][2] and not w):
            _best[d] = (d, t, w)
    domains_to_scan = list(_best.values())
    print(f"🚀 [PART {PART.upper()}] Toplam {len(domains_to_scan)} Turkbet domain taranacak...")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=500)) as session:
        semaphore = asyncio.Semaphore(500)
        async def bounded_scan(d, t, w):
            async with semaphore:
                await scan_domain(session, d, t, w, reported, found)
        await asyncio.gather(*[bounded_scan(d, t, w) for d, t, w in domains_to_scan])
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    repo = os.environ.get("GITHUB_REPOSITORY", "smhozt/poligon-domain-scanner")
    part_label = f" [{PART.upper()}]" if PART != "all" else ""
    if found:
        save_to_google_sheets(found)
        # SEED modu: ilk çalıştırmada mevcut/park edilmiş domainleri Sheets'e yaz,
        # Telegram'ı atla, hafızaya kaydet. Kullanım: SEED=1 python turkbet_scanner.py c
        if os.environ.get("SEED") == "1":
            save_reported(reported)
            print(f"SEED: {len(found)} domain Sheets'e yazildi, Telegram atlandi.")
            return
        msg = (
            f"🚨 *[TURKBET ALARM]{part_label} Aktif Sahte Domain!*\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain — Bulunan: `{len(found)}`\n"
        )
        for item in found:
            icon = (
                "👁️" if "HOMOGLYPH" in item["type"] else
                "🧪" if item["type"] == "WL-CHECK" else
                "🌍" if "NUMERIC-TLD-SWAP" in item["type"] else
                "🟢" if "LIVE" in item["type"] else
                "📷" if "CAM" in item["type"] else
                "5️⃣" if "5HANE" in item["type"] else
                "4️⃣" if item["type"] == "FOUR-DIGIT-HIGH" else
                "🌐" if "CO-" in item["type"] or "TURKBET-" in item["type"] else
                "🎭" if item["type"] == "IDN-SAHTE" else
                "🔗" if "PREFIX" in item["type"] else
                "🔄" if "TERS" in item["type"] else
                "🔥"
            )
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        await send_telegram(msg)
        save_reported(reported)
    else:
        msg = (
            f"✅ *[TURKBET TARAMA]{part_label} Temiz* — {now}\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain\n"
            f"Sahte domain bulunamadı."
        )
        await send_telegram(msg)
        save_reported(reported)
        print("Temiz.")
if __name__ == "__main__":
    asyncio.run(main())
