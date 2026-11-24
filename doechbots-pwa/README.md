# DoechBots Panel: PWA (ana ekrana eklenebilen uygulama)

panel.doechbots.com'u telefonda uygulama gibi açılır hale getiren dosyalar. Panelin hangi dille
yazıldığından bağımsızdır: dosyalar statik, sadece doğru adreslerden sunulmaları gerekir.

## Ne yapar

- Android (Chrome, Edge, Samsung Internet): altta **"DoechBots'u ana ekranına ekle"** çubuğu çıkar, "Ekle"ye dokununca kurulur.
- iPhone/iPad: Paylaş > "Ana Ekrana Ekle" adımını tarif eden çubuk çıkar (iOS'ta tek dokunuşla kurulum yok).
- Kurulunca adres çubuğu olmadan, kendi ikonuyla tam ekran açılır.
- Bağlantı yokken boş/hata sayfası yerine "İnternet bağlantısı yok" ekranı gösterir, bağlantı gelince kendiliğinden yenilenir.
- **Hiçbir panel sayfası ya da bot verisi önbelleğe alınmaz.** Bot durumu hep canlıdır, oturum bilgisi telefonda saklanmaz.

## Kurulum (3 adım)

**1. Dosyaları sitenin köküne koy.** Adresler tam olarak böyle olmalı:

| Dosya | Adres |
|---|---|
| `manifest.webmanifest` | `https://panel.doechbots.com/manifest.webmanifest` |
| `sw.js` | `https://panel.doechbots.com/sw.js` |
| `pwa.js` | `https://panel.doechbots.com/pwa.js` |
| `offline.html` | `https://panel.doechbots.com/offline.html` |
| `icons/*` | `https://panel.doechbots.com/icons/...` |

`sw.js` mutlaka kökte olmalı (`/static/sw.js` olursa sadece `/static/` altını kapsar). Framework'ün statik
dosyaları başka yoldan sunuyorsa, `/sw.js` ve `/manifest.webmanifest` için kökte birer yönlendirmesiz rota ekle.

**2. `head.html`'deki satırları** panelin ortak şablonuna (layout) ekle: `<head>` içine etiketler, `</body>` öncesine `pwa.js`.

**3. HTTPS** zorunlu (panel zaten HTTPS ise tamam). `manifest.webmanifest` için sunucu
`Content-Type: application/manifest+json` göndermeli; `sw.js` için `Cache-Control: no-cache` önerilir.

## Ayarlar

- **İkonlar:** `python3 make_icons.py logo.png` kendi logondan tüm boyutları üretir. Şimdiki ikonlar geçici "DB" monogramı.
- **Renkler:** `#0f1115` (zemin) ve `#f5b83d` (vurgu) geçici. Değiştirirsen `manifest.webmanifest`, `head.html`, `offline.html`, `pwa.js` ve `make_icons.py`'de aynı değerleri güncelle.
- **Çubuğun çıkmaması gereken sayfa** (giriş, ödeme vb.): o sayfanın `<html>` etiketine `data-pwa-teklif="yok"` ekle.
- **Ana sayfa:** uygulama `/?kaynak=pwa` ile açılır (istatistikte PWA'dan gelenleri ayırmak için). Panelin giriş sonrası
  sayfası farklıysa `manifest.webmanifest` içindeki `start_url`'i değiştir.
- **offline.html'i değiştirirsen** `sw.js`'teki `VERSION`'ı bir artır, yoksa telefonlar eski sayfayı göstermeye devam eder.

## Test

Chrome'da paneli aç > Geliştirici araçları > **Application** > Manifest ve Service workers bölümlerinde hata olmamalı.
Bu dosyalar yerel sunucuda Chromium ile denendi: kurulabilirlik hatası yok, çevrimdışı ekranı ve iPhone çubuğu çalışıyor.
