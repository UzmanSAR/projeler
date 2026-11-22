"""Randevu oluşturma, kapatma ve iptal. Tüm yazma işlemleri buradan geçer."""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from .availability import business_tz, day_slots
from .models import Appointment, AppointmentItem, AuditLog, Customer, MessageLog, Staff
from .sms import cancel_queued, send_sms


class BookingError(Exception):
    """Kullanıcıya gösterilecek mesajı taşır."""


def eligible_staff(business, services, staff=None):
    """Seçilen işlemlerin hepsini yapabilen aktif berberler."""
    qs = Staff.objects.filter(business=business, active=True)
    if staff is not None:
        qs = qs.filter(id=staff.id)
    for s in services:
        qs = qs.filter(services=s)
    return list(qs.distinct())


def totals(services):
    duration = sum(s.duration for s in services)
    buffer = max((s.buffer for s in services), default=0)
    price = sum(s.price for s in services)
    return duration, buffer, price


def get_or_create_customer(business, phone, name="", verified=False):
    customer, _ = Customer.objects.get_or_create(business=business, phone=phone)
    changed = []
    if name and customer.name != name:
        customer.name = name[:60]
        changed.append("name")
    if verified:
        customer.verified_at = timezone.now()
        changed.append("verified_at")
    if changed:
        customer.save(update_fields=changed)
    return customer


def _local(business, dt):
    return dt.astimezone(business_tz(business))


def appointment_url(appt):
    return settings.SITE_URL + reverse("public:appointment", args=[appt.business.slug, appt.token])


def _queue_messages(appt, now):
    b = appt.business
    when = _local(b, appt.start)
    send_sms(
        b, appt.customer.phone,
        f"{b.name}: {when:%d.%m} {when:%H:%M} randevunuz alindi ({appt.staff.name}). "
        f"Detay/iptal: {appointment_url(appt)}",
        MessageLog.Kind.CONFIRM, appointment=appt,
    )
    # Hatırlatma: 24 saat önce; randevu daha yakınsa 2 saat önce; o da geçtiyse gönderilmez.
    for hours in (24, 2):
        at = appt.start - timedelta(hours=hours)
        if at > now + timedelta(minutes=30):
            send_sms(
                b, appt.customer.phone,
                f"{b.name}: {when:%d.%m} {when:%H:%M} randevunuzu hatirlatiriz. "
                f"Gelemeyecekseniz: {appointment_url(appt)}",
                MessageLog.Kind.REMINDER, appointment=appt, scheduled_at=at,
            )
            break


@transaction.atomic
def create_appointment(business, services, start, *, staff=None, customer=None,
                       source=Appointment.Source.ONLINE, user=None, now=None, notify=True):
    """Randevuyu oluşturur. staff=None ise ('fark etmez') boş olan ilk berber atanır."""
    now = now or timezone.now()
    services = list(services)
    if not services or any(s.business_id != business.id or not s.active for s in services):
        raise BookingError("Geçerli bir işlem seçin.")
    if staff is not None and staff.business_id != business.id:
        raise BookingError("Geçerli bir berber seçin.")
    online = source == Appointment.Source.ONLINE
    duration, buffer, price = totals(services)
    candidates = eligible_staff(business, services, staff)
    if not candidates:
        raise BookingError("Seçilen işlemleri yapabilen berber bulunamadı.")

    if online:
        if not business.accepts_bookings:
            raise BookingError("Bu dükkân şu an online randevu almıyor. Lütfen dükkânı arayın.")
        if customer is None:
            raise BookingError("Telefon doğrulaması gerekli.")
        if customer.blocked:
            raise BookingError("Online randevu alınamıyor. Lütfen dükkânı arayın.")
        open_qs = Appointment.objects.filter(
            business=business, customer=customer,
            status=Appointment.Status.CONFIRMED, start__gt=now,
        )
        if open_qs.count() >= business.max_open_per_phone:
            raise BookingError("Açık randevu sayınız sınırda. Önce mevcut randevunuzu iptal edin.")
        day = _local(business, start).date()
        if any(_local(business, a.start).date() == day for a in open_qs):
            raise BookingError("Bu gün için zaten bir randevunuz var.")

    if source == Appointment.Source.WALKIN:
        # Randevusuz müşteri "şimdi" işlenir; çalışma saati ızgarası aranmaz,
        # çakışmayı veritabanı kısıtı yakalar.
        free = candidates
    else:
        slots = day_slots(business, candidates, _local(business, start).date(), duration, buffer,
                          now=now, enforce_rules=online)
        free = [s for s in candidates if start in slots[s.id]]
    if not free:
        raise BookingError("Bu saat az önce doldu. Lütfen başka bir saat seçin.")

    end = start + timedelta(minutes=duration)
    appt = None
    for chosen in free:
        try:
            with transaction.atomic():
                appt = Appointment.objects.create(
                    business=business, staff=chosen, customer=customer, start=start, end=end,
                    block_end=end + timedelta(minutes=buffer), source=source, planned_total=price,
                )
            break
        except IntegrityError:  # aynı saniyede başka biri aldı
            continue
    if appt is None:
        raise BookingError("Bu saat az önce doldu. Lütfen başka bir saat seçin.")

    AppointmentItem.objects.bulk_create([
        AppointmentItem(appointment=appt, service=s, name=s.name, price=s.price, duration=s.duration)
        for s in services
    ])
    AuditLog.objects.create(business=business, appointment=appt, user=user,
                            action="created", detail=source)
    if notify and customer and (online or (source == Appointment.Source.MANUAL and business.remind_manual)):
        _queue_messages(appt, now)
    return appt


