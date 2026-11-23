"""Üyelik ve ödeme, geri bildirim ve ana ekrana eklenebilen uygulama (PWA)."""
from datetime import date, timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from core import billing, demo
from core.models import Business, Feedback, PlatformSettings, SubscriptionPayment
from core.tests import make_business


class BillingTests(TestCase):
    def setUp(self):
        self.business, self.user = make_business("ali")
        self.today = timezone.localdate()

    def test_add_months_keeps_the_day_or_ends_the_month(self):
        self.assertEqual(billing.add_months(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(billing.add_months(date(2028, 1, 31)), date(2028, 2, 29))
        self.assertEqual(billing.add_months(date(2026, 12, 15)), date(2027, 1, 15))
        self.assertEqual(billing.add_months(date(2026, 11, 23), 3), date(2027, 2, 23))

    def test_trial_then_monthly(self):
        b = self.business
        bill = b.billing
        self.assertTrue(bill["in_trial"])
        self.assertEqual(bill["price"], 499)
        self.assertEqual(bill["due"], b.trial_ends)
        self.assertEqual(bill["days_left"], 14)
        self.assertFalse(bill["warn"])
        # erken ödeyen deneme gününü kaybetmez: dönem deneme bitişinden başlar
        first = billing.record_payment(b)
        b.refresh_from_db()
        self.assertEqual((first.amount, first.period_start, first.period_end),
                         (499, b.trial_ends, billing.add_months(b.trial_ends)))
        self.assertEqual((b.status, b.paid_until), ("active", first.period_end))
        self.assertFalse(b.billing["in_trial"])
        second = billing.record_payment(b)
        b.refresh_from_db()
        self.assertEqual(second.period_start, first.period_end)
        self.assertEqual(b.paid_until, billing.add_months(first.period_end))

    def test_late_payment_starts_on_the_day_it_is_paid(self):
        b = self.business
        b.status, b.trial_ends = "past_due", self.today - timedelta(days=9)
        b.save()
        bill = b.billing
        self.assertTrue(bill["overdue"] and bill["warn"])
        self.assertEqual(bill["days_over"], 9)
        payment = billing.record_payment(b)
        b.refresh_from_db()
        self.assertEqual(payment.period_start, self.today)
        self.assertEqual((b.status, b.paid_until), ("active", billing.add_months(self.today)))

    def test_due_day_returns_after_a_short_month(self):
        """31 Ocak'ta başlayan döngü Şubat'ta 28'ine iner, Mart'ta yeniden 31'ine döner."""
        b = self.business
        b.trial_ends = date(2027, 1, 31)
        b.save()
        ends = [billing.record_payment(b, paid_on=date(2027, 1, 31)).period_end for _ in range(4)]
        self.assertEqual(ends, [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30), date(2027, 5, 31)])

    def test_deleting_or_correcting_a_payment_moves_the_membership_back(self):
        b = self.business
        first = billing.record_payment(b)
        second = billing.record_payment(b)
        b.refresh_from_db()
        self.assertEqual(b.paid_until, second.period_end)
        second.delete()                                   # yanlış girilen kayıt silinir
        b.refresh_from_db()
        self.assertEqual(b.paid_until, first.period_end)
        first.period_end = first.period_end + timedelta(days=10)   # dönem elle düzeltilir
        first.save()
        b.refresh_from_db()
        self.assertEqual(b.paid_until, first.period_end)
        first.amount, first.period_end = None, None       # boşaltılan alan yeniden doldurulur
        first.save()
        self.assertEqual(first.amount, 499)
        self.assertIsNotNone(first.period_end)
        SubscriptionPayment.objects.filter(business=b).delete()   # toplu silme de geri alır
        b.refresh_from_db()
        self.assertIsNone(b.paid_until)
        self.client.force_login(self.user)
        self.assertIn("Henüz ödeme kaydı yok", self.client.get("/panel/ayarlar/uyelik/").content.decode())
        b.delete()                                        # işletme silinirken ödemeleri sorun çıkarmaz

    def test_payment_dates_are_checked_in_the_admin_form(self):
        payment = SubscriptionPayment(business=self.business, paid_on=self.today + timedelta(days=30))
        with self.assertRaises(ValidationError):
            payment.full_clean()
        payment = SubscriptionPayment(business=self.business, paid_on=self.today, period_start=self.today,
                                      period_end=self.today, amount=-5)
        with self.assertRaises(ValidationError) as caught:
            payment.full_clean()
        self.assertEqual(set(caught.exception.message_dict), {"amount", "period_end"})

    def test_a_shop_made_active_by_hand_is_not_called_overdue(self):
        """Ödeme kaydı olmadan aktif yapılmış hesap: eski deneme tarihinden gecikme sayılmaz."""
        b = self.business
        b.status, b.trial_ends = "active", self.today - timedelta(days=200)
        b.save()
        self.assertEqual((b.billing["due"], b.billing["warn"], b.billing["overdue"]), (None, False, False))
        self.client.force_login(self.user)
        self.assertNotIn("gün önce geçti", self.client.get("/panel/").content.decode())
        self.assertIn("Ödeme günün henüz belirlenmedi", self.client.get("/panel/ayarlar/uyelik/").content.decode())
        payment = billing.record_payment(b)               # ilk kayıt dönemi ödeme gününden başlatır
        self.assertEqual(payment.period_start, self.today)

    def test_a_free_shop_gets_no_reminder(self):
        b = self.business
        b.monthly_price, b.trial_ends = 0, self.today + timedelta(days=2)
        b.save()
        self.assertFalse(b.billing["warn"])

    def test_overdue_wording(self):
        b = self.business
        b.trial_ends = self.today - timedelta(days=90)
        b.save()
        billing.record_payment(b, paid_on=self.today - timedelta(days=60))   # dönemi yaklaşık bir ay önce bitti
        b.refresh_from_db()
        self.assertTrue(b.billing["overdue"])
        self.client.force_login(self.user)
        html = self.client.get("/panel/ayarlar/uyelik/").content.decode()
        self.assertIn("Geciken ödeme", html)
        self.assertNotIn("Sonraki ödeme", html)
        b.status = "past_due"
        b.save()
        self.assertIn("Üyelik ödemen bize ulaşmadı", self.client.get("/panel/").content.decode())

    def test_price_comes_from_platform_settings_unless_the_shop_has_its_own(self):
        settings = PlatformSettings.load()
        settings.monthly_price = 650
        settings.save()
        self.assertEqual(PlatformSettings.objects.count(), 1)
        self.assertEqual(self.business.billing["price"], 650)
        self.business.monthly_price = 300
        self.business.save()
        self.assertEqual(self.business.billing["price"], 300)
        self.assertEqual(billing.record_payment(self.business).amount, 300)

    def test_a_suspended_shop_stays_suspended_when_a_payment_is_entered(self):
        self.business.status = "suspended"
        self.business.save()
        billing.record_payment(self.business)
        self.business.refresh_from_db()
        self.assertEqual(self.business.status, "suspended")   # kapalı hesabı yalnızca yönetim açar

    def test_membership_page(self):
        self.assertEqual(self.client.get("/panel/ayarlar/uyelik/").status_code, 302)   # giriş ister
        self.client.force_login(self.user)
        html = self.client.get("/panel/ayarlar/uyelik/").content.decode()
        self.assertIn("Üyelik ve ödeme", html)
        self.assertIn("499&nbsp;₺", html)
        self.assertIn("Deneme bitişi", html)
        self.assertIn("Henüz ödeme kaydı yok", html)
        self.assertIn("Ödeme yöntemi henüz eklenmedi", html)
        settings = PlatformSettings.load()
        settings.payment_note = "IBAN TR00 0000\nAçıklama: dükkân adı"
        settings.save()
        billing.record_payment(self.business, note="ilk ay")
        html = self.client.get("/panel/ayarlar/uyelik/").content.decode()
        self.assertIn("IBAN TR00 0000<br>Açıklama: dükkân adı", html)
        self.assertIn("Sonraki ödeme", html)
        self.assertIn("Havale / EFT", html)
        self.assertNotIn("Henüz ödeme kaydı yok", html)

    def test_reminder_shows_in_the_last_days_only(self):
        self.client.force_login(self.user)
        self.assertNotIn("Deneme süren", self.client.get("/panel/").content.decode())
        self.business.trial_ends = self.today + timedelta(days=3)
        self.business.save()
        html = self.client.get("/panel/").content.decode()
        self.assertIn("Deneme süren 3 gün sonra bitiyor.", html)
        self.assertIn("/panel/ayarlar/uyelik/", html)
        billing.record_payment(self.business)
        self.assertNotIn("Deneme süren", self.client.get("/panel/").content.decode())

    def test_other_shops_payments_are_not_shown(self):
        other, _ = make_business("veli", "b@example.com")
        billing.record_payment(other, note="başkasının ödemesi")
        self.client.force_login(self.user)
        self.assertIn("Henüz ödeme kaydı yok", self.client.get("/panel/ayarlar/uyelik/").content.decode())

    def test_demo_shop_has_a_paid_membership_with_history(self):
        first = demo.ensure_demo(history_days=2, ahead_days=1)["business"]
        self.assertEqual(first.status, "active")
        self.assertGreaterEqual((first.paid_until - self.today).days, 10)
        count = first.payments.count()
        self.assertGreaterEqual(count, 3)
        demo.ensure_demo(history_days=2, ahead_days=1)
        self.assertEqual(SubscriptionPayment.objects.filter(business=first).count(), count)   # tekrar çalışınca çoğalmaz
        Business.objects.filter(pk=first.pk).update(paid_until=None)   # yönetim panelinden elle boşaltılmış
        again = demo.ensure_demo(history_days=2, ahead_days=1)["business"]
        self.assertGreaterEqual((again.paid_until - self.today).days, 10)


class FeedbackTests(TestCase):
    def setUp(self):
        cache.clear()
        self.business, self.user = make_business("ali")

    def test_customer_writes_from_a_shop_page(self):
        page = self.client.get("/ali/").content.decode()
        self.assertIn("/gorus/?d=ali&amp;next=/ali/", page)
        form = self.client.get("/gorus/?d=ali&next=/ali/").content.decode()
        self.assertIn('value="customer" checked', form)
        response = self.client.post("/gorus/", {"d": "ali", "next": "/ali/", "sender": "customer",
                                                "message": "Saat seçimi çok kolay olmuş.", "name": "Can", "contact": ""},
                                    follow=True)
        self.assertRedirects(response, "/ali/")
        self.assertTrue("görüşün bize ulaştı" in response.content.decode(), "teşekkür iletisi dönülen sayfada görünür")
        saved = Feedback.objects.get()
        self.assertEqual((saved.sender, saved.business, saved.user, saved.name, saved.page),
                         ("customer", self.business, None, "Can", "/ali/"))

    def test_owner_writes_from_the_panel(self):
        self.client.force_login(self.user)
        self.assertIn("/gorus/?next=/panel/ayarlar/", self.client.get("/panel/ayarlar/").content.decode())
        self.assertIn('value="owner" checked', self.client.get("/gorus/").content.decode())
        response = self.client.post("/gorus/", {"next": "/panel/ayarlar/", "sender": "owner",
                                                "message": "Haftalık rapor da olsa iyi olur."})
        self.assertRedirects(response, "/panel/ayarlar/")
        saved = Feedback.objects.get()
        self.assertEqual((saved.sender, saved.business, saved.user), ("owner", self.business, self.user))

    def test_empty_trap_and_flood(self):
        response = self.client.post("/gorus/", {"sender": "other", "message": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Görüşünü yazmadan gönderemeyiz", response.content.decode())
        # tuzak alanı dolduran otomatik gönderim kaydedilmez ama fark ettirilmez
        self.client.post("/gorus/", {"sender": "other", "message": "reklam reklam", "website": "http://x"})
        self.assertEqual(Feedback.objects.count(), 0)
        for i in range(5):
            self.client.post("/gorus/", {"sender": "other", "message": f"görüş numara {i}"})
        self.assertEqual(Feedback.objects.count(), 5)
        response = self.client.post("/gorus/", {"sender": "other", "message": "altıncı görüş"})
        self.assertEqual(Feedback.objects.count(), 5)
        self.assertIn("çok fazla gönderim", response.content.decode())

    def test_return_address_stays_on_this_site(self):
        response = self.client.post("/gorus/", {"sender": "other", "message": "dışarı gönderme denemesi",
                                                "next": "https://example.org/"})
        self.assertRedirects(response, "/gorus/", fetch_redirect_response=False)
        # satır sonu, boşluk, ters eğik çizgi, boş karakter, çift eğik çizgi: hepsi reddedilir
        for bad in ("//example.org/", "/\r//example.org/x", "/\r\n//example.org", "/\t/example.org", "/\\example.org",
                    "/a\x00b", "/ /x", "javascript:alert(1)", "/" + "a" * 300):
            page = self.client.get("/gorus/", {"next": bad})
            self.assertEqual(page.status_code, 200, repr(bad))
            self.assertIn('<a class="tap" href="/">', page.content.decode(), repr(bad))
        self.assertEqual(self.client.get("/gorus/", {"d": "\x00"}).status_code, 200)   # bozuk dükkân adresi hata vermez
        self.assertEqual(self.client.get("/gorus/", {"d": "a" * 500}).status_code, 200)
        page = self.client.get("/gorus/", {"d": "ali", "next": "/ali/randevu/saat/?h=1&b=0"})
        self.assertIn('href="/ali/randevu/saat/?h=1&amp;b=0"', page.content.decode())   # seçim taşıyan adres korunur

    def test_thank_you_is_shown_where_the_visitor_lands(self):
        """Ana sayfa ileti göstermez: oradan gelen ziyaretçi teşekkürü geri bildirim sayfasında görür."""
        response = self.client.post("/gorus/", {"sender": "other", "message": "ana sayfadan gelen görüş"}, follow=True)
        self.assertRedirects(response, "/gorus/")
        self.assertTrue("görüşün bize ulaştı" in response.content.decode())
        self.assertEqual(Feedback.objects.count(), 1)

    def test_booking_selection_survives_a_visit_to_the_feedback_page(self):
        service = self.business.services.first()
        html = self.client.get(f"/ali/randevu/saat/?h={service.id}&b=0").content.decode()
        self.assertIn(f"next=/ali/randevu/saat/%3Fh%3D{service.id}%26b%3D0", html)

    @override_settings(DEBUG=False)
    def test_changing_the_address_header_does_not_lift_the_limit(self):
        for i in range(70):
            self.client.post("/gorus/", {"sender": "other", "message": f"sahte adresli görüş {i}"},
                             HTTP_X_FORWARDED_FOR=f"10.9.{i}.1, 203.0.113.7")
        self.assertEqual(Feedback.objects.count(), 60)   # site geneli saatlik sınır

    def test_new_addresses_cannot_be_taken_as_shop_addresses(self):
        from core.models import RESERVED_SLUGS
        self.assertTrue({"gorus", "cevrimdisi"} <= RESERVED_SLUGS)


class AppShellTests(TestCase):
    def setUp(self):
        self.business, self.user = make_business("ali")

    def test_panel_app(self):
        response = self.client.get("/uygulama.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual((data["start_url"], data["scope"], data["display"]), ("/panel/", "/", "standalone"))
        self.assertLessEqual(len(data["short_name"]), 12)
        self.assertEqual({icon["purpose"] for icon in data["icons"]}, {"any", "maskable"})
        self.assertIn('<link rel="manifest" href="/uygulama.webmanifest">', self.client.get("/panel/giris/").content.decode())

    def test_each_shop_is_its_own_app(self):
        data = self.client.get("/ali/uygulama.webmanifest").json()
        self.assertEqual((data["name"], data["start_url"], data["scope"], data["id"]),
                         (self.business.name, "/ali/", "/ali/", "/ali/"))
        html = self.client.get("/ali/").content.decode()
        self.assertIn('<link rel="manifest" href="/ali/uygulama.webmanifest">', html)
        self.assertIn(f'name="apple-mobile-web-app-title" content="{self.business.name}"', html)
        self.assertEqual(self.client.get("/yok/uygulama.webmanifest").status_code, 404)

    def test_home_screen_label_keeps_the_distinctive_words(self):
        from core.pwa import _short
        for name, label in (("Örnek Kuaför", "Örnek Kuaför"), ("Makas Erkek Kuaförü", "Makas"),
                            ("Ahmet Usta Berber Salonu", "Ahmet Usta"), ("Deneme Dükkânı", "Deneme"),
                            ("Kuaför Randevu", "Randevu"), ("Erkek Kuaförü Salonu", "Erkek"),
                            ("Abdurrahmangazi Kuaför", "Abdurrahmang")):
            self.assertEqual(_short(name), label, name)
            self.assertLessEqual(len(_short(name)), 12)

    def test_icons_exist(self):
        from django.contrib.staticfiles import finders
        for name in ("icon.svg", "icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png", "favicon-32.png"):
            self.assertTrue(finders.find(f"icons/{name}"), name)

    def test_service_worker_only_answers_when_offline(self):
        response = self.client.get("/sw.js")
        self.assertTrue(response["Content-Type"].startswith("text/javascript"))
        self.assertEqual(response["Cache-Control"], "no-cache")
        js = response.content.decode()
        self.assertIn("'/cevrimdisi/'", js)
        self.assertIn("request.mode !== 'navigate' || request.method !== 'GET'", js)   # form gönderimine dokunmaz
        self.assertNotIn("cache.put", js)                                              # sayfa saklamaz
        page = self.client.get("/cevrimdisi/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Bağlantı yok", page.content.decode())
        self.assertIn("js/pwa.js", self.client.get("/").content.decode())
