"""Örnek dükkân verisi: tekrar çalıştırılabilir olmalı ve ziyaretçinin kaydına dokunmamalı."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core import demo
from core.booking import get_or_create_customer
from core.models import Appointment


class DemoDataTests(TestCase):
    def test_seed_is_rich_and_repeatable(self):
        first = demo.ensure_demo(history_days=6, ahead_days=3)
        b = first["business"]
        self.assertEqual(b.slug, demo.SLUG)
        self.assertEqual(b.staff.count(), len(demo.STAFF))
        self.assertEqual(b.services.count(), len(demo.SERVICES))
        customers = b.customers.count()
        self.assertGreaterEqual(customers, demo.CUSTOMERS)   # baştan gelenler + sonradan katılanlar
        self.assertGreater(first["created"], 60)
        now = timezone.now()
        # geçmişte açık örnek randevu kalmaz; ileride randevu vardır
        self.assertFalse(b.appointments.filter(status="confirmed", end__lt=now).exists())
        self.assertTrue(b.appointments.filter(status="confirmed", start__gt=now).exists())
        self.assertTrue(b.appointments.filter(status="completed", actual_total__gt=0).exists())

        self.assertEqual(b.name, demo.SHOP_NAME)
        # eski adla kurulmuş örnek dükkân yeni ada geçer; sahibi adı değiştirdiyse dokunulmaz
        b.name, b.description = demo.OLD_SHOP
        b.save()
        again = demo.ensure_demo(history_days=6, ahead_days=3)
        b.refresh_from_db()
        self.assertEqual((b.name, b.description), (demo.SHOP_NAME, demo.SHOP_ABOUT))
        b.name = "Benim Dükkânım"
        b.save()
        demo.ensure_demo(history_days=6, ahead_days=3)
        b.refresh_from_db()
        self.assertEqual(b.name, "Benim Dükkânım")
        self.assertEqual(again["created"], 0)          # hedefe ulaşmış güne ekleme yapılmaz
        self.assertEqual(b.staff.count(), len(demo.STAFF))
        self.assertEqual(b.services.count(), len(demo.SERVICES))
        self.assertEqual(b.customers.count(), customers)

    def test_visitor_booking_is_left_alone(self):
        b = demo.ensure_demo(history_days=1, ahead_days=1)["business"]
        visitor = get_or_create_customer(b, "05449998877", "Ziyaretçi", verified=True)
        staff, service = b.staff.first(), b.services.get(name="Saç kesimi")
        past = timezone.now() - timedelta(days=3)
        appt = Appointment.objects.create(business=b, staff=staff, customer=visitor, start=past,
                                          end=past + timedelta(minutes=30), block_end=past + timedelta(minutes=30),
                                          planned_total=service.price)
        demo.ensure_demo(history_days=1, ahead_days=1)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")     # ziyaretçinin denemesi kapatılmaz


class LandingTests(TestCase):
    def test_landing_page_and_demo_link(self):
        html = self.client.get("/").content.decode()
        self.assertIn('href="/panel/kayit/"', html)
        self.assertIn('href="/panel/giris/"', html)
        self.assertIn("css/landing.css?v=", html)
        self.assertNotIn("Örnek dükkânı gez", html)        # örnek dükkân yokken bağlantısı da yok
        demo._shop()
        html = self.client.get("/").content.decode()
        self.assertIn(f'href="/{demo.SLUG}/"', html)
        self.assertIn("Örnek dükkânı gez", html)
