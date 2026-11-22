import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import otp, reports
from core.availability import day_slots, merged_slots
from core.booking import (BookingError, cancel_appointment, close_appointment,
                          create_appointment, get_or_create_customer)
from core.models import Appointment, Customer, MessageLog, Service, Staff, TimeOff
from core.setup import create_business
from core.sms import send_due

TZ = ZoneInfo("Europe/Istanbul")
User = get_user_model()


def make_business(slug="ornek", email="a@example.com", closed=6):
    user = User.objects.create_user(username=email, email=email, password="gizli-sifre-1")
    return create_business(user, f"Berber {slug}", slug, "Ali", closed_weekday=closed), user


def next_weekday(weekday, now):
    """now'dan sonraki ilk `weekday` günü (en az 1 gün sonrası)."""
    day = now.astimezone(TZ).date() + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.user = make_business()
        self.staff = self.b.staff.get()
        self.cut = self.b.services.get(name="Saç kesimi")       # 30 dk
        self.combo = self.b.services.get(name="Saç + sakal")    # 45 dk
        self.now = timezone.now()
        self.day = next_weekday(1, self.now)  # salı, açık gün

    def at(self, h, m=0, day=None):
        return datetime.combine(day or self.day, time(h, m), tzinfo=TZ)

    def customer(self, phone="05321112233", name="Mehmet"):
        return get_or_create_customer(self.b, phone, name, verified=True)


class AvailabilityTests(Base):
    def test_open_day_grid(self):
        slots = day_slots(self.b, [self.staff], self.day, 30, now=self.now)[self.staff.id]
        self.assertEqual(slots[0], self.at(9))
        self.assertEqual(slots[-1], self.at(19, 30))   # 20:00'de biter
        self.assertEqual(len(slots), 43)               # 09:00-19:30, 15 dk ızgara

    def test_closed_day_has_no_slots(self):
        sunday = next_weekday(6, self.now)
        self.assertEqual(day_slots(self.b, [self.staff], sunday, 30, now=self.now)[self.staff.id], [])

    def test_break_and_timeoff_remove_slots(self):
        h = self.b.hours.get(weekday=1)
        h.break_start, h.break_end = time(13), time(14)
        h.save()
        TimeOff.objects.create(business=self.b, start=self.at(16), end=self.at(17))
        slots = day_slots(self.b, [self.staff], self.day, 30, now=self.now)[self.staff.id]
        self.assertIn(self.at(12, 30), slots)
        self.assertNotIn(self.at(12, 45), slots)   # molaya taşar
        self.assertNotIn(self.at(13, 30), slots)
        self.assertIn(self.at(14), slots)
        self.assertNotIn(self.at(15, 45), slots)   # kapalı saate taşar
        self.assertNotIn(self.at(16, 30), slots)
        self.assertIn(self.at(17), slots)

    def test_existing_appointment_and_buffer_block_slots(self):
        self.cut.buffer = 15
        self.cut.save()
        create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        slots = day_slots(self.b, [self.staff], self.day, 30, 15, now=self.now)[self.staff.id]
        self.assertIn(self.at(9, 15), slots)       # 09:15-09:45 + 15 dk pay = 10:00
        self.assertNotIn(self.at(9, 30), slots)
        self.assertNotIn(self.at(10, 30), slots)   # önceki randevunun hazırlık payı
        self.assertIn(self.at(10, 45), slots)

    def test_min_notice_and_horizon(self):
        today = self.now.astimezone(TZ).date()
        noon = datetime.combine(today, time(12), tzinfo=TZ)
        if today.weekday() == 6:
            self.b.hours.filter(weekday=6).update(closed=False)
        slots = day_slots(self.b, [self.staff], today, 30, now=noon)[self.staff.id]
        self.assertEqual(slots[0], noon + timedelta(hours=1))  # en az 60 dk sonrası
        far = today + timedelta(days=self.b.max_days_ahead + 1)
        self.assertEqual(merged_slots(day_slots(self.b, [self.staff], far, 30, now=noon)), [])

    def test_cancelled_appointment_frees_slot(self):
        appt = create_appointment(self.b, [self.cut], self.at(11), customer=self.customer(), now=self.now)
        cancel_appointment(appt, by_customer=True, now=self.now)
        self.assertIn(self.at(11), day_slots(self.b, [self.staff], self.day, 30, now=self.now)[self.staff.id])


