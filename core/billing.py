"""Aylık üyelik: ücret, ödeme günü ve ödeme kaydı.

Kural sade: işletme deneme süresinde ücretsizdir; sonrasında ay ay öder. `paid_until` ödenmiş son
günü tutar, bir sonraki ödeme o gün beklenir ve her zaman ödeme kayıtlarından (SubscriptionPayment)
hesaplanır: kayıt eklenince ilerler, düzeltilince ya da silinince geri gelir. Dönem, üyeliğin
bittiği günden başlar; gün geçtiyse ödeme gününden. Burada hiçbir hesap kendiliğinden kapatılmaz:
"ödeme bekliyor" ve "kapalı" durumlarını yönetim verir.
"""
import calendar
from datetime import date

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
        "warn": (days_left is not None and days_left <= WARN_DAYS and price > 0
                 and business.status != business.Status.SUSPENDED),
    }


def period_start_for(payment):
    """Dönem başı boş bırakılmış ödemenin başlayacağı gün. Erken ödeyen gün kaybetmez: dönem,
    üyeliğin (ya da denemenin) bittiği günden başlar; o gün geçtiyse ödeme gününden."""
    current_end = due_date(payment.business)
    return max(current_end, payment.paid_on) if current_end else payment.paid_on


def fill_payment(payment):
    """Boş bırakılan alanları tamamlar: tutar, dönem başı ve dönem sonu. Dönem hiçbir zaman bir
    takvim ayından kısa yazılmaz."""
    business = payment.business
    if payment.amount is None:
        payment.amount = price_for(business)
    if payment.period_start is None:
        payment.period_start = period_start_for(payment)
    if payment.period_end is None:
        start, day = payment.period_start, business.billing_day
        # Döngü gününe dönüş (28 Şub -> 31 Mar) yalnızca kesintisiz süren döngüde: dönem tam üyeliğin
        # bittiği gün başlıyorsa ve o gün gerçekten döngü günüyse (o ay kısa olduğu için kırpılmış hali
        # dahil). Elle uzatılmış, araya girilmiş ya da geç başlayan dönem kendi gününden bir ay sürer.
        continues = bool(day) and business.paid_until == start and start == _on_day(start.year, start.month, day)
        payment.period_end = add_months(start, anchor=day if continues else start.day)
        payment.cycle_day = day if continues else start.day


def sync(business):
    """Üyelik bitişi = kalan ödeme kayıtlarının en geç dönem sonu (kayıt kalmadıysa boş)."""
    from .models import Business, SubscriptionPayment
    latest = SubscriptionPayment.objects.filter(business_id=business.pk).aggregate(end=Max("period_end"))["end"]
    if business.paid_until != latest:
        business.paid_until = latest
        Business.objects.filter(pk=business.pk).update(paid_until=latest)   # işletme silinirken de güvenli


def apply_payment(payment, new):
    """Kayıttan sonra: üyelik bitişi yeniden hesaplanır; yeni ödeme deneme ya da ödeme bekleyen
    hesabı aktif yapar (önceki durum ödemeye not edilir). Kapalı hesabı yalnızca yönetim açar."""
    business = payment.business
    sync(business)
    fields = []
    cycle_day = getattr(payment, "cycle_day", None)
    # Döngü gününü yalnızca üyeliğin sonunu belirleyen kayıt değiştirir (araya girilen eski kayıt değil).
    if cycle_day and payment.period_end == business.paid_until and business.billing_day != cycle_day:
        business.billing_day = cycle_day
        fields.append("billing_day")
    if new and business.status in (business.Status.TRIAL, business.Status.PAST_DUE):
        type(payment).objects.filter(pk=payment.pk).update(status_before=business.status)
        payment.status_before = business.status
        business.status = business.Status.ACTIVE
        fields.append("status")
    if fields:
        business.save(update_fields=fields)


@receiver(post_delete, sender="core.SubscriptionPayment")
def _payment_deleted(sender, instance, **kwargs):
    """Silinen ödeme üyeliği geri alır (yanlış girilen kayıt silinerek düzeltilebilsin). Hesabı aktif
    yapan ödeme silinir ve başka ödeme kalmazsa hesap önceki durumuna (deneme / ödeme bekliyor) döner;
    başka ödeme varsa bu not en eski kayda devredilir."""
    from .models import Business, SubscriptionPayment
    business = instance.business
    sync(business)
    if not instance.status_before:
        return
    oldest = SubscriptionPayment.objects.filter(business_id=business.pk).order_by("id").first()
    if oldest:
        if not oldest.status_before:
            SubscriptionPayment.objects.filter(pk=oldest.pk).update(status_before=instance.status_before)
    elif Business.objects.filter(pk=business.pk, status=Business.Status.ACTIVE).update(
            status=instance.status_before, billing_day=None):
        business.status, business.billing_day = instance.status_before, None


def record_payment(business, amount=None, paid_on=None, method="transfer", note=""):
    """Bir aylık ödeme kaydı açar (yönetim panelindeki işlem ve örnek veri bunu kullanır)."""
    from .models import SubscriptionPayment
    return SubscriptionPayment.objects.create(
        business=business, amount=amount, paid_on=paid_on or timezone.localdate(), method=method, note=note)
