# Erkek Kuaförleri İçin Online Randevu Platformu

Her kuaförün kendi randevu sayfası: pazar yeri yok, komisyon yok. Müşteri üye olmadan,
SMS koduyla randevu alır; kuaför takvimini, müşterilerini ve cirosunu tek panelden görür.

Proje raporundaki Faz 1 ve Faz 2 kapsamını içerir (ayrıntı aşağıda).

## Kurulum

PostgreSQL 13+ ve Python 3.11+ gerekir.

```bash
pip install -r requirements.txt
createuser berber --pwprompt --createdb   # şifre: berber (geliştirme varsayılanı)
createdb berber --owner berber
python manage.py migrate
python manage.py seed_demo                # isteğe bağlı: örnek dükkân ve 12 haftalık veri
python manage.py runserver
```

| Adres | Ne |
|---|---|
| `http://localhost:8000/ornek-berber/` | Müşterinin gördüğü sayfa |
| `http://localhost:8000/panel/` | Kuaför paneli (`demo@example.com` / `demo-sifre-1`) |
| `http://localhost:8000/panel/kayit/` | Yeni dükkân kurulumu |
| `http://localhost:8000/yonetim/` | Platform yönetimi (`python manage.py createsuperuser`) |

Geliştirmede SMS gönderilmez; mesajlar konsola yazılır ve doğrulama kodu ekranda gösterilir.

Testler: `python manage.py test` (83 test).

## Canlı tanıtım sitesi (Render)

Depoda `render.yaml` var; web servisini ve PostgreSQL'i birlikte kurar.

1. <https://render.com/deploy?repo=https://github.com/UzmanSAR/projeler/tree/claude/proje-incelemesi-l3887x>
   adresini aç, Render'a GitHub hesabınla giriş yap ve depoya erişim izni ver.
2. "Apply" / "Deploy Blueprint" düğmesine bas. Kurulum birkaç dakika sürer.
3. Site adresi `berber-randevu` servisinin sayfasında görünür (`https://berber-randevu-....onrender.com`).

Platform yönetimi (`/yonetim/`) için Render'da servisin **Environment** sekmesine
`SUPERUSER_EMAIL` ve `SUPERUSER_PASSWORD` değişkenlerini ekle ve yeniden yayınla; yönetici
kurulum sırasında oluşturulur. Kullanıcı zaten varsa şifresi değişmez. Şifreyi sonradan
`/yonetim/` içinden değiştirebilirsin.

Bu bir tanıtım kurulumudur: SMS gitmez, doğrulama kodu ekranda gösterilir, örnek dükkân
(`/ornek-berber/`, panel: `demo@example.com` / `demo-sifre-1`) hazır gelir ve hatırlatma
mesajları gönderilmez. Örnek dükkânda dört berber, dokuz hizmet, birkaç yüz müşteri ve on iki
haftalık randevu geçmişi vardır (`core/demo.py`). `SEED_DEMO=1` iken veri her yayında ve sunucu
her uyandığında tazelenir: yeni günler eklenir, geçmişe düşen örnek randevular kapatılır;
ziyaretçilerin kendi aldığı deneme randevularına dokunulmaz. Gerçek müşteriyle kullanmadan önce `SMS_SHOW_CODE` ve `SEED_DEMO`
değişkenlerini kaldır, demo kullanıcısını sil ve aşağıdaki "Yayına almadan önce" listesini uygula.

## Neler var

**Ana sayfa**
- Tanıtım sayfası (`templates/public/landing.html`, `static/css/landing.css`): ürün önizlemesi, nasıl
  çalışır, özellikler, sık sorulanlar. Örnek dükkân kuruluysa "Örnek dükkânı gez" bağlantısı görünür

**Müşteri tarafı**
- Kuaföre özel sayfa: hizmetler, süre, fiyat, çalışma saatleri, arama ve WhatsApp butonu
- Dört adımda randevu: işlem ve berber ("fark etmez" dahil), gün ve saat, ad ve telefon, SMS kodu
- Doğrulanmış cihaz 90 gün tekrar kod istemez
- Onay sayfası: iptal, takvime ekleme, isteğe bağlı kampanya izni (koddan ayrı, işaretsiz kutu)
- Şifresiz müşteri hesabı: geçmiş randevular, "aynısını tekrar al"

**Kuaför paneli**
- Bugün: günün randevuları, randevu kapatma (tamamlandı / gelmedi, tutar, nakit ya da kart),
  randevusuz müşteri kaydı, kapatılmamış eski randevu uyarısı
