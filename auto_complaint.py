import asyncio
import aiohttp
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

REPORTED_FILE = "reported.json"
WHOIS_FILE = "whois_reported.json"
COMPLAINT_FILE = "complaint_reported.json"

# Şikayet gönderi adresleri
NICENIC_ABUSE = "abuse@nicenic.net"
NICENIC_SUPPORT = "support@nicenic.net"

# CGA Lisans linki
CGA_LICENSE = "https://cert.cga.cw/certificate?id=ZXlKcGRpSTZJa1V2TXpJM2MyWjFSV0pRYW1OQ1IxcFVkbEJMZGxFOVBTSXNJblpoYkhWbElqb2lMMVpTUXpSbU5XdG9lbkJHVlZSak1EVlJWMmxLZHowOUlpd2liV0ZqSWpvaVpXTXdaak5rWW1NeVlURXlNR1F6WkRFNVlqVmxabVJoTkdWak5qZzBNRGt3WVRVMFpHUmtNakppTXpnMVlUUmpaVFJrTW1JelpEazJZalJrTWpJd1l5SXNJblJoWnlJNklpSjk="

def load_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else list(data)
    except:
        return []

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(list(data), f)

def detect_brand(domain):
    d = domain.lower()
    if "betsat" in d:
        return "betsat", "betsat1540.com"
    elif "turkbet" in d:
        return "turkbet", "710turkbet.com"
    else:
        return "superbetin", "superbetin1821.com"

def build_nicenic_email(domain, brand, official_domain):
    """NICENIC için şikayet maili oluştur"""
    subject = f"URGENT: Phishing Domain - {domain} - Immediate ClientHold Required"

    body = f"""Dear NiceNIC Abuse Team,

We are reporting a fraudulent domain registered through your services:

Domain: {domain}

This domain is an active phishing site cloning our licensed brand ({brand.title()}), designed to steal user credentials and collect fraudulent bank transfers from Turkish users.

This is part of an ongoing serial fraud operation using your platform. Multiple domains from the same registrant cluster have already been placed on ClientHold by NiceNIC based on our previous reports.

We are a licensed operator: {brand}.com is operated by Poligon Entertainment N.V., licensed by the Curaçao Gaming Authority under license OGL/2024/815/0653 (Company Number 132517). Status: Active.
License verification: {CGA_LICENSE}

Our official domains: {brand}.com / {official_domain}

We urgently request:
1. Immediate ClientHold suspension of {domain}
2. Investigation of all domains registered by the same registrant account

Best regards,
Superbetin Security Team
security@superbetin.com
"""
    return subject, body

def send_email(to_addresses, subject, body, from_name="Superbetin Security Team"):
    """Gmail SMTP ile mail gönder"""
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
    reported_domains = load_json(REPORTED_FILE)
    complaint_done = set(load_json(COMPLAINT_FILE))

    # Daha önce şikayet edilmemiş domainler
    new_domains = [d for d in reported_domains if d not in complaint_done]

    if not new_domains:
        print("Şikayet gönderilecek yeni domain yok.")
        return

    print(f"{len(new_domains)} domain için şikayet gönderilecek...")

    success_list = []
    failed_list = []

    for domain in new_domains[:20]:  # Günde max 20 mail — spam olmasın
        # Subdomain ise root al
        parts = domain.split(".")
        if len(parts) > 2:
            root = ".".join(parts[-2:])
        else:
            root = domain

        brand, official_domain = detect_brand(domain)
        subject, body = build_nicenic_email(root, brand, official_domain)

        print(f"Şikayet gönderiliyor: {root} ({brand})")
        success = send_email(
            [NICENIC_ABUSE, NICENIC_SUPPORT],
            subject,
            body
        )

        if success:
            success_list.append(domain)
            complaint_done.add(domain)
            print(f"  ✅ Gönderildi: {root}")
        else:
            failed_list.append(domain)
            print(f"  ❌ Başarısız: {root}")

        await asyncio.sleep(5)  # Spam filtresi için bekle

    save_json(COMPLAINT_FILE, list(complaint_done))

    # Telegram özeti
    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    msg = f"📧 *[OTO-ŞİKAYET] NICENIC Mail Raporu* — {now}\n\n"

    if success_list:
        msg += f"✅ *Gönderilen:* {len(success_list)} şikayet\n"
        for d in success_list[:10]:
            brand, _ = detect_brand(d)
            icon = "🔵" if brand == "superbetin" else "🟠" if brand == "betsat" else "🟢"
            msg += f"  {icon} `{d}`\n"
        if len(success_list) > 10:
            msg += f"  ... ve {len(success_list)-10} tane daha\n"
        msg += "\n"

    if failed_list:
        msg += f"❌ *Başarısız:* {len(failed_list)} şikayet\n"

    msg += f"\n📬 *Gönderen:* `{SMTP_USER}`\n"
    msg += f"📮 *Alıcı:* `{NICENIC_ABUSE}`\n"
    msg += f"📮 *Alıcı:* `{NICENIC_SUPPORT}`"

    await send_telegram(msg)
    print(f"\n✅ Tamamlandı! {len(success_list)} mail gönderildi.")

if __name__ == "__main__":
    asyncio.run(main())
