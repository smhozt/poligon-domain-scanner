import json
import os
from datetime import datetime

def load_json(filename, default_val):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return default_val
    return default_val

# Verileri topla
btk_data = load_json('btk_status.json', {"statuses": {}})
reported = load_json('reported.json', [])
google_reported = load_json('reported_google.json', [])

now = datetime.now().strftime("%d.%m.%Y %H:%M")

# Markdown (DASHBOARD) Şablonunu Oluştur
md = f"# 🛡️ Poligon Operasyon Merkezi - Canlı Dashboard\n\n"
md += f"⏱️ **Son Güncelleme:** `{now} (UTC)`\n\n"
md += "---\n\n"

# 1. BTK Durumu
md += "## 🇹🇷 BTK Erişim Durumu\n"
md += "| Domain | Durum |\n"
md += "|--------|-------|\n"
if btk_data.get("statuses"):
    for domain, status in btk_data["statuses"].items():
        icon = "🔴 **ENGELLİ**" if "BLOCKED" in status else "✅ **AKTİF**"
        md += f"| `{domain}` | {icon} |\n"
else:
    md += "| Bekleniyor... | - |\n"

md += "\n---\n\n"

# 2. Google Tarayıcı
md += "## 🔍 Google Arama Radarı (Typo & Sahte)\n"
md += "| Yakalanan Domain | İşlem Durumu |\n"
md += "|------------------|--------------|\n"
if google_reported:
    # En son yakalananları en üstte göstermek için reversed kullanıyoruz
    for domain in reversed(google_reported): 
        md += f"| `{domain}` | ⚠️ Telegram'a Bildirildi |\n"
else:
    md += "| 🟢 Saha Temiz | - |\n"

md += "\n---\n\n"

# 3. Domain Tarayıcı (İnfaz Edilenler)
md += "## 🎯 Olası Sahte Domainler (1500+ Tarama)\n"
md += "| Yakalanan Domain | İşlem Durumu |\n"
md += "|------------------|--------------|\n"
if reported:
    for domain in reversed(reported):
        md += f"| `{domain}` | 🔫 İnfazlandı (NiceNIC Şikayet Edildi) |\n"
else:
    md += "| 🟢 Saha Temiz | - |\n"

# Dosyaya Yaz
with open('DASHBOARD.md', 'w', encoding='utf-8') as f:
    f.write(md)

print("DASHBOARD.md başarıyla güncellendi!")