- Takvim: berber başına sütun, elle randevu ekleme, saat kapatma
- Müşteriler: ziyaret, harcama, gelmeme sayısı, not, kaybedilme riski olanlar, kayıt silme
- Raporlar: beş temel rakam ve önceki aya göre değişim, yoğunluk haritası, hizmete ve berbere göre ciro
- Ayarlar: hizmetler, personel, çalışma saatleri ve mola, randevu kuralları
- Üyelik ve ödeme (`/panel/ayarlar/uyelik/`): aylık ücret, deneme ya da ödeme günü, kalan gün,
  nasıl ödeneceği ve ödeme geçmişi. Ödeme gününe beş gün kala panelin üstünde hatırlatma çıkar

**Üyelik (aylık)**
- Aylık ücret ve kuaföre gösterilecek ödeme bilgisi (IBAN gibi) yönetim panelinde
  **Platform ayarları**ndan girilir; tek bir işletmeye özel ücret işletme kaydında tutulur
- Ödeme geldiğinde yönetim panelinde işletme seçilip **"1 aylık üyelik ödemesi kaydet"** işlemi
  çalıştırılır (ya da işletme sayfasında ödeme satırı eklenir): üyelik bitişi bir ay ilerler, deneme
  ya da ödeme bekleyen hesap aktif olur. Erken ödeyen gün kaybetmez, geç ödeyenin dönemi ödediği gün başlar.
  Yanlış girilen ödeme silinerek ya da düzeltilerek geri alınır: üyelik bitişi her zaman kalan
  ödeme kayıtlarından hesaplanır ve elle yazılmaz. Ücretsiz süre vermek için işletme sayfasına 0 ₺'lik,
  dönem sonu yazılmış bir ödeme satırı eklenir. Bir ödeme hiçbir zaman bir takvim ayından kısa sürmez
- Hiçbir hesap kendiliğinden kapatılmaz: "ödeme bekliyor" ve "kapalı" durumlarını yönetim verir
- Online kart tahsilatı yoktur (`core/billing.py` yalnızca kaydı ve tarihleri yönetir)

**Geri bildirim**
- `/gorus/`: müşteri ya da işletme sahibi programla ilgili öneri ve görüşünü yazar. Bağlantısı dükkân
  sayfalarının altında, ana sayfada ve panelde Ayarlar'dadır. Gönderiler yönetim panelinde
  **Geri bildirimler** listesinde okunur. Tuzak alan, adres başına saatte beş ve site geneli saatte
  üç yüz gönderim tavanı vardır

**Ana ekrana eklenebilen uygulama (PWA)**
- Kuaför paneli ve her dükkânın sayfası ana ekrana eklenebilir: panel platformun adıyla, dükkân kendi
  adıyla yerleşir (`/uygulama.webmanifest`, `/<adres>/uygulama.webmanifest`, `core/pwa.py`)
- Tarayıcı izin verdiği anda "Ana ekrana ekle" çubuğu çıkar (`static/js/pwa.js`): panelde Bugün
  ekranında, müşteride dükkân sayfasında ve onay fişinde. iPhone'da ekleme adımını anlatır
- Hizmet betiği (`/sw.js`) hiçbir sayfayı ve veriyi saklamaz; yalnızca bağlantı yokken
  "Bağlantı yok" sayfasını gösterir

**Altyapı**
- Çok kiracılı yapı: tek veritabanı, her kayıtta işletme kimliği; yalıtım otomatik testle doğrulanır
- Çakışan randevu veritabanı kısıtıyla engellenir (`no_overlap_per_staff`)
- Kod gönderim sınırları: numara, IP ve dükkân başına; kod sunucuda özet olarak tutulur
- Mesaj kuyruğu: onay hemen, hatırlatma 24 saat önce; iptal edilen randevunun mesajı gitmez
- Fiyat ve süre randevu kalemine kopyalanır; fiyat değişince geçmiş ciro değişmez
- İşlem kaydı: kim, ne zaman, hangi randevuyu değiştirdi

**Görünüm**
- Açık tema "Usta işi": kemik beyazı kâğıt, mürekkep siyahı ve tek vurgu olarak bordo. Renk, yazı ve
  ölçü değerleri `static/css/app.css` dosyasının ilk bloğundadır (`--gold` adı eski temadan kalmadır;
  değeri bordodur)
- Yazı tipleri kendi sunucumuzdan gelir (`static/fonts`, SIL OFL): başlıklar Gloock, metin Libre
  Franklin, şekil altı notları Newsreader italik. Dışarıya hiçbir istek gitmez