class BookingTests(Base):
    def test_database_rejects_overlap(self):
        """Kontrol uygulamada atlansa bile veritabanı çakışmayı reddeder."""
        create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Appointment.objects.create(business=self.b, staff=self.staff, start=self.at(10, 15),
                                       end=self.at(10, 45), block_end=self.at(10, 45))

    def test_second_booking_for_same_slot_fails(self):
        create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        with self.assertRaisesMessage(BookingError, "az önce doldu"):
            create_appointment(self.b, [self.cut], self.at(10),
                               customer=self.customer("05329998877"), now=self.now)

    def test_any_staff_picks_free_barber(self):
        mert = Staff.objects.create(business=self.b, name="Mert")
        mert.services.set(self.b.services.all())
        a1 = create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        a2 = create_appointment(self.b, [self.cut], self.at(10),
                                customer=self.customer("05329998877"), now=self.now)
        self.assertNotEqual(a1.staff_id, a2.staff_id)
        with self.assertRaises(BookingError):
            create_appointment(self.b, [self.cut], self.at(10),
                               customer=self.customer("05327776655"), now=self.now)

    def test_staff_without_skill_is_not_offered(self):
        mert = Staff.objects.create(business=self.b, name="Mert")
        mert.services.set([self.cut])
        with self.assertRaisesMessage(BookingError, "yapabilen berber"):
            create_appointment(self.b, [self.combo], self.at(10), staff=mert,
                               customer=self.customer(), now=self.now)

    def test_price_is_copied(self):
        appt = create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        self.cut.price = 999
        self.cut.save()
        appt.refresh_from_db()
        self.assertEqual(appt.planned_total, 400)
        self.assertEqual(appt.items.get().price, 400)

    def test_open_appointment_limits(self):
        c = self.customer()
        create_appointment(self.b, [self.cut], self.at(10), customer=c, now=self.now)
        with self.assertRaisesMessage(BookingError, "zaten bir randevunuz"):
            create_appointment(self.b, [self.cut], self.at(15), customer=c, now=self.now)
        other = self.day + timedelta(days=1)
        create_appointment(self.b, [self.cut], self.at(10, day=other), customer=c, now=self.now)
        with self.assertRaisesMessage(BookingError, "sınırda"):
            create_appointment(self.b, [self.cut], self.at(10, day=other + timedelta(days=1)),
                               customer=c, now=self.now)

    def test_blocked_customer_and_paused_business(self):
        c = self.customer()
        c.blocked = True
        c.save()
        with self.assertRaises(BookingError):
            create_appointment(self.b, [self.cut], self.at(10), customer=c, now=self.now)
        self.b.status = "past_due"
        self.b.save()
        with self.assertRaisesMessage(BookingError, "online randevu almıyor"):
            create_appointment(self.b, [self.cut], self.at(10),
                               customer=self.customer("05329998877"), now=self.now)
        # Kuaför elle girmeye devam edebilir
        create_appointment(self.b, [self.cut], self.at(10), source="manual", now=self.now)

    def test_service_of_other_business_rejected(self):
        other, _ = make_business("diger", "b@example.com")
        with self.assertRaises(BookingError):
            create_appointment(self.b, [other.services.first()], self.at(10),
                               customer=self.customer(), now=self.now)

    def test_close_and_no_show_counter(self):
        c = self.customer()
        appt = create_appointment(self.b, [self.cut], self.at(10), customer=c, now=self.now)
        close_appointment(appt, "no_show")
        c.refresh_from_db()
        self.assertEqual(c.no_show_count, 1)
        close_appointment(appt, "completed", amount=450, payment="card")  # düzeltme
        c.refresh_from_db()
        appt.refresh_from_db()
        self.assertEqual((c.no_show_count, appt.actual_total, appt.payment), (0, 450, "card"))

    def test_customer_cancel_deadline(self):
        appt = create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        late = appt.start - timedelta(minutes=30)
        with self.assertRaisesMessage(BookingError, "İptal süresi geçti"):
            cancel_appointment(appt, by_customer=True, now=late)
        cancel_appointment(appt, by_customer=False, now=late)   # kuaför her zaman iptal edebilir
        self.assertEqual(appt.status, "cancelled_business")
        self.assertTrue(appt.messages.filter(kind="cancel", status="sent").exists())


