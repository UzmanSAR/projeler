"""Model kataloğu (fotoğraf, randevuda seçim), işletme türü ve müşteri girişi/geçmişi."""
import io
import re
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from core.booking import close_appointment, create_appointment, get_or_create_customer
from core.models import Appointment, Business, Style
from core.tests import make_business, next_weekday


def photo(size=(1600, 1200), fmt="JPEG", exif_gps=False, name="foto.jpg"):
    img = Image.new("RGB", size, (180, 120, 90))
    out = io.BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x0112] = 6                       # yön: 90 derece döndürülmüş
        exif[0x8825] = {1: "N", 2: (41.0, 1.0, 2.0)}   # GPS bilgisi
        kwargs["exif"] = exif
    img.save(out, fmt, **kwargs)
    return SimpleUploadedFile(name, out.getvalue(), content_type=f"image/{fmt.lower()}")


class StyleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.user = make_business("ali")
        self.cut = self.b.services.get(name="Saç kesimi")
        self.client.force_login(self.user)

    def add(self, **extra):
        data = {"title": "Kısa fade", "note": "", "service": self.cut.id, "order": 0, "active": "on",
                "photo": photo(exif_gps=True)}
        data.update(extra)
        return self.client.post("/panel/ayarlar/modeller/ekle/", data)

    def test_upload_resizes_rotates_and_strips_location(self):
        self.assertRedirects(self.add(), "/panel/ayarlar/modeller/")
        style = Style.objects.get()
        self.assertEqual((style.width, style.height), (1050, 1400))     # EXIF yönü uygulandı, uzun kenar 1400
        full = Image.open(io.BytesIO(bytes(style.image)))
        self.assertEqual(full.format, "WEBP")
        self.assertFalse(full.getexif())                                 # konum ve cihaz bilgisi yok
        self.assertLessEqual(max(Image.open(io.BytesIO(bytes(style.thumb))).size), 520)
        r = self.client.get(style.image_url)
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/webp"))
        self.assertIn("immutable", r["Cache-Control"])
        self.assertEqual(self.client.get(style.thumb_url).status_code, 200)
        self.assertEqual(self.client.get(f"/m/{style.id}-000000000000.webp").status_code, 404)

    def test_bad_files_are_refused(self):
        r = self.add(photo=SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg"))
        self.assertEqual(r.status_code, 200)
        r = self.add(photo=photo(size=(120, 120)))
        self.assertContains(r, "çok küçük")
        r = self.add(photo=photo(fmt="GIF", name="a.gif"))
        self.assertContains(r, "desteklenmiyor")
        self.assertFalse(Style.objects.exists())

    def test_edit_without_new_photo_keeps_it_and_delete(self):
        self.add()
        style = Style.objects.get()
        digest = style.digest
        r = self.client.post(f"/panel/ayarlar/modeller/{style.id}/",
                             {"title": "Uzun fade", "service": "", "order": 2, "note": "Yanlar sıfır"})
        self.assertRedirects(r, "/panel/ayarlar/modeller/")
        style.refresh_from_db()
        self.assertEqual((style.title, style.digest, style.active, style.service), ("Uzun fade", digest, False, None))
        self.client.post(f"/panel/ayarlar/modeller/{style.id}/", {"action": "delete"})
        self.assertFalse(Style.objects.exists())

    def test_other_businesses_cannot_touch_styles(self):
        self.add()
        style = Style.objects.get()
        _, user = make_business("veli", "v@example.com")
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"/panel/ayarlar/modeller/{style.id}/").status_code, 404)
        self.client.post(f"/panel/ayarlar/modeller/{style.id}/", {"action": "delete"})
        self.assertTrue(Style.objects.exists())
        # başka işletmenin modeli randevuya bağlanamaz
        self.assertNotContains(self.client.get(f"/veli/randevu/?m={style.id}"), "Kısa fade")

    def test_customer_picks_style_and_barber_sees_it(self):
        self.add()
        style = Style.objects.get()
        shop = self.client.get("/ali/").content.decode()
        self.assertIn(f"/ali/randevu/?m={style.id}", shop)
        self.assertIn("Modeller", shop)
        # modelden gelince ilgili işlem seçili gelir
        page = self.client.get(f"/ali/randevu/?m={style.id}").content.decode()
        self.assertRegex(page, rf'name="h" value="{self.cut.id}" checked')
        self.assertRegex(page, rf'name="m" value="{style.id}" checked')
        r = self.client.get(f"/ali/randevu/?devam=1&m={style.id}&h={self.cut.id}&b=0")
        self.assertRedirects(r, f"/ali/randevu/saat/?h={self.cut.id}&b=0&m={style.id}", fetch_redirect_response=False)
        # randevu (doğrudan oluşturularak)
        day = next_weekday(1, timezone.now())
        start = timezone.datetime.combine(day, timezone.datetime.min.time().replace(hour=10),
                                          tzinfo=timezone.get_current_timezone())
        customer = get_or_create_customer(self.b, "05321112233", "Mehmet", verified=True)
        appt = create_appointment(self.b, [self.cut], start, customer=customer, style=style)
        self.assertEqual(appt.style, style)
        self.assertContains(self.client.get(f"/ali/r/{appt.token}/"), "Kısa fade")
        self.assertContains(self.client.get(f"/panel/takvim/?g={day:%Y-%m-%d}"), "Takvim")
        today = self.client.get("/panel/musteriler/%d/" % customer.id).content.decode()
        self.assertIn("Model: Kısa fade", today)
        # model silinse de randevu kalır
        style.delete()
        appt.refresh_from_db()
        self.assertIsNone(appt.style)

    def test_limit(self):
        self.add()
        style = Style.objects.get()
        for i in range(Style.MAX_PER_BUSINESS - 1):
            Style.objects.create(business=self.b, title=f"m{i}", image=style.image, thumb=style.thumb, digest=style.digest)
        r = self.client.get("/panel/ayarlar/modeller/ekle/")
        self.assertRedirects(r, "/panel/ayarlar/modeller/")


