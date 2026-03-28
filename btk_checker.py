import os
import json
import asyncio
import aiohttp
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
BTK_API = "https://keyiflerolsun.dev/api/v1/btk?url="

DOMAINS = [
    "superbetin1815.com",
    "betsat1541.com",
    "711turkbet.com",
]

STATUS_FILE = "btk_status.json"

def load_status():
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)

async def check_domain(session, domain):
    url = BTK_API + domain
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as resp:
            code = resp.status
            if code == 203:
                return {"domain": domain, "status": "BLOCKED", "detail": "BTK tarafindan engellendi (HTTP 203)"}
            if code == 429:
                await asyncio.sleep(5)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as retry:
                    if retry.status == 203:
                        return {"domain": domain, "status": "BLOCKED", "detail": "BTK tarafindan engellendi (HTTP 203)"}
                    if retry.status == 200:
                        data = await retry.json(content_type=None)
                        return {"domain": domain, "status": "BLOCKED" if data.get("blocked") else "ACCESSIBLE", "detail": data.get("data", "")}
                return {"domain": domain, "status": "RATE_LIMIT", "detail": "Rate limit"}
            if code == 200:
                data = await resp.json(content_type=None)
                return {"domain": domain, "status": "BLOCKED" if data.get("blocked") else "ACCESSIBLE", "detail": data.get("data", "")}
            return {"domain": domain, "status": "API_ERROR", "detail": f"HTTP {code}"}
    except Exception as e:
        return {"domain": domain, "status": "API_ERROR", "detail": str(e)}

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            chat_id = chat_id.strip()
            if not chat_id:
                continue
            await session.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            )

async def main():
    prev_status = load_status()
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    async with aiohttp.ClientSession() as session:
        tasks = [check_domain(session, d) for d in DOMAINS]
        results = await asyncio.gather(*tasks)

    new_status = {}
    changes = []
    status_lines = []

    for r in results:
        domain = r["domain"]
        current = r["status"]
        previous = prev_status.get(domain, "")
        new_status[domain] = current

        icon = "🔴" if current == "BLOCKED" else "✅" if current == "ACCESSIBLE" else "⚠️"
        status_lines.append(f"{icon} {domain}: {current}")

        if previous and previous != current:
            changes.append({**r, "from": previous})
            print(f"[CHANGE] {domain}: {previous} -> {current}")
        else:
            print(f"[OK] {domain}: {current}")

    save_status(new_status)

    if changes:
        msg = "🚨 *BTK Domain Durum Değişikliği!*\n"
        msg += f"🕐 {timestamp}\n"
        msg += "─────────────────\n\n"
        for c in changes:
            emoji = "🔴" if c["status"] == "BLOCKED" else "✅"
            msg += f"{emoji} *{c['domain']}*\n"
            msg += f"   {c['from']} → *{c['status']}*\n"
            if c.get("detail"):
                msg += f"   📋 {c['detail']}\n"
            msg += "\n"
        await send_telegram(msg)
    else:
        # Rutin durum bildirimi
        msg = f"[BTK Kontrol] {timestamp}\n"
        msg += "\n".join(status_lines)
        await send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