class MessageTests(Base):
    def test_confirmation_now_reminder_later(self):
        start = self.at(10, day=self.day + timedelta(days=7))
        appt = create_appointment(self.b, [self.cut], start, customer=self.customer(), now=self.now)
        confirm = appt.messages.get(kind="confirm")
        reminder = appt.messages.get(kind="reminder")
        self.assertEqual(confirm.status, "sent")
        self.assertEqual((reminder.status, reminder.scheduled_at), ("queued", start - timedelta(hours=24)))
        self.assertTrue(confirm.body.isascii())          # tek SMS boyutunda kalsın
        self.assertEqual(confirm.segments, 1)
        self.assertEqual(send_due(now=start - timedelta(hours=25)), 0)
        self.assertEqual(send_due(now=start - timedelta(hours=23)), 1)
        self.b.refresh_from_db()
        self.assertEqual(self.b.sms_credit, 98)

    def test_cancelled_appointment_sends_no_reminder(self):
        start = self.at(10, day=self.day + timedelta(days=7))
        appt = create_appointment(self.b, [self.cut], start, customer=self.customer(), now=self.now)
        cancel_appointment(appt, by_customer=True, now=self.now)
        self.assertEqual(send_due(now=start - timedelta(hours=1)), 0)
        self.assertEqual(appt.messages.get(kind="reminder").status, "cancelled")

    def test_manual_booking_reminder_follows_setting(self):
        c = self.customer()
        a = create_appointment(self.b, [self.cut], self.at(10), customer=c, source="manual", now=self.now)
        self.assertTrue(a.messages.exists())
        self.b.remind_manual = False
        self.b.save()
        a2 = create_appointment(self.b, [self.cut], self.at(12), customer=c, source="manual", now=self.now)
        self.assertFalse(a2.messages.exists())

    @override_settings(SMS_BACKEND="core.sms.FailingBackend")
    def test_provider_failure_does_not_break_booking(self):
        appt = create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(), now=self.now)
        self.assertEqual(appt.messages.get(kind="confirm").status, "failed")
        self.b.refresh_from_db()
        self.assertEqual(self.b.sms_credit, 100)


