import asyncio
import aiohttp
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")

# Bizim domainlerimiz - whitelist
SUPERBETIN_WHITELIST = set([
    "superbetin.com","superbetin1813.com","superbetin1814.com","superbetin1815.com",
    "superbetin1816.com","superbetin1817.com","superbetin1818.com","superbetin1819.com",
    "superbetin1820.com","superbetin1821.com","superbetin1822.com","superbetin1823.com",
    "superbetin1824.com","superbetin1826.com","superbetin1827.com","superbetin1828.com",
    "superbetin1829.com","superbetin1830.com","superbetin1831.com","superbetin1832.com",
    "superbetin1833.com","superbetin1834.com","superbetin1835.com","superbetin1836.com",
    "superbetin1837.com","superbetin1838.com","superbetin1839.com","superbetin1840.com",
    "superbetin1841.com","superbetin1842.com","superbetin1843.com","superbetin1844.com",
    "superbetin1845.com","superbetin1846.com","superbetin1847.com","superbetin1848.com",
    "superbetin1849.com","superbetin1850.com","superbetin1851.com","superbetin1852.com",
    "superbetin1853.com","superbetin1854.com","superbetin1855.com","superbetin1856.com",
    "superbetin1857.com","superbetin1858.com","superbetin1859.com","superbetin1860.com",
    "superbetin1861.com","superbetin1862.com","superbetin1863.com","superbetin1864.com",
    "superbetin1865.com","superbetin1866.com","superbetin1867.com","superbetin1868.com",
    "superbetin1869.com","superbetin1870.com","superbetin1871.com","superbetin1872.com",
    "superbetin1873.com","superbetin1874.com","superbetin1875.com","superbetin1876.com",
    "superbetin1877.com","superbetin1878.com","superbetin1880.com","superbetin1881.com",
    "superbetin1882.com","superbetin1883.com","superbetin1884.com","superbetin1885.com",
    "superbetin1886.com","superbetin1887.com","superbetin1888.com","superbetin1889.com",
    "superbetin1890.com","superbetin1891.com","superbetin1892.com","superbetin1893.com",
    "superbetin1894.com","superbetin1895.com","superbetin1896.com","superbetin1897.com",
    "superbetin1898.com","superbetin1899.com","superbetin1900.com","superbetin1901.com",
    "superbetin1902.com","superbetin1903.com","superbetin1904.com","superbetin1905.com",
    "superbetin1906.com","superbetin1907.com","superbetin1908.com","superbetin1909.com",
    "superbetin1910.com","superbetin1912.com","superbetin1913.com","superbetin1914.com",
    "superbetin1915.com","superbetin1916.com","superbetin1917.com","superbetin1918.com",
    "superbetin1919.com","superbetin1920.com","superbetin1921.com","superbetin1922.com",
    "superbetin1923.com","superbetin1924.com","superbetin1925.com","superbetin1926.com",
    "superbetin1927.com","superbetin1928.com","superbetin1929.com","superbetin1930.com",
    "superbetin1931.com","superbetin1932.com","superbetin1933.com","superbetin1934.com",
    "superbetin1935.com","superbetin1936.com","superbetin1937.com","superbetin1938.com",
    "superbetin1939.com","superbetin1940.com","superbetin1941.com","superbetin1942.com",
    "superbetin1943.com","superbetin1944.com","superbetin1945.com","superbetin1946.com",
    "superbetin1947.com","superbetin1948.com","superbetin1949.com","superbetin1950.com",
    "superbetin1951.com","superbetin1952.com","superbetin1953.com","superbetin1954.com",
    "superbetin1955.com","superbetin1956.com","superbetin1957.com","superbetin1958.com",
    "superbetin1959.com","superbetin1960.com","superbetin1961.com","superbetin1962.com",
    "superbetin1963.com","superbetin1964.com","superbetin1965.com","superbetin1966.com",
    "superbetin1967.com","superbetin1968.com","superbetin1969.com","superbetin1970.com",
    "superbetin1971.com","superbetin1972.com","superbetin1973.com","superbetin1974.com",
])

# Taranacak domainler
SUPERBETIN_GAPS = [1825, 1879, 1911]
SUPERBETIN_RANGE = range(1975, 2501)  # 1975-2500
SUPERBETIM_RANGE = range(1000, 2151)  # 1000-2150

# VIP domainler için kullanılacak anahtar kelimeler
VIP_KEYWORDS = [
    "turkey", "girisi", "adres", "resmi", "guncel", 
    "guncelgiris", "giris", "link", "yeni", "vip", "girisadresi"
]

# Sabit bilinenler ve otomatik üretilenler için liste
VIP_DOMAINS = set([
    "superbetinturkey.vip", "superbetingirisi.vip", "superbetinadres.vip",
    "m.superbetinturkey.vip", "m.superbetingirisi.vip", "m.superbetinadres.vip"
])

