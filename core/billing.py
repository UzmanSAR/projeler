"""Aylık üyelik: ücret, ödeme günü ve ödeme kaydı.

Kural sade: işletme deneme süresinde ücretsizdir; sonrasında ay ay öder. `paid_until` ödenmiş son
günü tutar, bir sonraki ödeme o gün beklenir ve her zaman ödeme kayıtlarından (SubscriptionPayment)
hesaplanır: kayıt eklenince ilerler, düzeltilince ya da silinince geri gelir. Dönem, üyeliğin
bittiği günden başlar; gün geçtiyse ödeme gününden. Burada hiçbir hesap kendiliğinden kapatılmaz:
"ödeme bekliyor" ve "kapalı" durumlarını yönetim verir.
"""
import calendar
from datetime import date

from django.conf import settings
from django.db.models import Max
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

WARN_DAYS = 5   # ödeme gününe bu kadar kala panelde hatırlatma çıkar


def _on_day(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(day, months=1, anchor=None):
    """`months` ay sonra aynı gün; ay o kadar uzun değilse ayın son günü (31 Oca -> 28 Şub).
    `anchor` döngünün asıl günüdür: kısa aydan sonra gün ona geri döner (28 Şub -> 31 Mar)."""
    index = day.year * 12 + day.month - 1 + months
    return _on_day(index // 12, index % 12 + 1, anchor or day.day)


def price_for(business):
    """İşletmeye özel ücret varsa o, yoksa platformun genel aylık ücreti."""
    from .models import PlatformSettings
    if business.monthly_price is not None:
        return business.monthly_price
    return PlatformSettings.load().monthly_price


def due_date(business):
    """Bir sonraki ödemenin beklendiği gün: ödenmiş dönemin sonu; hiç ödeme yoksa ve hesap hâlâ
    denemede (ya da ödeme bekliyor) ise deneme bitişi. Elle aktif yapılmış, kaydı olmayan hesabın
    günü yoktur: eski deneme tarihinden gecikme sayılmaz."""
    if business.paid_until:
        return business.paid_until
    if business.status in (business.Status.TRIAL, business.Status.PAST_DUE):
        return business.trial_ends
    return None


def summary(business, today=None):
    """Üyelik sayfası ve paneldeki hatırlatma için tek yerden özet."""
    today = today or timezone.localdate()
    due = due_date(business)
    price = price_for(business)
    days_left = (due - today).days if due else None
    return {
        "price": price,
        "due": due,
        "days_left": days_left,
        "days_over": -days_left if days_left is not None and days_left < 0 else 0,
        "overdue": days_left is not None and days_left < 0,
        "in_trial": business.status == business.Status.TRIAL and not business.paid_until,
        "trial_days": settings.TRIAL_DAYS,
        "warn": (days_left is not None and days_left <= WARN_DAYS and price > 0
                 and business.status != business.Status.SUSPENDED),
    }


def fill_payment(payment):
    """Boş bırakılan alanları tamamlar: tutar, dönem başı ve dönem sonu."""
    business = payment.business
    if payment.amount is None:
        payment.amount = price_for(business)
    if payment.period_start is None:
        current_end = due_date(business)
        # Erken ödeyen gün kaybetmez: dönem, üyeliğin (ya da denemenin) bittiği günden başlar.
        payment.period_start = max(current_end, payment.paid_on) if current_end else payment.paid_on
    if payment.period_end is None:
        # Kesintisiz süren döngüde ödeme günü aynı kalır; ara verildiyse yeni dönemin günü geçerlidir.
        continues = business.billing_day and business.paid_until == payment.period_start
        anchor = business.billing_day if continues else payment.period_start.day
        payment.period_end = add_months(payment.period_start, anchor=anchor)
        payment.cycle_day = anchor


def sync(business):
    """Üyelik bitişi = kalan ödeme kayıtlarının en geç dönem sonu (kayıt kalmadıysa boş)."""
    from .models import Business, SubscriptionPayment
    latest = SubscriptionPayment.objects.filter(business_id=business.pk).aggregate(end=Max("period_end"))["end"]
    if business.paid_until != latest:
        business.paid_until = latest
        Business.objects.filter(pk=business.pk).update(paid_until=latest)   # işletme silinirken de güvenli


def apply_payment(payment, new):
    """Kayıttan sonra: üyelik bitişi yeniden hesaplanır; yeni ödeme deneme ya da ödeme bekleyen
    hesabı aktif yapar. Kapalı hesabı yalnızca yönetim açar."""
    business = payment.business
    sync(business)
    fields = []
    cycle_day = getattr(payment, "cycle_day", None)
    if cycle_day and business.billing_day != cycle_day:
        business.billing_day = cycle_day
        fields.append("billing_day")
    if new and business.status in (business.Status.TRIAL, business.Status.PAST_DUE):
        business.status = business.Status.ACTIVE
        fields.append("status")
    if fields:
        business.save(update_fields=fields)


@receiver(post_delete, sender="core.SubscriptionPayment")
def _payment_deleted(sender, instance, **kwargs):
    """Silinen ödeme üyeliği geri alır (yanlış girilen kayıt silinerek düzeltilebilsin)."""
    sync(instance.business)


def record_payment(business, amount=None, paid_on=None, method="transfer", note=""):
    """Bir aylık ödeme kaydı açar (yönetim panelindeki işlem ve örnek veri bunu kullanır)."""
    from .models import SubscriptionPayment
    return SubscriptionPayment.objects.create(
        business=business, amount=amount, paid_on=paid_on or timezone.localdate(), method=method, note=note)