class KindTests(TestCase):
    def test_wording_follows_the_kind(self):
        b, _ = make_business("ayna")
        b.kind = Business.Kind.BEAUTY
        b.save()
        b.staff.create(name="Selin")
        page = self.client.get("/ayna/").content.decode()
        self.assertIn("Güzellik merkezi", page)
        self.assertIn("<h2>Uzmanlar</h2>", page)
        select = self.client.get("/ayna/randevu/").content.decode()
        self.assertIn("Kiminle?", select)
        self.assertNotIn("Erkek kuaförü", page)


class AccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.user = make_business("ali")
        self.cut = self.b.services.get(name="Saç kesimi")
        self.combo = self.b.services.get(name="Saç + sakal")

    def login(self, phone="05321112233", name="Mehmet"):
        r = self.client.post("/ali/hesabim/", {"action": "send", "phone": phone, "name": name}, follow=True)
        code = re.search(r"Kod: (\d{6})", r.content.decode()).group(1)
        self.assertContains(r, "6 haneli bir kod")
        return self.client.post("/ali/hesabim/", {"action": "verify", "code": code}, follow=True)

    def test_register_without_booking(self):
        self.assertContains(self.client.get("/ali/"), "Giriş yap")
        r = self.login()
        self.assertContains(r, "Merhaba, Mehmet")
        self.assertContains(r, "Henüz randevun yok")
        customer = self.b.customers.get()
        self.assertIsNotNone(customer.verified_at)
        self.assertContains(self.client.get("/ali/"), "Tekrar hoş geldin")   # cihaz hatırlandı

    def test_wrong_code_and_sms_text(self):
        self.client.post("/ali/hesabim/", {"action": "send", "phone": "05321112233"})
        r = self.client.post("/ali/hesabim/", {"action": "verify", "code": "000000"}, follow=True)
        self.assertContains(r, "Kod hatalı")
        self.assertFalse(self.b.customers.exists())
        self.assertIn("giris kodunuz", self.b.messages.get().body)

    def test_history_shows_last_visit_and_services(self):
        customer = get_or_create_customer(self.b, "05321112233", "Mehmet", verified=True)
        now = timezone.now()
        day = next_weekday(1, now - timedelta(days=30))
        tz = timezone.get_current_timezone()
        for weeks, services in ((4, [self.cut]), (2, [self.combo])):
            d = day - timedelta(days=7 * weeks)
            start = timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=11), tzinfo=tz)
            appt = create_appointment(self.b, services, start, customer=customer,
                                      source=Appointment.Source.MANUAL, now=start - timedelta(days=1), notify=False)
            close_appointment(appt, Appointment.Status.COMPLETED)
        r = self.login()
        html = r.content.decode()
        self.assertIn("En son yaptırdıkların", html)
        self.assertIn("Saç + sakal", html)
        self.assertIn("gün önce", html)
        self.assertRegex(html, r"<small>Ziyaret</small><b>2</b>")
        # çıkış
        self.client.post("/ali/hesabim/unut/")
        self.assertContains(self.client.get("/ali/hesabim/"), "Giriş yap ya da kayıt ol")

    def test_panel_customer_summary(self):
        customer = get_or_create_customer(self.b, "05321112233", "Mehmet", verified=True)
        tz = timezone.get_current_timezone()
        base = next_weekday(1, timezone.now() - timedelta(days=60))
        for k in range(3):
            d = base + timedelta(days=14 * k)
            start = timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=11), tzinfo=tz)
            appt = create_appointment(self.b, [self.cut], start, customer=customer,
                                      source=Appointment.Source.MANUAL, now=start - timedelta(days=1), notify=False)
            close_appointment(appt, Appointment.Status.COMPLETED)
        self.client.force_login(self.user)
        html = self.client.get(f"/panel/musteriler/{customer.id}/").content.decode()
        self.assertIn("Son ziyaret", html)
        self.assertIn("14 günde bir", html)
        self.assertIn("Saç kesimi · 3", html)