for word in VIP_KEYWORDS:
    VIP_DOMAINS.add(f"superbetin{word}.vip")
    VIP_DOMAINS.add(f"m.superbetin{word}.vip")
    VIP_DOMAINS.add(f"superbetim{word}.vip") 

REPORTED_FILE = "reported.json"

def load_reported():
    try:
        with open(REPORTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_reported(reported):
    with open(REPORTED_FILE, "w") as f:
        json.dump(list(reported), f)

# NICE NIC OTOMATIK SIKAYET FONKSIYONU (THE EXECUTIONER)
def send_execution_email(domain):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print(f"[{domain}] Mail bilgileri eksik, otomatik şikayet atlanıyor.")
        return

    receiver_email = "abuse@nicenic.net"
    subject = f"URGENT Phishing Domain Takedown - {domain}"
    
    body = f"""Dear NiceNIC Abuse Team,

We are Poligon Entertainment N.V. (Curaçao License OGL/2024/815/0653), the legitimate operator of superbetin.com and superbetin1815.com.

The domain {domain} registered through your registrar is actively used for phishing and credential harvesting targeting Turkish users.

This matches the exact pattern of recently suspended phishing domains by the same threat actor (e.g., superbetin1977.com, superbetin1978.com, superbetingirisi.vip).

Please suspend this domain immediately to prevent further financial fraud.

Best regards,
Poligon Entertainment N.V.
License: OGL/2024/815/0653
"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[{domain}] Icin infaz maili NiceNIC'e basariyla atildi! 🔫")
    except Exception as e:
        print(f"Mail gonderim hatasi ({domain}): {e}")

async def check_dns(session, domain):
    try:
        url = f"https://dns.google/resolve?name={domain}&type=A"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if data.get("Status") == 0 and data.get("Answer"):
                    ip = data["Answer"][0].get("data", "")
                    return True, ip
    except:
        pass
    return False, ""

async def check_http(session, domain):
    try:
        async with session.get(
            f"https://{domain}",
            timeout=aiohttp.ClientTimeout(total=5),
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "tr-TR,tr;q=0.9"}
        ) as resp:
            if resp.status in [200, 301, 302, 403]:
                return True, resp.status
    except:
        pass
    return False, 0

async def scan_domain(session, domain, prefix, dtype, whitelist, reported, found):
    if domain in whitelist or domain in reported:
        return
    
    dns_ok, ip = await check_dns(session, domain)
    http_ok, code = await check_http(session, domain)
    
    if dns_ok or http_ok:
        detected_by = "HTTP" if http_ok else "DNS"
        status = str(code) if http_ok else f"DNS:{ip}"
        found.append({
            "domain": domain,
            "type": dtype,
            "detected_by": detected_by,
            "status": status,
            "ip": ip
        })
        reported.add(domain)
        print(f"[FOUND] {domain} ({detected_by}: {status})")

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            chat_id = chat_id.strip()
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            await session.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            })

async def main():
    reported = load_reported()
    found = []

    domains_to_scan = []
    
    for num in SUPERBETIN_GAPS:
        domain = f"superbetin{num}.com"
        domains_to_scan.append((domain, "superbetin", "BOSLUK", SUPERBETIN_WHITELIST))
    
    for num in SUPERBETIN_RANGE:
        domain = f"superbetin{num}.com"
        domains_to_scan.append((domain, "superbetin", "YENI", SUPERBETIN_WHITELIST))
    
    for num in SUPERBETIM_RANGE:
        domain = f"superbetim{num}.com"
        domains_to_scan.append((domain, "superbetim", "TYPO", set()))

    for domain in VIP_DOMAINS:
        domains_to_scan.append((domain, "vip", "VIP", set()))

    print(f"Toplam {len(domains_to_scan)} domain taranacak...")

    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        semaphore = asyncio.Semaphore(50)
        
        async def bounded_scan(domain, prefix, dtype, whitelist):
            async with semaphore:
                await scan_domain(session, domain, prefix, dtype, whitelist, reported, found)
        
        tasks = [bounded_scan(d, p, t, w) for d, p, t, w in domains_to_scan]
        await asyncio.gather(*tasks)

    save_reported(reported)

    if found:
        msg = "🚨 *[ALARM] Aktif Sahte Domain Tespit Edildi!*\n"
        msg += f"{len(found)} domain aktif:\n\n"
        for item in found:
            icon = "🦇 [TYPO]" if item["type"] == "TYPO" else "⚠️ [!]" if item["type"] == "BOSLUK" else "💎 [VIP]" if item["type"] == "VIP" else "🔥 [YENI]"
            msg += f"{icon} `{item['domain']}` ({item['detected_by']}: {item['status']})\n"
            if item["ip"]:
                msg += f"   IP: {item['ip']}\n"
            
            # THE EXECUTIONER: Maili Atesle! (İşte tetiğe bastığımız yer burası)
            send_execution_email(item['domain'])
        
        print(msg)
        await send_telegram(msg)
    else:
        print("Temiz - yeni sahte domain bulunamadi.")

if __name__ == "__main__":
    asyncio.run(main())
