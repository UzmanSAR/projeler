"""SMS gönderimi ve mesaj kuyruğu.

Her mesaj MessageLog'a yazılır. Hatırlatmalar randevu oluşurken değil, zamanı
gelince `python manage.py send_due_messages` komutuyla gönderilir (cron ile
dakikada bir çalıştırılır). İptal edilen randevunun mesajı gitmez.
"""
import logging
import math
from decimal import Decimal

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import Appointment, Business, MessageLog

log = logging.getLogger("sms")

# Türkçe karakterli mesaj 70 karakterde ikinci SMS'e taşar ve iki kat ücretlenir.
# Bu yüzden gövde gönderilmeden önce sadeleştirilir.
_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")


def plain(text):
    return text.translate(_TR)


def segment_count(body):
    return 1 if len(body) <= 160 else math.ceil(len(body) / 153)


class ConsoleBackend:
    """Geliştirme: mesajı gönderme, günlüğe yaz."""

    def send(self, phone, body):
        log.info("SMS -> %s: %s", phone, body)


class FailingBackend:
    """Testlerde sağlayıcı hatasını taklit eder."""

    def send(self, phone, body):
        raise RuntimeError("sağlayıcı yanıt vermedi")


def get_backend():
    return import_string(settings.SMS_BACKEND)()


def _deliver(msg):
    try:
        get_backend().send(msg.phone, msg.body)
    except Exception as exc:  # sağlayıcı hatası randevuyu bozmamalı
        msg.status = MessageLog.Status.FAILED
        msg.error = str(exc)[:200]
        msg.save(update_fields=["status", "error"])
        log.warning("SMS gönderilemedi (%s): %s", msg.phone, exc)
        return False
    unit = settings.SMS_OTP_UNIT_COST if msg.kind == MessageLog.Kind.OTP else settings.SMS_UNIT_COST
    msg.status = MessageLog.Status.SENT
    msg.sent_at = timezone.now()
    msg.cost = Decimal(unit) * msg.segments
    msg.save(update_fields=["status", "sent_at", "cost"])
    Business.objects.filter(id=msg.business_id).update(sms_credit=F("sms_credit") - msg.segments)
    return True


def send_sms(business, phone, body, kind, appointment=None, scheduled_at=None):
    body = plain(body)
    msg = MessageLog.objects.create(
        business=business, appointment=appointment, phone=phone, kind=kind, body=body,
        segments=segment_count(body), scheduled_at=scheduled_at or timezone.now(),
    )
    if scheduled_at is None:
        _deliver(msg)
    return msg


def send_due(now=None):
    """Zamanı gelmiş mesajları gönderir. Gönderilen mesaj sayısını döndürür."""
    now = now or timezone.now()
    sent = 0
    due = MessageLog.objects.filter(
        status=MessageLog.Status.QUEUED, scheduled_at__lte=now
    ).select_related("appointment")
    for msg in due:
        appt = msg.appointment
        if appt and (appt.status != Appointment.Status.CONFIRMED or appt.start <= now):
            msg.status = MessageLog.Status.CANCELLED
            msg.save(update_fields=["status"])
            continue
        sent += _deliver(msg)
    return sent


def cancel_queued(appointment):
    appointment.messages.filter(status=MessageLog.Status.QUEUED).update(
        status=MessageLog.Status.CANCELLED
    )
