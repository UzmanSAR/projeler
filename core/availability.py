"""Boş saat hesabı: çalışma saati − mola − kapalı zamanlar − mevcut randevular."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import Appointment, TimeOff, WorkingHours


def business_tz(business):
    return ZoneInfo(business.timezone)


def open_intervals(business, day):
    """O gün dükkânın açık olduğu aralıklar (mola çıkarılmış), saat dilimli."""
    wh = WorkingHours.objects.filter(business=business, weekday=day.weekday()).first()
    if not wh or wh.closed or wh.close <= wh.open:
        return []
    tz = business_tz(business)

    def at(t):
        return datetime.combine(day, t, tzinfo=tz)

    if wh.break_start and wh.break_end and wh.open < wh.break_start < wh.break_end < wh.close:
        return [(at(wh.open), at(wh.break_start)), (at(wh.break_end), at(wh.close))]
    return [(at(wh.open), at(wh.close))]


def busy_by_staff(business, staff_list, lo, hi, exclude_id=None):
    """Her berber için [lo, hi) aralığındaki dolu zamanlar."""
    busy = {s.id: [] for s in staff_list}
    appts = Appointment.objects.filter(
        business=business, staff__in=staff_list, status__in=Appointment.ACTIVE,
        start__lt=hi, block_end__gt=lo,
    )
    if exclude_id:
        appts = appts.exclude(id=exclude_id)
    for a in appts:
        busy[a.staff_id].append((a.start, a.block_end))
    for off in TimeOff.objects.filter(business=business, start__lt=hi, end__gt=lo):
        for sid in busy:
            if off.staff_id is None or off.staff_id == sid:
                busy[sid].append((off.start, off.end))
    return busy


def day_slots(business, staff_list, day, duration, buffer=0, now=None, enforce_rules=True):
    """{berber_id: [başlangıç saatleri]} döndürür.

    enforce_rules=False iken (kuaförün elle girdiği randevu) en erken/en geç
    kuralları uygulanmaz; çalışma saati ve çakışma yine kontrol edilir.
    """
    now = now or timezone.now()
    staff_list = list(staff_list)
    result = {s.id: [] for s in staff_list}
    intervals = open_intervals(business, day)
    if not intervals or not staff_list or duration <= 0:
        return result

    if enforce_rules:
        today = now.astimezone(business_tz(business)).date()
        if day < today or day > today + timedelta(days=business.max_days_ahead):
            return result
        earliest = now + timedelta(minutes=business.min_notice_minutes)
    else:
        earliest = None

    busy = busy_by_staff(business, staff_list, intervals[0][0], intervals[-1][1])
    step = timedelta(minutes=business.slot_step or 15)
    length = timedelta(minutes=duration)
    block = timedelta(minutes=duration + buffer)

    for lo, hi in intervals:
        t = lo
        while t + length <= hi:
            if earliest is None or t >= earliest:
                for s in staff_list:
                    if all(t + block <= b0 or t >= b1 for b0, b1 in busy[s.id]):
                        result[s.id].append(t)
            t += step
    return result


def merged_slots(slots_by_staff):
    """'Fark etmez' seçimi için: herhangi bir berberde boş olan saatler."""
    return sorted({t for times in slots_by_staff.values() for t in times})