@override_settings(SMS_SHOW_CODE=True)
class OtpTests(Base):
    def test_phone_normalisation(self):
        for raw in ("0532 111 22 33", "+90 532 111 22 33", "5321112233", "905321112233"):
            self.assertEqual(otp.normalize_phone(raw), "05321112233")
        for raw in ("0212 111 22 33", "12345", "", "+49 151 1234567", "053211122334"):
            self.assertIsNone(otp.normalize_phone(raw))

    def test_code_is_single_use_and_hashed(self):
        code = otp.request_code(self.b, "05321112233", "1.1.1.1")
        self.assertRegex(code, r"^\d{6}$")
        self.assertNotIn(code, str(cache.get(f"otp:code:{self.b.id}:05321112233")))
        self.assertTrue(otp.check_code(self.b, "05321112233", code))
        with self.assertRaises(otp.OtpError):
            otp.check_code(self.b, "05321112233", code)

    def test_five_wrong_attempts_invalidate_code(self):
        code = otp.request_code(self.b, "05321112233", "1.1.1.1")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            with self.assertRaisesMessage(otp.OtpError, "hatalı"):
                otp.check_code(self.b, "05321112233", wrong)
        with self.assertRaisesMessage(otp.OtpError, "Çok fazla"):
            otp.check_code(self.b, "05321112233", code)

    def test_code_bound_to_phone(self):
        code = otp.request_code(self.b, "05321112233", "1.1.1.1")
        with self.assertRaises(otp.OtpError):
            otp.check_code(self.b, "05329998877", code)

    @override_settings(OTP_RESEND_SECONDS=0)
    def test_per_phone_and_per_ip_limits(self):
        for _ in range(3):
            otp.request_code(self.b, "05321112233", "1.1.1.1")
        with self.assertRaisesMessage(otp.OtpError, "çok fazla kod"):
            otp.request_code(self.b, "05321112233", "2.2.2.2")
        for i in range(7):   # aynı IP'den 3 + 7 = 10 istek
            otp.request_code(self.b, f"0532000000{i}", "1.1.1.1")
        with self.assertRaisesMessage(otp.OtpError, "Çok fazla deneme"):
            otp.request_code(self.b, "05320000099", "1.1.1.1")

    def test_resend_cooldown(self):
        otp.request_code(self.b, "05321112233", "1.1.1.1")
        with self.assertRaisesMessage(otp.OtpError, "az önce"):
            otp.request_code(self.b, "05321112233", "1.1.1.1")
        self.assertEqual(MessageLog.objects.filter(kind="otp").count(), 1)