- Ustura, makas, tarak ve berber direği elle çizilmiş SVG'dir (`templates/_pole.html`,
  `templates/_sprite.html`, ana sayfadaki levhalar)

**Hareket katmanı**
- Sayfa geçişleri, buton durumları ve bekleme göstergesi; derleme adımı ve dış kütüphane yok
  (`static/css/app.css`, `static/js/app.js`, müşteri tarafı `public.*`, panel `panel.*`)
- Berberliğe özgü hareketler: ustura köpüğü siler (ana sayfa başlığı, gün değişimi, kapatılan
  randevunun tutarı), makas kesik çizgiyi ve seçilen saatin köşesini keser, onayda mühür iner ve
  koçan ayrılır, beklerken direk döner
- Ana sayfadaki ustura, tarak ve makas ekrandayken durmadan çalışır (sap açılıp kapanır, dişlerden
  ışık geçer, makas keser); ekrandan çıkınca bekler. Şekil altındaki "Durdur" hepsini durdurur,
  seçim oturum boyunca kalır. Yalnızca tam harekette çalışır (`html[data-loops]`, `public.js`)
- Hareket yalnızca süslemedir: JavaScript kapalıyken ya da "hareketi azalt" ayarı açıkken her sayfa
  eksiksiz çalışır; sayfa geçişlerini desteklemeyen tarayıcıda geçiş olmadan açılır
- `MOTION` ortam değişkeni: `full` (varsayılan), `lite` (yalnızca basma, yükleme ve geçiş), `off` (hareket
  kapalı; `OFF`, `0`, `false` yazımları da kapatır). `off` yalnızca hareketi kapatır: gönderilen formun
  kilitlenmesi ve bekleme göstergesi çalışmaya devam eder
- Statik dosya adresleri içerikten türeyen bir `?v=` değeri taşır (`core/context.py`); dosya değişince
  adres kendiliğinden değişir, sürümü elle artırmak gerekmez
- Davranış bayrakları `templates/base.html` içindeki `data-flags` özniteliğinde: `live-total`
  ("Devam et" butonunda süre ve tutar), `now-line` (takvimde şu an çizgisi), `copy-link` (randevu
  bağlantısına dokununca kopyalama). `auto-code` (altıncı rakamda kodu kendiliğinden gönderme)
  kapalıdır; özniteliğe eklenince açılır

## Rapora göre yapılan değişiklikler

- Randevu kapatma, randevusuz müşteri kaydı ve iptal linki ilk sürüme alındı
  (raporda kapsam tablosu ile faz etiketleri çelişiyordu).
- Kuaförün elle girdiği randevuya da onay ve hatırlatma gider; Ayarlar'dan kapatılabilir.
- Müşteri kaydı işletmeye özeldir; platform geneli müşteri hesabı ve kara liste yoktur.
- Arka plan işleri için ayrı bir kuyruk sunucusu yerine veritabanı kuyruğu ve cron kullanılır.

## Yayına almadan önce

1. **SMS sağlayıcısı.** `core/sms.py` içindeki `ConsoleBackend` gibi, `send(phone, body)` metodu olan
   bir sınıf yazıp `SMS_BACKEND` ile ver. Gerçek sağlayıcı bağlantısı bu depoda yok.
2. **Hatırlatmalar.** Cron ile dakikada bir: `python manage.py send_due_messages`
3. **Ortam değişkenleri.** `.env.example` dosyasındaki değerler; `DEBUG=0`, `SECRET_KEY`, `REDIS_URL`.
4. **Bot kontrolü.** Turnstile anahtarları verilmezse kod gönderiminden önce bot kontrolü yapılmaz.
5. **Statik dosyalar.** `python manage.py collectstatic` ve bir web sunucusu (gunicorn + nginx gibi).
6. **Hukuk.** Aydınlatma metni, kullanım koşulları ve veri işleme eki yazılmadı; avukat görüşü gerekir.

## Henüz yok

Fotoğraf galerisi, online abonelik tahsilatı (kart) ve fatura, SMS kredisi satışı, bekleme listesi,
yorum daveti, düzenli randevu, anlık bildirim, kapora, personelin kendi girişi ve yetki ayrımı, panel girişinde ikinci adım,
takvimde sürükle-bırak, kampanya mesajı gönderimi ve İYS kaydı.

## Dizin yapısı

```
config/   ayarlar ve adresler
core/     veri modeli, boş saat hesabı, randevu, doğrulama kodu, SMS, raporlar, testler
public/   müşteri tarafı
panel/    kuaför paneli
templates/, static/
```
