"""Rapor ekranı: üstte beş rakam, altta iki grafik."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Count, Min, Sum
from django.utils import timezone

from .availability import business_tz, open_intervals
from .models import Appointment, AppointmentItem, Customer, Staff

S = Appointment.Status


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _range(business, d0, d1):
    tz = business_tz(business)
    return datetime.combine(d0, datetime.min.time(), tz), datetime.combine(d1, datetime.min.time(), tz)


def _figures(business, d0, d1, staff=None):
    """[d0, d1) günleri için temel rakamlar."""
    lo, hi = _range(business, d0, d1)
    qs = Appointment.objects.filter(business=business, start__gte=lo, start__lt=hi)
    staff_count = 1
    if staff:
        qs = qs.filter(staff=staff)
    else:
        staff_count = Staff.objects.filter(business=business, active=True).count() or 1

    done = qs.filter(status=S.COMPLETED)
    revenue = done.aggregate(t=Sum("actual_total"))["t"] or 0
    completed = done.count()
    no_show = qs.filter(status=S.NO_SHOW).count()
    closed = completed + no_show

    booked = sum((a.end - a.start).total_seconds() / 60
                 for a in qs.filter(status__in=Appointment.ACTIVE).only("start", "end"))
    today = timezone.now().astimezone(business_tz(business)).date()
    open_minutes, day = 0, d0
    while day < min(d1, today + timedelta(days=1)):
        open_minutes += sum((b - a).total_seconds() / 60 for a, b in open_intervals(business, day))
        day += timedelta(days=1)
    capacity = open_minutes * staff_count

    first_visits = (Appointment.objects.filter(business=business, status__in=Appointment.ACTIVE,
                                               customer__isnull=False)
                    .values("customer").annotate(first=Min("start"))
                    .filter(first__gte=lo, first__lt=hi))
    if staff:
        ids = qs.values_list("customer_id", flat=True)
        first_visits = first_visits.filter(customer__in=ids)

    return {
        "revenue": revenue,
        "completed": completed,
        "occupancy": round(100 * booked / capacity, 1) if capacity else 0,
        "no_show_rate": round(100 * no_show / closed, 1) if closed else 0,
        "new_customers": first_visits.count(),
        "avg_ticket": round(revenue / completed) if completed else 0,
        "no_show_loss": qs.filter(status=S.NO_SHOW).aggregate(t=Sum("planned_total"))["t"] or 0,
        "cash": done.filter(payment="cash").aggregate(t=Sum("actual_total"))["t"] or 0,
        "card": done.filter(payment="card").aggregate(t=Sum("actual_total"))["t"] or 0,
        "online": qs.filter(source="online").exclude(status__startswith="cancelled").count(),
        "walkin": qs.filter(source="walkin").count(),
        "total": qs.filter(status__in=Appointment.ACTIVE).count(),
        "cancelled": qs.filter(status__startswith="cancelled").count(),
    }


def _delta(cur, prev, points=False):
    """Önceki döneme göre değişim. points=True ise yüzde puanı farkı."""
    if points:
        return round(cur - prev, 1)
    if not prev:
        return None
    return round(100 * (cur - prev) / prev)


def build(business, year, month, staff=None):
    d0, d1 = month_bounds(year, month)
    p0, p1 = month_bounds(*previous_month(year, month))
    cur, prev = _figures(business, d0, d1, staff), _figures(business, p0, p1, staff)
    lo, hi = _range(business, d0, d1)
    tz = business_tz(business)

    cards = [
        {"label": "Ciro", "value": f"{cur['revenue']:,.0f} ₺".replace(",", "."),
         "delta": _delta(cur["revenue"], prev["revenue"]), "unit": "%", "good_up": True},
        {"label": "Tamamlanan randevu", "value": cur["completed"],
         "delta": _delta(cur["completed"], prev["completed"]), "unit": "%", "good_up": True},
        {"label": "Doluluk", "value": f"%{cur['occupancy']:g}".replace(".", ","),
         "delta": _delta(cur["occupancy"], prev["occupancy"], True), "unit": " puan", "good_up": True},
        {"label": "Gelmeme oranı", "value": f"%{cur['no_show_rate']:g}".replace(".", ","),
         "delta": _delta(cur["no_show_rate"], prev["no_show_rate"], True), "unit": " puan",
         "good_up": False},
        {"label": "Yeni müşteri", "value": cur["new_customers"],
         "delta": _delta(cur["new_customers"], prev["new_customers"]), "unit": "%", "good_up": True},
    ]
    for c in cards:
        d = c["delta"]
        c["direction"] = None if not d else ("up" if d > 0 else "down")
        c["good"] = None if not d else ((d > 0) == c["good_up"])
        c["abs"] = None if d is None else f"{abs(d):g}".replace(".", ",")

    # Yoğunluk haritası: gün × saat
    appts = Appointment.objects.filter(business=business, start__gte=lo, start__lt=hi,
                                       status__in=Appointment.ACTIVE)
    if staff:
        appts = appts.filter(staff=staff)
    grid = defaultdict(int)
    for start in appts.values_list("start", flat=True):
        local = start.astimezone(tz)
        grid[(local.weekday(), local.hour)] += 1
    hours = sorted({h for _, h in grid}) or [9]
    hour_range = list(range(min(hours), max(hours) + 1))
    peak = max(grid.values(), default=0)
    days = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
    heat = [{"day": days[wd],
             "cells": [{"n": grid[(wd, h)],
                        "level": 0 if not peak else -(-5 * grid[(wd, h)] // peak)}
                       for h in hour_range]}
            for wd in range(7)]
    busiest = max(grid, key=grid.get) if grid else None

    # Hizmete göre ciro
    items = AppointmentItem.objects.filter(appointment__in=appts.filter(status=S.COMPLETED))
    by_service = list(items.values("name").annotate(total=Sum("price"), n=Count("id")).order_by("-total"))
    top = by_service[0]["total"] if by_service else 0
    for row in by_service:
        row["pct"] = round(100 * row["total"] / top) if top else 0

    by_staff = list(appts.filter(status=S.COMPLETED).values("staff__name")
                    .annotate(total=Sum("actual_total"), n=Count("id")).order_by("-total"))

    return {
        "cards": cards, "cur": cur,
        "heat": heat, "hours": hour_range,
        "busiest": f"{days[busiest[0]]} {busiest[1]:02d}:00" if busiest else None,
        "by_service": by_service, "by_staff": by_staff,
    }


def at_risk_customers(business, limit=20):
    """Normal geliş sıklığının 1,5 katı süredir gelmeyen düzenli müşteriler."""
    now = timezone.now()
    out = []
    customers = Customer.objects.filter(business=business).prefetch_related("appointments")
    for c in customers:
        visits = sorted(a.start for a in c.appointments.all() if a.status == S.COMPLETED)
        if len(visits) < 3:
            continue
        gaps = [(b - a).days for a, b in zip(visits, visits[1:])]
        usual = sum(gaps) / len(gaps)
        since = (now - visits[-1]).days
        if usual >= 7 and since > usual * 1.5:
            out.append({"customer": c, "usual": round(usual), "since": since})
    return sorted(out, key=lambda r: -r["since"])[:limit]