@override_settings(SMS_SHOW_CODE=True)
class PublicFlowTests(Base):
    def first_slot(self):
        page = self.client.get(f"/ornek/randevu/saat/?h={self.cut.id}&b=0")
        self.assertEqual(page.status_code, 200)
        return int(re.search(r"t=(\d+)", page.content.decode()).group(1))

    def book(self, phone="0532 111 22 33", client=None):
        client = client or self.client
        t = self.first_slot()
        url = f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t}"
        r = client.post(url, {"name": "Mehmet", "phone": phone}, follow=True)
        self.assertRedirects(r, "/ornek/randevu/kod/")
        code = re.search(r"Kod: (\d{6})", r.content.decode()).group(1)
        return client.post("/ornek/randevu/kod/", {"code": code}), t

    def test_full_booking_then_known_device_skips_code(self):
        self.assertContains(self.client.get("/ornek/"), "Saç kesimi")
        self.assertRedirects(self.client.get(f"/ornek/randevu/?devam=1&h={self.cut.id}&b=0"),
                             f"/ornek/randevu/saat/?h={self.cut.id}&b=0")
        response, t = self.book()
        appt = Appointment.objects.get()
        self.assertRedirects(response, f"/ornek/r/{appt.token}/")
        self.assertEqual(int(appt.start.timestamp()), t)
        self.assertEqual(appt.customer.phone, "05321112233")
        self.assertIsNotNone(appt.customer.verified_at)
        self.assertFalse(appt.customer.marketing_consent)   # izin kodla birlikte alınmaz
        self.assertContains(self.client.get(f"/ornek/r/{appt.token}/"), "Randevun alındı")

        # Aynı cihaz, başka gün: kod istenmez, yeni doğrulama SMS'i gitmez
        cancel_appointment(appt, by_customer=True)
        t2 = self.first_slot()
        details = self.client.get(f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t2}")
        self.assertContains(details, "tekrar kod istenmez")
        r = self.client.post(f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t2}",
                             {"known": "1", "name": "Mehmet"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Appointment.objects.filter(status="confirmed").count(), 1)
        self.assertEqual(MessageLog.objects.filter(kind="otp").count(), 1)
        self.assertContains(self.client.get("/ornek/hesabim/"), "Mehmet")

    def test_wrong_code_creates_nothing(self):
        t = self.first_slot()
        self.client.post(f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t}",
                         {"name": "Mehmet", "phone": "05321112233"})
        r = self.client.post("/ornek/randevu/kod/", {"code": "abc"})
        self.assertContains(r, "Kod hatalı")
        self.assertFalse(Appointment.objects.exists())

    def test_invalid_phone_sends_no_sms(self):
        t = self.first_slot()
        r = self.client.post(f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t}",
                             {"name": "Mehmet", "phone": "0212 111 22 33"})
        self.assertContains(r, "Geçerli bir cep numarası")
        self.assertFalse(MessageLog.objects.exists())

    def test_verify_page_requires_pending_booking(self):
        self.assertRedirects(self.client.get("/ornek/randevu/kod/"), "/ornek/randevu/")

    def test_tampered_time_is_rejected(self):
        """Adres çubuğundaki saat değiştirilse de kurallar sunucuda uygulanır."""
        sunday = next_weekday(6, self.now)
        t = int(self.at(3, day=sunday).timestamp())   # kapalı gün, gece 03:00
        self.client.post(f"/ornek/randevu/bilgi/?h={self.cut.id}&b=0&t={t}",
                         {"name": "Mehmet", "phone": "05321112233"})
        code = MessageLog.objects.get(kind="otp").body
        code = re.search(r"\d{6}", code).group(0)
        self.client.post("/ornek/randevu/kod/", {"code": code})
        self.assertFalse(Appointment.objects.exists())

    def test_customer_cancel_and_consent(self):
        response, _ = self.book()
        appt = Appointment.objects.get()
        self.client.post(f"/ornek/r/{appt.token}/izin/", {"consent": "1"})
        appt.customer.refresh_from_db()
        self.assertTrue(appt.customer.marketing_consent)
        self.assertEqual(self.client.get(f"/ornek/r/{appt.token}/takvim.ics").status_code, 200)
        self.client.post(f"/ornek/r/{appt.token}/iptal/")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "cancelled_customer")

    def test_unknown_token_and_suspended_business(self):
        self.assertEqual(self.client.get("/ornek/r/yanlis-token/").status_code, 404)
        self.b.status = "suspended"
        self.b.save()
        self.assertEqual(self.client.get("/ornek/").status_code, 404)

    def test_device_cookie_does_not_cross_businesses(self):
        other, _ = make_business("diger", "b@example.com")
        self.book()
        self.assertContains(self.client.get("/diger/hesabim/"), "doğrulanmış bir numara yok")
        self.assertFalse(Customer.objects.filter(business=other).exists())