def close_appointment(appt, status, *, amount=None, payment="", user=None):
    """Tamamlandı ya da gelmedi olarak kapatır."""
    S = Appointment.Status
    if status not in (S.COMPLETED, S.NO_SHOW):
        raise BookingError("Geçersiz durum.")
    if appt.status not in (S.CONFIRMED, S.COMPLETED, S.NO_SHOW):
        raise BookingError("İptal edilmiş randevu kapatılamaz.")
    was_no_show = appt.status == S.NO_SHOW
    appt.status = status
    if status == S.COMPLETED:
        appt.actual_total = appt.planned_total if amount is None else amount
        appt.payment = payment or Appointment.Payment.CASH
    else:
        appt.actual_total, appt.payment = None, ""
    appt.save(update_fields=["status", "actual_total", "payment"])
    if appt.customer_id and was_no_show != (status == S.NO_SHOW):
        c = appt.customer
        c.no_show_count = max(0, c.no_show_count + (1 if status == S.NO_SHOW else -1))
        c.save(update_fields=["no_show_count"])
    cancel_queued(appt)
    AuditLog.objects.create(business=appt.business, appointment=appt, user=user,
                            action=status, detail=str(appt.actual_total or ""))
    return appt


def cancel_appointment(appt, *, by_customer, user=None, now=None):
    now = now or timezone.now()
    if appt.status != Appointment.Status.CONFIRMED:
        raise BookingError("Bu randevu zaten kapatılmış.")
    if by_customer and not appt.can_cancel_online(now):
        raise BookingError("İptal süresi geçti. Lütfen dükkânı arayın.")
    appt.status = (Appointment.Status.CANCELLED_CUSTOMER if by_customer
                   else Appointment.Status.CANCELLED_BUSINESS)
    appt.save(update_fields=["status"])
    cancel_queued(appt)
    AuditLog.objects.create(business=appt.business, appointment=appt, user=user, action=appt.status)
    # İşletme iptal ettiyse müşteriye bildirilir (sessiz iptal, rakiplerdeki şikâyetlerden biri).
    if not by_customer and appt.customer_id and appt.start > now:
        when = _local(appt.business, appt.start)
        send_sms(
            appt.business, appt.customer.phone,
            f"{appt.business.name}: {when:%d.%m} {when:%H:%M} randevunuz dukkan tarafindan iptal edildi. "
            f"Yeni randevu: {settings.SITE_URL}/{appt.business.slug}/",
            MessageLog.Kind.CANCEL, appointment=appt,
        )
    return appt
