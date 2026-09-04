import asyncio
import aiohttp
import socket
import concurrent.futures
import os
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
# Resmi güncel adres: 758turkbet.com
# ============================================================
TURKBET_WHITELIST = set([
    "turkbet.com",
    "726turkbet.com", "727turkbet.com",
    *[f"{num}turkbet.com" for num in range(488, 600)],
    *[f"{num}turkbet.com" for num in range(600, 700)],
    "700turkbet.com", "701turkbet.com", "702turkbet.com", "703turkbet.com", "704turkbet.com",
    "705turkbet.com", "706turkbet.com", "707turkbet.com", "708turkbet.com", "709turkbet.com",
    "710turkbet.com", "711turkbet.com", "712turkbet.com", "713turkbet.com", "714turkbet.com",
    "715turkbet.com", "716turkbet.com", "717turkbet.com", "718turkbet.com", "719turkbet.com",
    "720turkbet.com", "721turkbet.com", "722turkbet.com", "723turkbet.com", "724turkbet.com",
    "725turkbet.com", "727turkbet.com", "728turkbet.com", "729turkbet.com",
    "730turkbet.com", "731turkbet.com", "732turkbet.com", "733turkbet.com", "734turkbet.com",
    "735turkbet.com", "736turkbet.com", "737turkbet.com", "738turkbet.com", "739turkbet.com",
    "740turkbet.com", "741turkbet.com", "742turkbet.com", "743turkbet.com", "744turkbet.com",
    "745turkbet.com", "746turkbet.com", "747turkbet.com", "748turkbet.com", "749turkbet.com",
    "750turkbet.com", "751turkbet.com", "752turkbet.com", "753turkbet.com", "754turkbet.com",
    "755turkbet.com", "756turkbet.com", "757turkbet.com", "758turkbet.com", "759turkbet.com",
    "760turkbet.com", "761turkbet.com", "762turkbet.com", "763turkbet.com", "764turkbet.com",
    "765turkbet.com", "766turkbet.com", "767turkbet.com", "768turkbet.com", "769turkbet.com",
    "770turkbet.com", "771turkbet.com", "772turkbet.com", "773turkbet.com", "774turkbet.com",
    "775turkbet.com", "776turkbet.com", "777turkbet.com", "778turkbet.com", "779turkbet.com",
    "780turkbet.com", "781turkbet.com", "782turkbet.com", "783turkbet.com", "784turkbet.com",
    "785turkbet.com", "786turkbet.com", "787turkbet.com", "788turkbet.com", "789turkbet.com",
    "790turkbet.com", "791turkbet.com", "792turkbet.com", "793turkbet.com", "794turkbet.com",
    "795turkbet.com", "796turkbet.com", "797turkbet.com", "798turkbet.com", "799turkbet.com",
    "800turkbet.com", "801turkbet.com", "802turkbet.com", "803turkbet.com", "804turkbet.com",
    "805turkbet.com", "806turkbet.com", "807turkbet.com", "808turkbet.com", "809turkbet.com",
    "810turkbet.com", "811turkbet.com", "812turkbet.com", "813turkbet.com", "814turkbet.com",
    "815turkbet.com", "816turkbet.com", "817turkbet.com", "818turkbet.com", "819turkbet.com",
    "820turkbet.com", "821turkbet.com", "822turkbet.com", "823turkbet.com", "824turkbet.com",
    "825turkbet.com", "826turkbet.com", "827turkbet.com", "828turkbet.com", "829turkbet.com",
    "830turkbet.com", "831turkbet.com", "832turkbet.com", "833turkbet.com", "834turkbet.com",
    "835turkbet.com", "836turkbet.com", "837turkbet.com", "838turkbet.com", "839turkbet.com",
    "840turkbet.com", "841turkbet.com", "842turkbet.com", "843turkbet.com", "844turkbet.com",
    "845turkbet.com", "846turkbet.com", "847turkbet.com", "848turkbet.com", "849turkbet.com",
    "850turkbet.com", "851turkbet.com", "852turkbet.com", "853turkbet.com", "854turkbet.com",
    "855turkbet.com", "856turkbet.com", "857turkbet.com", "858turkbet.com", "859turkbet.com",
    "860turkbet.com", "861turkbet.com", "862turkbet.com", "863turkbet.com", "864turkbet.com",
    "865turkbet.com", "866turkbet.com", "867turkbet.com", "868turkbet.com", "869turkbet.com",
    "870turkbet.com", "871turkbet.com", "872turkbet.com", "873turkbet.com", "874turkbet.com",
    "875turkbet.com", "876turkbet.com", "877turkbet.com", "878turkbet.com", "879turkbet.com",
    "880turkbet.com", "881turkbet.com", "882turkbet.com", "883turkbet.com", "884turkbet.com",
    "885turkbet.com", "886turkbet.com", "887turkbet.com", "888turkbet.com", "889turkbet.com",
    "890turkbet.com",
])
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
    "yonleniyoramp.com", "googlecdnservice.net",
    "supetbetingirisadresim.vip", "turkbetgirisadresim.vip",
])
TURKBET_RANGE = range(891, 5001)
REPORTED_FILE = "turkbet_reported.json"
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
async def scan_domain(session, domain, dtype, whitelist, reported, found):
    if domain in whitelist or domain in reported:
        return
    dns_ok, ip = await check_dns_native(domain)
    if not dns_ok:
        return
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
async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            await session.post(url, json={
                "chat_id": chat_id.strip(),
                "text": message,
                "parse_mode": "Markdown"
            })
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
async def main():
    reported = load_reported()
    found = []
    domains_to_scan = []
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
    # 9. DİĞER ALT TLD'LER (vip/icu/net/org) — 700-2001 aralığı yeterli,
    # bu TLD'lerde şimdiye kadar somut fraud görülmediği için genişletilmedi.
    # NOT (3 Eyl 2026): .cam ve .live buradan ÇIKARILDI — artık kendi
    # bölümlerinde (10 ve 12) betsat_scanner.py/superbetin_scanner.py ile
    # tutarlı şekilde TAM 1-9999 aralığında taranıyorlar (bkz. aşağı).
    print("🌐 Turkbet alt TLD varyasyonları taranıyor (vip/icu/net/org)...")
    for num in range(700, 2001):
        for tld in ["vip", "icu", "net", "org"]:
            domains_to_scan.append((f"{num}turkbet.{tld}", f"TURKBET-{tld.upper()}", set()))
            domains_to_scan.append((f"turkbet{num}.{tld}", f"TURKBET-{tld.upper()}-TERS", set()))
    # ── 10. .CAM TLD-SWAP TARAMASI — GÜNCELLENDİ (3 Eyl 2026) ──
    # betsat_scanner.py / superbetin_scanner.py ile aynı mantığa
    # getirildi: sabit sayı listesi yerine TAM 1-9999 aralığı, her iki
    # yönde de (NUMturkbet.cam VE turkbetNUM.cam — turkbet761.com'un
    # kendisi zaten ters-sıra bir typosquat olarak bulundu, format
    # kararsız). Eski CAM_DEPOSIT_CHECK_NUMBERS = [758, 757, 724] listesi
    # kaldırıldı — hem stale'di (resmi artık 761/760) hem de deposit-
    # subdomain derin taraması (yatirim/tr/m/payment/odeme) gereksizdi,
    # bulunan her root zaten elle inceleniyor.
    print("📷 Turkbet .cam TLD-swap varyasyonları taranıyor (1-9999 tam aralık, iki yön)...")
    for num in range(1, 10000):
        domains_to_scan.append((f"{num}turkbet.cam", "CAM-TLD-SWAP", set()))
        domains_to_scan.append((f"turkbet{num}.cam", "CAM-TLD-SWAP-TERS", set()))
    # CAM ÖNEK TARAMASI — YENİ (3 Eyl 2026): .live tarafında zaten
    # m-/tr-/www-/vip- (tireli ve tiresiz) önek taraması vardı, .cam
    # tarafında hiç yoktu — asimetri kapatıldı (betsat/superbetin'de
    # yapılan aynı düzeltme).
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
    # Eskiden bare .live taraması sadece 9. bölümdeki alt-TLD döngüsünde
    # 700-2001 aralığındaydı — artık .cam ile tutarlı TAM 1-9999,
    # her iki yönde de.
    print("🟢 Turkbet .live TLD-swap varyasyonları taranıyor (1-9999 tam aralık, iki yön)...")
    for num in range(1, 10000):
        domains_to_scan.append((f"{num}turkbet.live", "LIVE-TLD-SWAP", set()))
        domains_to_scan.append((f"turkbet{num}.live", "LIVE-TLD-SWAP-TERS", set()))
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
    # NOT (3 Eyl 2026): deposit-subdomain derin taraması (LIVE_DEPOSIT_
    # CHECK_NUMBERS) burada da kaldırıldı — betsat/superbetin'deki aynı
    # gerekçe: bulunan her root zaten elle inceleniyor, sabit sayı listesi
    # sürekli eskiyip stale kalıyordu.
    # HOMOGLYPH (RAKAM↔HARF) — .com/.cam/.live üçünde, iki yönde de.
    # bkz. generate_homoglyph_number_variants() tanımındaki not.
    print("👁️ Homoglyph (1→l, 0→o) varyasyonları üretiliyor (.com/.cam/.live, iki yön)...")
    for num in range(700, 2001):
        for variant_num in generate_homoglyph_number_variants(num):
            domains_to_scan.append((f"{variant_num}turkbet.com", "TYPO-HOMOGLYPH", set()))
            domains_to_scan.append((f"turkbet{variant_num}.com", "TYPO-HOMOGLYPH-TERS", set()))
            domains_to_scan.append((f"{variant_num}turkbet.cam", "CAM-TLD-SWAP-HOMOGLYPH", set()))
            domains_to_scan.append((f"turkbet{variant_num}.cam", "CAM-TLD-SWAP-HOMOGLYPH-TERS", set()))
            domains_to_scan.append((f"{variant_num}turkbet.live", "LIVE-TLD-SWAP-HOMOGLYPH", set()))
            domains_to_scan.append((f"turkbet{variant_num}.live", "LIVE-TLD-SWAP-HOMOGLYPH-TERS", set()))
    print(f"🚀 Toplam {len(domains_to_scan)} Turkbet domain taranacak...")
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=500)) as session:
        semaphore = asyncio.Semaphore(500)
        async def bounded_scan(d, t, w):
            async with semaphore:
                await scan_domain(session, d, t, w, reported, found)
        await asyncio.gather(*[bounded_scan(d, t, w) for d, t, w in domains_to_scan])
    save_reported(reported)
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    repo = os.environ.get("GITHUB_REPOSITORY", "smhozt/poligon-domain-scanner")
    if found:
        msg = (
            f"🚨 *[TURKBET ALARM] Aktif Sahte Domain!*\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain — Bulunan: `{len(found)}`\n"
        )
        for item in found:
            icon = (
                "👁️" if "HOMOGLYPH" in item["type"] else
                "🟢" if "LIVE" in item["type"] else
                "📷" if "CAM" in item["type"] else
                "5️⃣" if item["type"] == "TERS-5HANE" else
                "🌐" if "CO-" in item["type"] or "TURKBET-" in item["type"] else
                "🎭" if item["type"] == "IDN-SAHTE" else
                "🔗" if "PREFIX" in item["type"] else
                "🔄" if "TERS" in item["type"] else
                "🔥"
            )
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        save_to_google_sheets(found)
        await send_telegram(msg)
    else:
        msg = (
            f"✅ *[TURKBET TARAMA] Temiz* — {now}\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain\n"
            f"Sahte domain bulunamadı."
        )
        await send_telegram(msg)
        print("Temiz.")
if __name__ == "__main__":
    asyncio.run(main())