class PanelTests(Base):
    def setUp(self):
        super().setUp()
        self.other, self.other_user = make_business("diger", "b@example.com")
        self.client.login(username="a@example.com", password="gizli-sifre-1")
        self.appt = create_appointment(self.b, [self.cut], self.at(10), customer=self.customer(),
                                       now=self.now)
        self.foreign = create_appointment(
            self.other, [self.other.services.first()], self.at(10),
            customer=get_or_create_customer(self.other, "05440001122", "Yabancı Müşteri"), now=self.now)

    def test_login_required(self):
        self.client.logout()
        for name in ("today", "calendar", "customers", "report", "settings"):
            self.assertEqual(self.client.get(reverse(f"panel:{name}")).status_code, 302)

    def test_pages_render(self):
        for url in ("/panel/", f"/panel/takvim/?g={self.day}", "/panel/musteriler/",
                    "/panel/raporlar/", "/panel/ayarlar/", "/panel/ayarlar/saatler/",
                    "/panel/ayarlar/hizmet/", "/panel/ayarlar/personel/",
                    f"/panel/musteriler/{self.appt.customer_id}/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_tenant_isolation(self):
        """Bir kuaför başka kuaförün müşterisini, randevusunu ya da ayarını göremez, değiştiremez."""
        self.assertNotContains(self.client.get("/panel/musteriler/"), "Yabancı Müşteri")
        self.assertNotContains(self.client.get(f"/panel/takvim/?g={self.day}"), "Yabancı Müşteri")
        self.assertEqual(self.client.get(f"/panel/musteriler/{self.foreign.customer_id}/").status_code, 404)
        self.assertEqual(self.client.post(f"/panel/randevu/{self.foreign.id}/kapat/",
                                          {"status": "completed"}).status_code, 404)
        self.assertEqual(self.client.post(f"/panel/randevu/{self.foreign.id}/iptal/").status_code, 404)
        foreign_service = self.other.services.first()
        self.assertEqual(self.client.get(f"/panel/ayarlar/hizmet/{foreign_service.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/panel/ayarlar/personel/{self.other.staff.get().id}/").status_code, 404)
        # Başka dükkânın hizmetiyle ya da berberiyle randevu açılamaz
        self.client.post("/panel/takvim/ekle/", {"date": str(self.day), "time": "15:00",
                                                  "h": foreign_service.id, "b": "0"})
        self.assertEqual(self.client.post("/panel/takvim/ekle/", {
            "date": str(self.day), "time": "15:00", "h": self.cut.id,
            "b": self.other.staff.get().id}).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, "confirmed")
        self.assertEqual(Appointment.objects.filter(business=self.b).count(), 1)

    def test_close_from_panel(self):
        self.client.post(f"/panel/randevu/{self.appt.id}/kapat/",
                         {"status": "completed", "amount": "450", "payment": "card"})
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.status, self.appt.actual_total), ("completed", 450))

    def test_manual_booking_and_walkin(self):
        self.client.post("/panel/takvim/ekle/", {"date": str(self.day), "time": "15:00",
                                                  "h": self.cut.id, "b": "0",
                                                  "name": "Arayan", "phone": "0533 444 55 66"})
        manual = Appointment.objects.get(source="manual")
        self.assertEqual(manual.start, self.at(15))
        self.assertEqual(manual.customer.name, "Arayan")
        self.assertIsNone(manual.customer.verified_at)
        r = self.client.post("/panel/takvim/ekle/", {"date": str(self.day), "time": "15:15",
                                                      "h": self.cut.id, "b": "0"}, follow=True)
        self.assertContains(r, "Bu saat dolu")
        self.client.post("/panel/randevusuz/", {"h": self.cut.id, "b": "0"})
        walkin = Appointment.objects.get(source="walkin")
        self.assertIsNone(walkin.customer)
        self.assertFalse(walkin.messages.exists())

    def test_timeoff_blocks_online_slots(self):
        self.client.post("/panel/takvim/kapat/", {"date": str(self.day), "from": "14:00",
                                                   "to": "16:00", "b": "0", "reason": "izin"})
        slots = day_slots(self.b, [self.staff], self.day, 30, now=self.now)[self.staff.id]
        self.assertNotIn(self.at(14, 30), slots)

    def test_settings_and_hours_save(self):
        r = self.client.post("/panel/ayarlar/hizmet/", {"name": "Çocuk tıraşı", "duration": 20,
                                                         "buffer": 0, "price": 200, "order": 5,
                                                         "active": "on"})
        self.assertEqual(r.status_code, 302)
        new = Service.objects.get(name="Çocuk tıraşı")
        self.assertEqual(new.business, self.b)
        self.assertIn(new, self.staff.services.all())
        data = {}
        for wd in range(7):
            data.update({f"open_{wd}": "10:00", f"close_{wd}": "19:00"})
        data["closed_0"] = "1"
        self.client.post("/panel/ayarlar/saatler/", data)
        self.assertTrue(self.b.hours.get(weekday=0).closed)
        self.assertEqual(self.b.hours.get(weekday=6).open, time(10))
        self.assertEqual(self.other.hours.get(weekday=6).closed, True)

    def test_signup_creates_ready_business(self):
        self.client.logout()
        r = self.client.post("/panel/kayit/", {
            "business_name": "Yıldız Berber", "slug": "Yıldız Berber", "owner_name": "Can",
            "closed_weekday": 6, "open_at": "09:00", "close_at": "20:00",
            "email": "yeni@example.com", "password": "uzun-bir-sifre-9"})
        self.assertRedirects(r, "/panel/")
        self.assertContains(self.client.get("/yildiz-berber/"), "Saç + sakal")
        self.client.logout()
        r = self.client.post("/panel/kayit/", {
            "business_name": "X", "slug": "panel", "owner_name": "Can", "closed_weekday": 6,
            "open_at": "09:00", "close_at": "20:00", "email": "x@example.com",
            "password": "uzun-bir-sifre-9"})
        self.assertContains(r, "Bu adres kullanılamaz")   # ayrılmış adres


