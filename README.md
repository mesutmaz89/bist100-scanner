# BIST100 Otomatik Teknik Tarama Sistemi

## Mimari
```
GitHub Actions (cron, günde 3x)
      ↓
data_fetcher.py (Yapı Kredi API → yoksa Yahoo Finance)
      ↓
indicators.py (EMA/ADX/RSI/MACD/ATR/Bollinger/Hacim)
      ↓
rule_based_prefilter (ucuz filtre — maliyeti düşürür)
      ↓
claude_analyzer.py (sadece adaylar, batch halinde Claude'a)
      ↓
firestore_writer.py ──→ Firestore (signals/, signal_history/)
      ↓
fcm_notifier.py ──→ Push bildirim (confidence=high + yeni sinyal)
      ↓
React PWA dashboard (Firestore'u okur, FCM dinler)
```

## Kurulum Adımları

### 1. GitHub reposu
Bu klasörü `mesutmaz89` altında yeni bir repoya push et:
```bash
cd bist100-scanner
git init
git add .
git commit -m "İlk kurulum"
git remote add origin https://github.com/mesutmaz89/bist100-scanner.git
git push -u origin main
```

### 2. Watchlist'i tamamla
`config/watchlist.json` içinde ~75 hisse var. Eksik ~25 hisseyi
https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Endeks-Bilesenleri.aspx
adresindeki güncel BIST100 listesinden tamamla (ticker kodu, `.IS` YOK — kod otomatik ekliyor).

### 3. Firebase projesi
Mevcut `bsh-fik1-spc` ya da `villa-takip` projelerini kullanma — ayrı bir proje aç
(finansal veri farklı güvenlik kuralları gerektirir). `europe-west` region'da yeni proje:
- Firestore'u etkinleştir (Native mode)
- Cloud Messaging (FCM) etkinleştir
- Proje Ayarları → Servis Hesapları → "Yeni özel anahtar oluştur" ile JSON indir

Firestore güvenlik kuralları (herkese okuma, sadece server'a yazma):
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /signals/{ticker} {
      allow read: if true;
      allow write: if false;   // sadece Admin SDK (GitHub Actions) yazabilir
    }
    match /signal_history/{doc} {
      allow read: if true;
      allow write: if false;
    }
  }
}
```

### 4. GitHub Secrets
Repo → Settings → Secrets and variables → Actions → "New repository secret":

| Secret adı | Değer |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com'dan aldığın API key |
| `FIREBASE_SERVICE_ACCOUNT` | indirdiğin JSON dosyasının TAM içeriği (tek satır string olarak yapıştır) |
| `YKB_API_KEY` | Yapı Kredi API'yi alınca doldurulacak (şimdilik boş bırakabilirsin) |
| `YKB_BASE_URL` | aynı şekilde ileride |

### 5. Test çalıştırması
Actions sekmesinden `BIST100 Scanner` workflow'unu bul, "Run workflow" ile manuel tetikle.
Loglardan kaç hisse çekildiğini, kaç adayın Claude'a gittiğini ve kaç sinyal yazıldığını görürsün.

### 6. Yapı Kredi API alındığında
`scripts/data_fetcher.py` içindeki `fetch_from_ykb()` fonksiyonunun içindeki TODO bloğunu
gerçek endpoint ile doldur. Kod zaten YKB → Yahoo fallback mantığına göre yazıldı,
başka hiçbir yeri değiştirmen gerekmiyor.

## Maliyet notu
- 75-100 hisse × günde 3 tarama = veri çekme ücretsiz (Yahoo Finance)
- Claude çağrısı sadece ön filtreden geçen adaylar için, 15'li batch halinde
  → günde tipik olarak 5-15 API çağrısı (aday sayısına göre değişir), tek tek 300 çağrı DEĞİL
- Model olarak `claude-sonnet-4-6` seçili; maliyeti daha da düşürmek istersen
  `claude_analyzer.py` içindeki `MODEL` değişkenini Haiku'ya çevirebilirsin

## Sırada ne var (henüz yapılmadı)
- [ ] React PWA dashboard (Firestore `signals/` koleksiyonunu okuyup kart listesi gösterecek)
- [ ] FCM topic aboneliği (PWA'da `bist100_signals` topic'ine subscribe)
- [ ] Yapı Kredi API entegrasyonu (key alındığında)
- [ ] Backtest scripti (geçmiş sinyallerin ne kadar isabetli olduğunu ölçmek için)

Bir sonraki adım olarak PWA dashboard'u mu yoksa backtest scriptini mi önce istersin,
söyle devam edelim.
