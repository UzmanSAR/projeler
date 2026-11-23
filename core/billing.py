"""Aylık üyelik: ücret, ödeme günü ve ödeme kaydı.

Kural sade: işletme deneme süresinde ücretsizdir; sonrasında ay ay öder. `paid_until` ödenmiş son
günü tutar, bir sonraki ödeme o gün beklenir. Ödeme kaydı (SubscriptionPayment) girilince dönem,
üyeliğin bittiği günden başlar; gün geçtiyse ödeme gününden. Burada hiçbir şey kendiliğinden
kapatılmaz: durum değişikliği (ödeme bekliyor, kapalı) yönetim panelinden yapılır.
"""
import calendar

from django.conf import settings
from django.utils import timezone

WARN_DAYS = 5   # ödeme gününe bu kadar kala panelde hatırlatma çıkar


def add_months(day, months=1):
    """Aynı gün, `months` ay sonra; ay o kadar uzun değilse ayın son günü (31 Oca -> 28 Şub)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def price_for(business):
    """İşletmeye özel ücret varsa o, yoksa platformun genel aylık ücreti."""
    from .models import PlatformSettings
    if business.monthly_price is not None:
        return business.monthly_price
    return PlatformSettings.load().monthly_price


def due_date(business):
    """Bir sonraki ödemenin beklendiği gün: ödenmiş dönemin sonu, hiç ödeme yoksa deneme bitişi."""
    return business.paid_until or business.trial_ends


def summary(business, today=None):
    """Üyelik sayfası ve paneldeki hatırlatma için tek yerden özet."""
    today = today or timezone.localdate()
    due = due_date(business)
    days_left = (due - today).days if due else None
    in_trial = business.status == business.Status.TRIAL and not business.paid_until
    return {
        "price": price_for(business),
        "due": due,
        "days_left": days_left,
        "days_over": -days_left if days_left is not None and days_left < 0 else 0,
        "overdue": days_left is not None and days_left < 0,
        "in_trial": in_trial,
        "trial_days": settings.TRIAL_DAYS,
        "warn": (days_left is not None and days_left <= WARN_DAYS
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
        payment.period_end = add_months(payment.period_start)


def apply_payment(payment):
    """Ödeme girilince üyelik bitişi ilerler; deneme ya da ödeme bekleyen hesap aktif olur."""
    business = payment.business
    fields = []
    if not business.paid_until or payment.period_end > business.paid_until:
        business.paid_until = payment.period_end
        fields.append("paid_until")
    if business.status in (business.Status.TRIAL, business.Status.PAST_DUE):
        business.status = business.Status.ACTIVE
        fields.append("status")
    if fields:
        business.save(update_fields=fields)


def record_payment(business, amount=None, paid_on=None, method="transfer", note=""):
    """Bir aylık ödeme kaydı açar (yönetim panelindeki işlem ve örnek veri bunu kullanır)."""
    from .models import SubscriptionPayment
    return SubscriptionPayment.objects.create(
        business=business, amount=amount, paid_on=paid_on or timezone.localdate(), method=method, note=note)

