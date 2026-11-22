# Erkek Kuaförleri İçin Online Randevu Platformu

Her berberin kendi randevu sayfası: pazar yeri yok, komisyon yok. Müşteri üye olmadan,
SMS koduyla randevu alır; kuaför takvimini, müşterilerini ve cirosunu tek panelden görür.

Proje raporundaki Faz 1 ve Faz 2 kapsamını içerir (ayrıntı aşağıda).

## Kurulum

PostgreSQL 13+ ve Python 3.11+ gerekir.

```bash
pip install -r requirements.txt
createuser berber --pwprompt --createdb   # şifre: berber (geliştirme varsayılanı)
createdb berber --owner berber
python manage.py migrate
python manage.py seed_demo                # isteğe bağlı: örnek dükkân ve 7 haftalık veri
python manage.py runserver
```

| Adres | Ne |
|---|---|
| `http://localhost:8000/ornek-berber/` | Müşterinin gördüğü sayfa |
| `http://localhost:8000/panel/` | Kuaför paneli (`demo@example.com` / `demo-sifre-1`) |
| `http://localhost:8000/panel/kayit/` | Yeni dükkân kurulumu |
| `http://localhost:8000/yonetim/` | Platform yönetimi (`python manage.py createsuperuser`) |

Geliştirmede SMS gönderilmez; mesajlar konsola yazılır ve doğrulama kodu ekranda gösterilir.

Testler: `python manage.py test` (43 test).

## Neler var

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

**Altyapı**
- Çok kiracılı yapı: tek veritabanı, her kayıtta işletme kimliği; yalıtım otomatik testle doğrulanır
- Çakışan randevu veritabanı kısıtıyla engellenir (`no_overlap_per_staff`)
- Kod gönderim sınırları: numara, IP ve dükkân başına; kod sunucuda özet olarak tutulur
- Mesaj kuyruğu: onay hemen, hatırlatma 24 saat önce; iptal edilen randevunun mesajı gitmez
- Fiyat ve süre randevu kalemine kopyalanır; fiyat değişince geçmiş ciro değişmez
- İşlem kaydı: kim, ne zaman, hangi randevuyu değiştirdi

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

Fotoğraf galerisi, abonelik tahsilatı ve fatura, SMS kredisi satışı, bekleme listesi, yorum daveti,
düzenli randevu, PWA, kapora, personelin kendi girişi ve yetki ayrımı, panel girişinde ikinci adım,
takvimde sürükle-bırak, kampanya mesajı gönderimi ve İYS kaydı.

## Dizin yapısı

```
config/   ayarlar ve adresler
core/     veri modeli, boş saat hesabı, randevu, doğrulama kodu, SMS, raporlar, testler
public/   müşteri tarafı
panel/    kuaför paneli
templates/, static/
```