class ReportTests(Base):
    def test_month_figures(self):
        day = self.now.astimezone(TZ).date().replace(day=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        past = datetime.combine(day, time(8), tzinfo=TZ)
        c1, c2 = self.customer(), self.customer("05329998877", "Can")
        a1 = create_appointment(self.b, [self.cut], self.at(10, day=day), customer=c1, now=past)
        a2 = create_appointment(self.b, [self.combo], self.at(11, day=day), customer=c2, now=past)
        a3 = create_appointment(self.b, [self.cut], self.at(13, day=day), source="manual", now=past)
        close_appointment(a1, "completed", payment="cash")
        close_appointment(a2, "completed", amount=650, payment="card")
        close_appointment(a3, "no_show")
        r = reports.build(self.b, day.year, day.month)
        self.assertEqual(r["cur"]["revenue"], 1050)
        self.assertEqual(r["cur"]["completed"], 2)
        self.assertEqual(r["cur"]["no_show_rate"], 33.3)
        self.assertEqual(r["cur"]["new_customers"], 2)
        self.assertEqual((r["cur"]["cash"], r["cur"]["card"]), (400, 650))
        self.assertEqual(r["cur"]["no_show_loss"], 400)
        self.assertEqual(r["by_service"][0]["name"], "Saç + sakal")
        self.assertEqual(sum(c["n"] for row in r["heat"] for c in row["cells"]), 3)
        self.assertGreater(r["cur"]["occupancy"], 0)


class SuperuserCommandTests(TestCase):
    def run_cmd(self, **env):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        out = StringIO()
        with mock.patch.dict("os.environ", env):
            call_command("ensure_superuser", stdout=out)
        return out.getvalue()

    def test_creates_once_and_keeps_password(self):
        self.assertIn("atlandı", self.run_cmd(SUPERUSER_EMAIL="", SUPERUSER_PASSWORD=""))
        self.assertFalse(User.objects.exists())
        self.run_cmd(SUPERUSER_EMAIL="Yonetici@Example.com", SUPERUSER_PASSWORD="cok-uzun-sifre-42")
        user = User.objects.get(username="yonetici@example.com")
        self.assertTrue(user.is_superuser and user.is_staff)
        self.run_cmd(SUPERUSER_EMAIL="yonetici@example.com", SUPERUSER_PASSWORD="baska-bir-sifre-77")
        user.refresh_from_db()
        self.assertTrue(user.check_password("cok-uzun-sifre-42"))
        self.assertTrue(self.client.login(username="yonetici@example.com", password="cok-uzun-sifre-42"))
        self.assertEqual(self.client.get("/yonetim/").status_code, 200)
        self.assertRedirects(self.client.get("/panel/"), "/yonetim/")

    def test_weak_password_rejected(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_cmd(SUPERUSER_EMAIL="a@example.com", SUPERUSER_PASSWORD="12345678")
        self.assertFalse(User.objects.exists())
