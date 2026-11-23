"""Üyelik ve ödeme, geri bildirim ve ana ekrana eklenebilen uygulama (PWA)."""
from datetime import date, timedelta

from django.core.cache import cache
from django.test import TestCase
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
        self.assertIn("499 ₺", html)
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
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        response = self.client.post("/gorus/", {"sender": "other", "message": "ikinci deneme", "next": "//example.org/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

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
