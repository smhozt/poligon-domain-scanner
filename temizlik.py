import json
import os

# Bize ait olan numaralar ve aralıklar
OWNED_NUMBERS = [724, 1240, 1268, 1560, 2369]
OWNED_RANGES = [
    (1300, 1410),
    (1700, 1974)
]

# Kapsamlı Whitelist'i oluştur
whitelist = set(["superbetin.com"])
for num in OWNED_NUMBERS:
    whitelist.add(f"superbetin{num}.com")
for r_start, r_end in OWNED_RANGES:
    for num in range(r_start, r_end + 1):
        whitelist.add(f"superbetin{num}.com")

# Temizlenecek dosyalar
files_to_clean = [
    "reported.json",
    "complaint_reported.json",
    "safe_browsing_reported.json",
    "whois_reported.json"
]

print("🧹 JSON Temizliği Başlıyor...\n")

for filename in files_to_clean:
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except:
                data = []
        
        original_count = len(data)
        # Whitelist'te OLMAYANLARI filtrele (Sadece Gerçek Sahteler Kalsın)
        clean_data = [domain for domain in data if domain not in whitelist]
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(clean_data, f)
            
        removed = original_count - len(clean_data)
        print(f"✅ {filename}: {removed} tane bizim domain silindi. Kalan gerçek sahte sayısı: {len(clean_data)}")
    else:
        print(f"⚠️ {filename} bulunamadı, atlanıyor.")

print("\n🚀 Temizlik tamamlandı! Artık sistem kendi domainlerimizi fake sanmayacak.")
