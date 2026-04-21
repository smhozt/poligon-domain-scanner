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

# Native DNS için thread pool
executor = concurrent.futures.ThreadPoolExecutor(max_workers=500)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

GCP_CREDENTIALS = os.environ.get("GCP_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# ============================================================
# TURKBET WHİTELİST — Bizim domainlerimiz
# NOT: Turkbet'in domain formatı [num]turkbet.com (sayı önde!)
# ============================================================
TURKBET_WHITELIST = set([
    "turkbet.com",
    "709turkbet.com","710turkbet.com","711turkbet.com","712turkbet.com",
    "713turkbet.com","714turkbet.com","715turkbet.com","716turkbet.com",
    "717turkbet.com","718turkbet.com","719turkbet.com","720turkbet.com",
    "721turkbet.com","722turkbet.com","723turkbet.com","724turkbet.com",
    "725turkbet.com","726turkbet.com","727turkbet.com","728turkbet.com",
    "729turkbet.com","730turkbet.com","731turkbet.com","732turkbet.com",
    "733turkbet.com","734turkbet.com","735turkbet.com","736turkbet.com",
    "737turkbet.com","738turkbet.com","739turkbet.com","740turkbet.com",
    "741turkbet.com","742turkbet.com","743turkbet.com","744turkbet.com",
    "745turkbet.com","746turkbet.com","747turkbet.com","748turkbet.com",
    "749turkbet.com","750turkbet.com","751turkbet.com","752turkbet.com",
    "753turkbet.com","754turkbet.com","755turkbet.com","756turkbet.com",
    "757turkbet.com","758turkbet.com","759turkbet.com","760turkbet.com",
    "761turkbet.com","762turkbet.com","763turkbet.com","764turkbet.com",
    "765turkbet.com","766turkbet.com","767turkbet.com","768turkbet.com",
    "769turkbet.com","770turkbet.com","771turkbet.com","772turkbet.com",
    "773turkbet.com","774turkbet.com","775turkbet.com","776turkbet.com",
    "777turkbet.com","778turkbet.com","779turkbet.com","780turkbet.com",
    "781turkbet.com","782turkbet.com","783turkbet.com","784turkbet.com",
    "785turkbet.com","786turkbet.com","787turkbet.com","788turkbet.com",
    "789turkbet.com","790turkbet.com","791turkbet.com","792turkbet.com",
    "793turkbet.com","794turkbet.com","795turkbet.com","796turkbet.com",
    "797turkbet.com","798turkbet.com","799turkbet.com","800turkbet.com",
    "801turkbet.com","802turkbet.com","803turkbet.com","804turkbet.com",
    "805turkbet.com","806turkbet.com","807turkbet.com","808turkbet.com",
    "809turkbet.com","810turkbet.com","811turkbet.com","812turkbet.com",
    "813turkbet.com","814turkbet.com","815turkbet.com","816turkbet.com",
    "817turkbet.com","818turkbet.com","819turkbet.com","820turkbet.com",
    "821turkbet.com","822turkbet.com","823turkbet.com","824turkbet.com",
    "825turkbet.com","826turkbet.com","827turkbet.com","828turkbet.com",
    "829turkbet.com","830turkbet.com","831turkbet.com","832turkbet.com",
    "833turkbet.com","834turkbet.com","835turkbet.com","836turkbet.com",
    "837turkbet.com","838turkbet.com","839turkbet.com","840turkbet.com",
    "841turkbet.com","842turkbet.com","843turkbet.com","844turkbet.com",
    "845turkbet.com","846turkbet.com","847turkbet.com","848turkbet.com",
    "849turkbet.com","850turkbet.com","851turkbet.com","852turkbet.com",
    "853turkbet.com","854turkbet.com","855turkbet.com","856turkbet.com",
    "857turkbet.com","858turkbet.com","859turkbet.com","860turkbet.com",
    "861turkbet.com","862turkbet.com","863turkbet.com","864turkbet.com",
    "865turkbet.com","866turkbet.com","867turkbet.com","868turkbet.com",
    "869turkbet.com","870turkbet.com","871turkbet.com","872turkbet.com",
    "873turkbet.com",
])

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
        print("Google Sheets kimlik bilgileri eksik.")
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

async def check_dns_native(domain):
    """Native DNS — OS üzerinden, Google API beklemiyor"""
    loop = asyncio.get_running_loop()
    try:
        ip = await loop.run_in_executor(executor, socket.gethostbyname, domain)
        return True, ip
    except:
        return False, ""

async def check_http(session, domain):
    try:
        async with session.get(f"https://{domain}", timeout=5, allow_redirects=True) as resp:
            if resp.status in [200, 301, 302, 403]:
                return True, resp.status
    except: pass
    return False, 0

async def scan_domain(session, domain, dtype, whitelist, reported, found):
    if domain in whitelist or domain in reported: return
    dns_ok, ip = await check_dns_native(domain)
    if not dns_ok:
        return
    http_ok, code = await check_http(session, domain)
    if dns_ok or http_ok:
        found.append({
            "domain": domain,
            "type": dtype,
            "status": code if http_ok else f"DNS:{ip}",
            "ip": ip,
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

async def main():
    reported = load_reported()
    found = []
    domains_to_scan = []

    # 1. ANA PATTERN: [num]turkbet.com — yeni domainler (874+)
    for num in range(874, 2001):
        domains_to_scan.append((f"{num}turkbet.com", "YENI", TURKBET_WHITELIST))

    # 2. TERS PATTERN: turkbet[num].com (bizimki sayı önde, sahte sayı arkada olabilir)
    for num in range(700, 2001):
        domains_to_scan.append((f"turkbet{num}.com", "TERS-PATTERN", set()))

    # 3. TYPO: turcbet (k→c)
    for num in range(700, 2001):
        domains_to_scan.append((f"{num}turcbet.com", "TYPO-K-C", set()))
        domains_to_scan.append((f"turcbet{num}.com", "TYPO-K-C", set()))

    # 4. TYPO: turkbett (t fazla)
    for num in range(700, 2001):
        domains_to_scan.append((f"{num}turkbett.com", "TYPO-T-FAZLA", set()))

    # 5. TYPO: turkkbet (k fazla)
    for num in range(700, 2001):
        domains_to_scan.append((f"{num}turkkbet.com", "TYPO-K-FAZLA", set()))

    # 6. TYPO: trkbet (u eksik)
    for num in range(700, 2001):
        domains_to_scan.append((f"{num}trkbet.com", "TYPO-U-EKSIK", set()))
        
    # 7. YENİ TİRELİ ÖNEKLER (m-, tr-, www-, vip-) — m-710turkbet.com vb. yakalar!
    print("🔗 Tireli önek (m-, tr- vb.) varyasyonları üretiliyor...")
    PREFIXES = ["m-", "tr-", "www-", "vip-"]
    for num in range(700, 2001):
        for prefix in PREFIXES:
            domains_to_scan.append((f"{prefix}{num}turkbet.com", "PREFIX-PATTERN", set()))
            domains_to_scan.append((f"{prefix}turkbet{num}.com", "PREFIX-PATTERN", set()))

    print(f"Toplam {len(domains_to_scan)} domain taranacak...")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=50)) as session:
        semaphore = asyncio.Semaphore(50)
        async def bounded_scan(d, t, w):
            async with semaphore:
                await scan_domain(session, d, t, w, reported, found)
        await asyncio.gather(*[bounded_scan(d, t, w) for d, t, w in domains_to_scan])

    save_reported(reported)

    if found:
        msg = "🚨 *[TURKBET ALARM] Aktif Sahte Domain!*\n"
        for item in found:
            icon = "🔗" if item["type"] == "PREFIX-PATTERN" else "🔄" if item["type"] == "TERS-PATTERN" else "🔥"
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        save_to_google_sheets(found)
        await send_telegram(msg)
    else:
        print("Temiz.")

if __name__ == "__main__":
    asyncio.run(main())
