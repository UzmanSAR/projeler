"""Kuaför paneli. Her görünüm yalnızca oturumdaki işletmenin verisine dokunur:
tüm sorgular request.business ile filtrelenir (kiracı yalıtımı)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import images, reports
from core.availability import business_tz, open_intervals
from core.booking import (BookingError, cancel_appointment, close_appointment,
                          create_appointment, get_or_create_customer)
from core.models import (Appointment, Customer, Membership, PlatformSettings, Service, Staff, Style, TimeOff,
                         WorkingHours)
from core.otp import normalize_phone
from core.setup import create_business


from .forms import BusinessForm, ServiceForm, SignupForm, StaffForm, StyleForm

User = get_user_model()
PX_PER_MIN = 1.5


def panel_view(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        membership = Membership.objects.select_related("business").filter(user=request.user).first()
        if not membership:
            if request.user.is_staff:
                return redirect("admin:index")
            raise PermissionDenied
        request.business = membership.business
        request.tz = business_tz(membership.business)
        timezone.activate(request.tz)  # şablonlarda saatler dükkânın saat diliminde
        return view(request, *args, **kwargs)
    return wrapper


def signup(request):
    if request.user.is_authenticated:
        return redirect("panel:today")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"])
        create_business(user, d["business_name"], d["slug"], d["owner_name"],
                        closed_weekday=d["closed_weekday"], open_at=d["open_at"],
                        close_at=d["close_at"], phone=d["phone"], kind=d["kind"])
        login(request, user)
        messages.success(request, "Sayfan yayında. Hizmet ve fiyatlarını Ayarlar'dan düzenleyebilirsin.")
        return redirect("panel:today")
    return render(request, "panel/signup.html", {"form": form})


def _parse_day(request, tz):
    try:
        return datetime.strptime(request.GET.get("g", ""), "%Y-%m-%d").date()
    except ValueError:
        return timezone.now().astimezone(tz).date()


def _day_range(day, tz):
    lo = datetime.combine(day, time.min, tz)
    return lo, lo + timedelta(days=1)


def _appointments(business):
    return (Appointment.objects.filter(business=business)
            .select_related("staff", "customer", "style").defer("style__image", "style__thumb")
            .prefetch_related("items"))


def _back(request, default="panel:today"):
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/panel/") else default)


# ---- Bugün ----------------------------------------------------------------

@panel_view
def today(request):
    b, tz = request.business, request.tz
    now = timezone.now()
    lo, hi = _day_range(now.astimezone(tz).date(), tz)
    appts = list(_appointments(b).filter(start__gte=lo, start__lt=hi)
                 .exclude(status__startswith="cancelled"))
    done = [a for a in appts if a.status == Appointment.Status.COMPLETED]
    unclosed = _appointments(b).filter(status=Appointment.Status.CONFIRMED, end__lt=now)
    return render(request, "panel/today.html", {
        "tab": "today", "appts": appts, "now": now,
        "revenue": sum(a.actual_total or 0 for a in done),
        "done_count": len(done),
        "waiting": sum(1 for a in appts if a.is_open and a.start >= now),
        "unclosed": [a for a in unclosed if a.start < lo],
        "staff": b.staff.filter(active=True),
        "services": b.services.filter(active=True),
        "page_url": f"{settings.SITE_URL}/{b.slug}/",
    })


@require_POST
@panel_view
def appointment_close(request, pk):
    appt = get_object_or_404(Appointment, business=request.business, pk=pk)
    status = request.POST.get("status")
    amount = None
    raw = request.POST.get("amount", "").strip().replace(",", ".")
    if raw:
        try:
            amount = Decimal(raw)
            if amount < 0:
                raise InvalidOperation
        except InvalidOperation:
            messages.error(request, "Tutar geçersiz.")
            return _back(request)
    try:
        close_appointment(appt, status, amount=amount, payment=request.POST.get("payment", ""),
                          user=request.user)
    except BookingError as exc:
        messages.error(request, str(exc))
    return _back(request)


@require_POST
@panel_view
def appointment_cancel(request, pk):
    appt = get_object_or_404(Appointment, business=request.business, pk=pk)
    try:
        cancel_appointment(appt, by_customer=False, user=request.user)
        messages.success(request, "Randevu iptal edildi; müşteriye bildirildi.")
    except BookingError as exc:
        messages.error(request, str(exc))
    return _back(request)


def _posted_services(request):
    ids = [x for x in request.POST.getlist("h") if x.isdigit()]
    return list(Service.objects.filter(business=request.business, active=True, id__in=ids))


def _posted_staff(request):
    sid = request.POST.get("b", "0")
    if sid.isdigit() and sid != "0":
        return get_object_or_404(Staff, business=request.business, active=True, pk=sid)
    return None


def _posted_customer(request):
    """Ad ve telefon isteğe bağlı. Telefon yazıldıysa geçerli olmalı."""
    name = request.POST.get("name", "").strip()
    raw = request.POST.get("phone", "").strip()
    if not raw:
        return None
    phone = normalize_phone(raw)
    if not phone:
        raise BookingError("Telefon numarası geçersiz (05xx xxx xx xx).")
    return get_or_create_customer(request.business, phone, name)


@require_POST
@panel_view
def walkin(request):
    """Randevusuz gelen müşteri: iki dokunuşla şu anki saate işlenir."""
    now = timezone.now().replace(second=0, microsecond=0)
    try:
        create_appointment(request.business, _posted_services(request), now,
                           staff=_posted_staff(request), customer=_posted_customer(request),
                           source=Appointment.Source.WALKIN, user=request.user)
        messages.success(request, "Randevusuz müşteri takvime işlendi.")
    except BookingError as exc:
        msg = str(exc)
        if "doldu" in msg:
            msg = "Bu çalışan şu an dolu görünüyor. Başka birini seçin ya da önceki randevuyu kapatın."
        messages.error(request, msg)
    return _back(request)


# ---- Takvim ---------------------------------------------------------------

@panel_view
def calendar(request):
    b, tz = request.business, request.tz
    day = _parse_day(request, tz)
    lo, hi = _day_range(day, tz)
    staff = list(b.staff.filter(active=True))
    appts = list(_appointments(b).filter(start__lt=hi, block_end__gt=lo)
                 .exclude(status__startswith="cancelled"))
    offs = list(TimeOff.objects.filter(business=b, start__lt=hi, end__gt=lo))

    intervals = open_intervals(b, day)
    first = intervals[0][0] if intervals else datetime.combine(day, time(9), tz)
    last = intervals[-1][1] if intervals else datetime.combine(day, time(20), tz)
    for a in appts:
        first, last = min(first, a.start), max(last, a.end)
    first = max(first.astimezone(tz).replace(minute=0), lo)
    last = min(last.astimezone(tz), hi)

    def box(start, end):
        start, end = max(start, first), min(end, last)
        return {"top": round((start - first).total_seconds() / 60 * PX_PER_MIN),
                "height": max(22, round((end - start).total_seconds() / 60 * PX_PER_MIN) - 2)}

    columns = []
    for s in staff:
        columns.append({
            "staff": s,
            "appts": [{"a": a, **box(a.start, a.end)} for a in appts if a.staff_id == s.id],
            "offs": [{"o": o, **box(o.start, o.end)} for o in offs
                     if o.staff_id in (None, s.id) and o.end > first and o.start < last],
        })
    if intervals and len(intervals) == 2:  # mola
        for col in columns:
            col["offs"].append({"o": None, **box(intervals[0][1], intervals[1][0])})

    marks, t = [], first
    while t < last:
        marks.append({"label": t.strftime("%H:%M"),
                      "top": round((t - first).total_seconds() / 60 * PX_PER_MIN)})
        t += timedelta(hours=1)

    return render(request, "panel/calendar.html", {
        "tab": "calendar", "day": day, "prev": day - timedelta(days=1),
        "next": day + timedelta(days=1), "closed": not intervals,
        "columns": columns, "marks": marks,
        "height": round((last - first).total_seconds() / 60 * PX_PER_MIN),
        "staff": staff, "services": b.services.filter(active=True),
        "day_offs": offs,
    })


def _posted_datetime(request, tz, date_field="date", time_field="time"):
    try:
        return datetime.strptime(
            f"{request.POST.get(date_field, '')} {request.POST.get(time_field, '')}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)
    except ValueError:
        raise BookingError("Tarih ya da saat geçersiz.")


@require_POST
@panel_view
def manual_create(request):
    """Arayan müşteri için kuaförün elle girdiği randevu; aynı takvime düşer."""
    day = request.POST.get("date", "")
    try:
        start = _posted_datetime(request, request.tz)
        create_appointment(request.business, _posted_services(request), start,
                           staff=_posted_staff(request), customer=_posted_customer(request),
                           source=Appointment.Source.MANUAL, user=request.user)
        messages.success(request, "Randevu eklendi.")
    except BookingError as exc:
        msg = str(exc)
        if "doldu" in msg:
            msg = "Bu saat dolu ya da çalışma saatleri dışında."
        messages.error(request, msg)
    return redirect(f"/panel/takvim/?g={day}")


@require_POST
@panel_view
def timeoff_create(request):
    day = request.POST.get("date", "")
    try:
        start = _posted_datetime(request, request.tz, time_field="from")
        end = _posted_datetime(request, request.tz, time_field="to")
        if end <= start:
            raise BookingError("Bitiş, başlangıçtan sonra olmalı.")
        staff = _posted_staff(request)
        clash = Appointment.objects.filter(
            business=request.business, status=Appointment.Status.CONFIRMED,
            start__lt=end, block_end__gt=start,
        )
        if staff:
            clash = clash.filter(staff=staff)
        TimeOff.objects.create(business=request.business, staff=staff, start=start, end=end,
                               reason=request.POST.get("reason", "").strip()[:80])
        if clash.exists():
            messages.warning(request, f"Saat kapatıldı. Bu aralıkta {clash.count()} randevu var; "
                                      "onlar kendiliğinden iptal edilmez.")
        else:
            messages.success(request, "Saat kapatıldı.")
    except BookingError as exc:
        messages.error(request, str(exc))
    return redirect(f"/panel/takvim/?g={day}")


@require_POST
@panel_view
def timeoff_delete(request, pk):
    off = get_object_or_404(TimeOff, business=request.business, pk=pk)
    day = off.start.astimezone(request.tz).date()
    off.delete()
    return redirect(f"/panel/takvim/?g={day}")


# ---- Müşteriler -----------------------------------------------------------

@panel_view
def customers(request):
    q = request.GET.get("q", "").strip()
    qs = Customer.objects.filter(business=request.business)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__contains=q.replace(" ", "")))
    done = Q(appointments__status=Appointment.Status.COMPLETED)
    qs = qs.annotate(visits=Count("appointments", filter=done),
                     spent=Sum("appointments__actual_total", filter=done),
                     last=Max("appointments__start", filter=done)).order_by("-last", "-id")[:200]
    return render(request, "panel/customers.html", {
        "tab": "customers", "customers": qs, "q": q,
        "total": Customer.objects.filter(business=request.business).count(),
        "at_risk": reports.at_risk_customers(request.business) if not q else [],
    })


@panel_view
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, business=request.business, pk=pk)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            # KVKK silme hakkı: müşteri kaydı silinir, randevular isimsiz kalır.
            customer.delete()
            messages.success(request, "Müşteri kaydı silindi.")
            return redirect("panel:customers")
        customer.name = request.POST.get("name", "").strip()[:60]
        customer.note = request.POST.get("note", "").strip()[:500]
        customer.blocked = request.POST.get("blocked") == "1"
        customer.save(update_fields=["name", "note", "blocked"])
        messages.success(request, "Kaydedildi.")
        return redirect("panel:customer", pk=pk)
    appts = list(_appointments(request.business).filter(customer=customer).order_by("-start")[:50])
    done = [a for a in appts if a.status == Appointment.Status.COMPLETED]
    counts = {}
    for a in done:
        for item in a.items.all():
            counts[item.name] = counts.get(item.name, 0) + 1
    now = timezone.now()
    last = done[0] if done else None
    upcoming = [a for a in appts if a.status == Appointment.Status.CONFIRMED and a.start > now]
    gaps = [(done[i].start - done[i + 1].start).days for i in range(len(done) - 1)]
    return render(request, "panel/customer.html", {
        "tab": "customers", "customer": customer, "appts": appts,
        "visits": len(done), "spent": sum(a.actual_total or 0 for a in done),
        "last": last, "since": (now - last.start).days if last else None,
        "upcoming": upcoming[-1] if upcoming else None,
        "usual": round(sum(gaps) / len(gaps)) if gaps else None,
        "favourites": sorted(counts.items(), key=lambda kv: -kv[1])[:4],
        "styles": [a.style for a in done if a.style][:6],
    })


# ---- Raporlar -------------------------------------------------------------

@panel_view
def report(request):
    b = request.business
    today_ = timezone.now().astimezone(request.tz).date()
    try:
        year, month = map(int, request.GET.get("ay", "").split("-"))
        date(year, month, 1)
    except ValueError:
        year, month = today_.year, today_.month
    staff_id = request.GET.get("b", "")
    staff = b.staff.filter(pk=staff_id).first() if staff_id.isdigit() else None

    months, y, m = [], today_.year, today_.month
    for _ in range(12):
        months.append({"value": f"{y}-{m:02d}", "label": f"{m:02d}.{y}",
                       "selected": (y, m) == (year, month)})
        y, m = reports.previous_month(y, m)
    return render(request, "panel/report.html", {
        "tab": "report", "r": reports.build(b, year, month, staff), "months": months,
        "staff": b.staff.all(), "staff_selected": staff,
        "levels": range(6),
    })


# ---- Ayarlar --------------------------------------------------------------

@panel_view
def settings_view(request):
    b = request.business
    form = BusinessForm(request.POST or None, instance=b)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Ayarlar kaydedildi.")
        return redirect("panel:settings")
    stale = timezone.localdate() - timedelta(days=90)
    return render(request, "panel/settings.html", {
        "tab": "settings", "form": form,
        "services": b.services.all(), "staff": b.staff.all(),
        "hours": b.hours.all(), "stale": stale,
        "styles": b.styles.defer("image", "thumb")[:4], "style_count": b.styles.count(),
        "page_url": f"{settings.SITE_URL}/{b.slug}/",
    })


@panel_view
def membership(request):
    """Üyelik ve ödeme: kuaför ne zaman, ne kadar ödeyeceğini ve geçmiş ödemelerini görür."""
    b = request.business
    return render(request, "panel/membership.html", {
        "tab": "settings", "bill": b.billing, "payments": b.payments.all()[:24],
        "payment_note": PlatformSettings.load().payment_note,
    })


def _time_or_none(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (ValueError, TypeError):
        return None


@panel_view
def hours(request):
    b = request.business
    rows = {h.weekday: h for h in b.hours.all()}
    if request.method == "POST":
        for wd, _ in WorkingHours.WEEKDAYS:
            row = rows.get(wd) or WorkingHours(business=b, weekday=wd)
            row.closed = request.POST.get(f"closed_{wd}") == "1"
            row.open = _time_or_none(request.POST.get(f"open_{wd}")) or row.open
            row.close = _time_or_none(request.POST.get(f"close_{wd}")) or row.close
            row.break_start = _time_or_none(request.POST.get(f"bs_{wd}"))
            row.break_end = _time_or_none(request.POST.get(f"be_{wd}"))
            if not row.closed and row.close <= row.open:
                messages.error(request, f"{row.get_weekday_display()}: kapanış açılıştan sonra olmalı.")
                return redirect("panel:hours")
            row.save()
        messages.success(request, "Çalışma saatleri kaydedildi.")
        return redirect("panel:settings")
    week = [rows.get(wd) or WorkingHours(business=b, weekday=wd, closed=True)
            for wd, _ in WorkingHours.WEEKDAYS]
    return render(request, "panel/hours.html", {"tab": "settings", "week": week})


@panel_view
def service_edit(request, pk=None):
    b = request.business
    service = get_object_or_404(Service, business=b, pk=pk) if pk else None
    old_price = service.price if service else None
    form = ServiceForm(request.POST or None, instance=service)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        if obj.price != old_price:
            obj.price_updated_at = timezone.localdate()
        obj.save()
        if service is None:  # yeni işlemi varsayılan olarak herkes yapabilir
            for s in b.staff.all():
                s.services.add(obj)
        messages.success(request, "Hizmet kaydedildi.")
        return redirect("panel:settings")
    return render(request, "panel/form.html", {
        "tab": "settings", "form": form, "title": "Hizmet",
        "hint": "Fiyat değişikliği geçmiş randevuların cirosunu etkilemez.",
    })


@panel_view
def staff_edit(request, pk=None):
    b = request.business
    person = get_object_or_404(Staff, business=b, pk=pk) if pk else None
    form = StaffForm(request.POST or None, instance=person, business=b,
                     initial=None if person else {"services": b.services.all()})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        obj.save()
        form.save_m2m()
        messages.success(request, "Personel kaydedildi.")
        return redirect("panel:settings")
    return render(request, "panel/form.html", {"tab": "settings", "form": form, "title": "Personel"})


# ---- Modeller (örnek çalışmalar) -------------------------------------------

@panel_view
def styles(request):
    b = request.business
    return render(request, "panel/styles.html", {
        "tab": "settings", "styles": b.styles.select_related("service").defer("image", "thumb"),
        "limit": Style.MAX_PER_BUSINESS,
    })


@panel_view
def style_edit(request, pk=None):
    b = request.business
    style = get_object_or_404(Style, business=b, pk=pk) if pk else None
    if style is None and b.styles.count() >= Style.MAX_PER_BUSINESS:
        messages.error(request, f"En fazla {Style.MAX_PER_BUSINESS} model eklenebilir. Eskilerden birini sil ya da değiştir.")
        return redirect("panel:styles")
    if request.method == "POST" and request.POST.get("action") == "delete" and style:
        style.delete()
        messages.success(request, "Model silindi.")
        return redirect("panel:styles")
    form = StyleForm(request.POST or None, request.FILES or None, instance=style, business=b)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        photo = form.cleaned_data.get("photo")
        try:
            if photo:
                images.apply(obj, photo)
        except images.ImageError as exc:
            form.add_error("photo", str(exc))
        else:
            obj.save()
            messages.success(request, "Model kaydedildi.")
            return redirect("panel:styles")
    return render(request, "panel/style_form.html", {"tab": "settings", "form": form, "style": style})
