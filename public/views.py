"""Müşteri tarafı: kuaförün sayfası ve dört adımda randevu."""
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.http import Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import otp
from core.availability import business_tz, day_slots, merged_slots
from core.booking import (BookingError, cancel_appointment, create_appointment, eligible_staff,
                          get_or_create_customer, totals)
from core.models import (Appointment, Business, Customer, Feedback, Membership, PlatformSettings, Service, Staff, Style,
                         WorkingHours, mask_phone, slug_validator)

DAY_NAMES = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def landing(request):
    # Örnek salonlar yalnızca tanıtım kurulumunda vardır; yoksa bağlantıları da gösterilmez.
    demos = {b.slug: b for b in Business.objects.filter(slug__in=("ornek-salon", "ornek-berber"))}
    return render(request, "public/landing.html", {
        "demo": demos.get("ornek-salon") or demos.get("ornek-berber"),
        "demo_men": demos.get("ornek-berber"),
        "demo_salon": demos.get("ornek-salon"),
        "tomorrow": timezone.localdate() + timedelta(days=1),     # telefon önizlemesindeki gün
        "hours": [f"{h:02d}" for h in range(8, 22)],              # açılıştaki saat cetveli
        "ticks": range(0, 360, 30),                               # kadranın saat çizgileri (derece)
        "price": PlatformSettings.load().monthly_price,
    })


def privacy(request):
    return render(request, "public/privacy.html")


def contact(request):
    return render(request, "public/contact.html")


def style_image(request, pk, digest, size=""):
    """Model fotoğrafı. Adres fotoğrafın özetini taşır: fotoğraf değişince adres de değişir,
    bu yüzden tarayıcı bir yıl saklayabilir."""
    style = get_object_or_404(Style.objects.only("image", "thumb", "digest", "business__status")
                              .select_related("business"), pk=int(pk), digest=digest)
    if style.business.status == Business.Status.SUSPENDED:
        raise Http404
    response = HttpResponse(bytes(style.thumb if size == "k" else style.image), content_type="image/webp")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


FEEDBACK_HOURLY_CAP = 300


def feedback(request):
    """Programla ilgili öneri ve görüş: müşteri ya da işletme sahibi yazar, platform yönetimi okur.
    ?d=<adres> hangi dükkânın sayfasından gelindiğini, ?next= gönderince dönülecek sayfayı taşır."""
    from .forms import FeedbackForm
    data = request.POST if request.method == "POST" else request.GET
    slug = data.get("d", "")
    shop = Business.objects.filter(slug=slug).first() if slug_validator.regex.fullmatch(slug) else None
    owned = None
    if request.user.is_authenticated:
        membership = Membership.objects.select_related("business").filter(user=request.user).first()
        owned = membership.business if membership else None
    back = data.get("next", "")
    # Dönüş adresi bu sitenin bir yolu olmalı: "/" ile başlar, "//" ile başlamaz; boşluk, denetim
    # karakteri (tarayıcı satır sonunu siler: "/\r//site" başka siteye gider) ve ters eğik çizgi içermez.
    if (len(back) > 200 or not back.startswith("/") or back.startswith("//") or re.search(r"[\x00-\x20\x7f\\]", back)
            or not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()})):
        back = reverse("public:business", args=[shop.slug]) if shop else (reverse("panel:settings") if owned else "/")
    # Teşekkür iletisi dönülen sayfada görünür; ana sayfa ileti göstermez, o zaman bu sayfada kalınır.
    after = back if back != "/" else reverse("feedback")
    start = Feedback.Sender.OWNER if owned else (Feedback.Sender.CUSTOMER if shop else Feedback.Sender.OTHER)
    form = FeedbackForm(request.POST or None, initial={"sender": start})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["website"]:   # tuzak alan dolu: kaydetmeden teşekkür et
            messages.success(request, "Teşekkürler, görüşün bize ulaştı.")
            return redirect(after)
        # Adres başına saatte 5. Adres başlığı değiştirilerek bu sınır aşılabildiği için sitenin tamamına
        # da bir tavan var (saatte 300): veritabanı dolmasın. Tavan gerçek kullanımın çok üstündedir.
        if not otp._bump(f"fb:{otp.client_ip(request)}", 3600, 5):
            messages.error(request, "Kısa sürede çok fazla gönderim yapıldı. Biraz sonra yeniden dene.")
        elif not otp._bump("fb:all", 3600, FEEDBACK_HOURLY_CAP):
            logging.getLogger(__name__).warning("Geri bildirim tavanı aşıldı: saatte %s gönderim", FEEDBACK_HOURLY_CAP)
            messages.error(request, "Şu an çok fazla gönderim var. Biraz sonra yeniden dene.")
        else:
            Feedback.objects.create(
                sender=d["sender"], message=d["message"].strip(), name=d["name"].strip(), contact=d["contact"].strip(),
                business=owned or shop, user=request.user if request.user.is_authenticated else None, page=back[:200])
            messages.success(request, "Teşekkürler, görüşün bize ulaştı.")
            return redirect(after)
    return render(request, "public/feedback.html", {"form": form, "shop": shop, "owned": owned, "back": back})


def _business(slug):
    business = get_object_or_404(Business, slug=slug)
    if business.status == Business.Status.SUSPENDED:
        raise Http404
    timezone.activate(business_tz(business))  # şablonlarda saatler dükkânın saat diliminde
    return business


# ---- Cihazı hatırlama: doğrulanmış telefon 90 gün tekrar kod istemez ------

def _cookie_name(business):
    return f"dv{business.id}"


def device_customer(request, business):
    raw = request.COOKIES.get(_cookie_name(business))
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt="device", max_age=settings.DEVICE_REMEMBER_DAYS * 86400)
    except signing.BadSignature:
        return None
    return Customer.objects.filter(business=business, id=data.get("c"), blocked=False).first()


def remember_device(response, business, customer):
    response.set_cookie(
        _cookie_name(business), signing.dumps({"c": customer.id}, salt="device"),
        max_age=settings.DEVICE_REMEMBER_DAYS * 86400, httponly=True, samesite="Lax",
        secure=not settings.DEBUG,
    )
    return response


# ---- Seçim (işlemler, berber, saat) adres çubuğunda taşınır ---------------

class Selection:
    def __init__(self, request, business):
        data = request.GET  # form gönderilse bile seçim adres çubuğunda kalır
        ids = [int(x) for x in data.getlist("h") if x.isdigit()][:6]
        by_id = {s.id: s for s in Service.objects.filter(business=business, active=True, id__in=ids)}
        self.services = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
        style_id = data.get("m", "")
        self.style = (Style.objects.filter(business=business, active=True, id=style_id).select_related("service").first()
                      if style_id.isdigit() else None)
        # Modelden gelinince (henüz işlem seçilmemişken) ilgili işlem işaretli gelir; müşteri kaldırabilir.
        if self.style and self.style.service and self.style.service.active and not ids and not data.get("devam"):
            self.services = [self.style.service]
        staff_id = data.get("b", "0")
        self.staff = (Staff.objects.filter(business=business, active=True, id=staff_id).first()
                      if staff_id.isdigit() and staff_id != "0" else None)
        self.duration, self.buffer, self.price = totals(self.services)
        self.start = None
        t = data.get("t", "")
        if t.isdigit():
            try:
                self.start = datetime.fromtimestamp(int(t), tz=dt_timezone.utc)
            except (OverflowError, OSError, ValueError):
                pass

    def query(self, **extra):
        pairs = [("h", s.id) for s in self.services] + [("b", self.staff.id if self.staff else 0)]
        if self.style:
            pairs.append(("m", self.style.id))
        if self.start and "t" not in extra:
            pairs.append(("t", int(self.start.timestamp())))
        pairs += [(k, v) for k, v in extra.items() if v is not None]
        return urlencode(pairs)


def _url(name, business, sel, **extra):
    return f"{reverse(f'public:{name}', args=[business.slug])}?{sel.query(**extra)}"


# ---- Sayfalar -------------------------------------------------------------

def business_page(request, slug):
    business = _business(slug)
    hours = {h.weekday: h for h in business.hours.all()}
    week = [(label, hours.get(i)) for i, label in WorkingHours.WEEKDAYS]
    return render(request, "public/business.html", {
        "business": business,
        "services": business.services.filter(active=True),
        "staff": business.staff.filter(active=True),
        "styles": business.styles.filter(active=True).defer("image", "thumb"),
        "week": week,
        "known": device_customer(request, business),
    })


def book_select(request, slug):
    """Adım 1: işlem ve berber seçimi."""
    business = _business(slug)
    sel = Selection(request, business)
    if request.GET.get("devam"):
        if not sel.services:
            messages.error(request, "En az bir işlem seçin.")
        elif not eligible_staff(business, sel.services, sel.staff):
            messages.error(request, f"Seçtiğiniz {business.staff_word.lower()} bu işlemlerin hepsini yapmıyor. "
                                    "'Fark etmez' seçeneğini deneyin.")
        else:
            return redirect(_url("book_time", business, sel))
    return render(request, "public/book_select.html", {
        "business": business, "sel": sel,
        "styles": business.styles.filter(active=True).defer("image", "thumb"),
        "services": business.services.filter(active=True),
        "staff": business.staff.filter(active=True),
        "selected_ids": [s.id for s in sel.services],
    })


def book_time(request, slug):
    """Adım 2: gün ve saat. Yalnızca gerçekten boş saatler listelenir."""
    business = _business(slug)
    sel = Selection(request, business)
    candidates = eligible_staff(business, sel.services, sel.staff) if sel.services else []
    if not candidates:
        return redirect(_url("book_select", business, sel))

    tz = business_tz(business)
    today = timezone.now().astimezone(tz).date()
    horizon = min(business.max_days_ahead, 13)
    picked = None
    try:
        picked = datetime.strptime(request.GET.get("g", ""), "%Y-%m-%d").date()
    except ValueError:
        pass

    days, slots = [], []
    for offset in range(horizon + 1):
        day = today + timedelta(days=offset)
        times = merged_slots(day_slots(business, candidates, day, sel.duration, sel.buffer))
        if picked is None and times:
            picked = day
        days.append({"date": day, "name": DAY_NAMES[day.weekday()], "free": bool(times),
                     "url": _url("book_time", business, sel, g=day.isoformat(), t=None)})
        if day == picked:
            slots = [{"label": t.astimezone(tz).strftime("%H:%M"),
                      "url": _url("book_details", business, sel, t=int(t.timestamp()))}
                     for t in times]
    return render(request, "public/book_time.html", {
        "business": business, "sel": sel, "days": days, "picked": picked, "slots": slots,
        "back": _url("book_select", business, sel, t=None),
    })


def _finish(request, business, sel, customer):
    """Randevuyu oluşturur; saat dolduysa saat seçimine geri gönderir."""
    try:
        appt = create_appointment(business, sel["services"], sel["start"], staff=sel["staff"],
                                  customer=customer, style=sel.get("style"))
    except BookingError as exc:
        messages.error(request, str(exc))
        return None
    request.session.pop("pending", None)
    response = redirect("public:appointment", business.slug, appt.token)
    return remember_device(response, business, customer)


def book_details(request, slug):
    """Adım 3: ad ve telefon. Tanınan cihazda kod istenmez."""
    business = _business(slug)
    sel = Selection(request, business)
    if not sel.services or not sel.start:
        return redirect(_url("book_select", business, sel))
    known = None if request.GET.get("yeni") else device_customer(request, business)
    back = _url("book_time", business, sel, t=None,
                g=sel.start.astimezone(business_tz(business)).date().isoformat())

    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:60]
        choice = {"services": sel.services, "staff": sel.staff, "start": sel.start, "style": sel.style}
        if known and request.POST.get("known") == "1":
            if name and name != known.name:
                known.name = name
                known.save(update_fields=["name"])
            response = _finish(request, business, choice, known)
            return response or redirect(back)

        phone = otp.normalize_phone(request.POST.get("phone"))
        if not name:
            messages.error(request, "Adınızı yazın.")
        elif not phone:
            messages.error(request, "Geçerli bir cep numarası yazın (05xx xxx xx xx).")
        elif not otp.verify_turnstile(request.POST.get("cf-turnstile-response"), otp.client_ip(request)):
            messages.error(request, "Güvenlik kontrolü tamamlanamadı. Sayfayı yenileyip tekrar deneyin.")
        else:
            try:
                code = otp.request_code(business, phone, otp.client_ip(request))
            except otp.OtpError as exc:
                messages.error(request, str(exc))
            else:
                request.session["pending"] = {
                    "slug": business.slug, "name": name, "phone": phone, "query": sel.query(),
                }
                if code:
                    messages.info(request, f"Tanıtım modu, SMS gönderilmedi. Kod: {code}")
                return redirect("public:book_verify", business.slug)

    return render(request, "public/book_details.html", {
        "business": business, "sel": sel, "known": known, "back": back,
        "local_start": sel.start.astimezone(business_tz(business)),
        "other_number": _url("book_details", business, sel, yeni=1),
    })


def book_verify(request, slug):
    """Adım 4: SMS kodu. Kod yalnızca randevuyu onaylar; pazarlama izni burada sorulmaz."""
    business = _business(slug)
    pending = request.session.get("pending")
    if not pending or pending.get("slug") != business.slug:
        return redirect("public:book_select", business.slug)
    phone = pending["phone"]
    retry = f"{reverse('public:book_time', args=[business.slug])}?{pending['query']}"

    if request.method == "POST":
        if request.POST.get("action") == "resend":
            try:
                code = otp.request_code(business, phone, otp.client_ip(request))
                messages.success(request, "Yeni kod gönderildi.")
                if code:
                    messages.info(request, f"Tanıtım modu, SMS gönderilmedi. Kod: {code}")
            except otp.OtpError as exc:
                messages.error(request, str(exc))
            return redirect("public:book_verify", business.slug)
        try:
            otp.check_code(business, phone, request.POST.get("code"))
        except otp.OtpError as exc:
            messages.error(request, str(exc))
        else:
            customer = get_or_create_customer(business, phone, pending["name"], verified=True)
            response = _finish(request, business, _selection_from(pending, business), customer)
            if response:
                return response
            # Telefon doğrulandı ama saat doldu: cihazı hatırla, yeni saat seçtir.
            request.session.pop("pending", None)
            return remember_device(redirect(retry), business, customer)

    return render(request, "public/book_verify.html", {
        "business": business, "masked": mask_phone(phone), "retry": retry,
    })


class _Query:
    """Oturumda saklanan seçimi Selection'ın okuyabileceği biçime çevirir."""

    def __init__(self, query):
        self.GET = QueryDict(query)


def _selection_from(pending, business):
    sel = Selection(_Query(pending["query"]), business)
    return {"services": sel.services, "staff": sel.staff, "start": sel.start, "style": sel.style}


def _appointment(slug, token):
    business = _business(slug)
    appt = get_object_or_404(
        Appointment.objects.select_related("staff", "customer", "style").defer("style__image", "style__thumb")
        .prefetch_related("items"),
        business=business, token=token,
    )
    return business, appt


def appointment(request, slug, token):
    """Onay sayfası. Linki bilen görür; link tahmin edilemez ve tek randevuya özeldir."""
    business, appt = _appointment(slug, token)
    rebook = urlencode([("h", i.service_id) for i in appt.items.all() if i.service_id]
                       + [("b", appt.staff_id)])
    return render(request, "public/appointment.html", {
        "business": business, "appt": appt,
        "local_start": appt.start.astimezone(business_tz(business)),
        "can_cancel": appt.can_cancel_online(),
        "cancel_hours": business.cancel_limit_minutes / 60,
        "rebook": f"{reverse('public:book_time', args=[slug])}?{rebook}",
    })


@require_POST
def appointment_cancel(request, slug, token):
    _, appt = _appointment(slug, token)
    try:
        cancel_appointment(appt, by_customer=True)
        messages.success(request, "Randevunuz iptal edildi.")
    except BookingError as exc:
        messages.error(request, str(exc))
    return redirect("public:appointment", slug, token)


@require_POST
def appointment_consent(request, slug, token):
    """Kampanya izni randevu bittikten sonra, ayrı ve işaretsiz bir kutuyla sorulur."""
    _, appt = _appointment(slug, token)
    if appt.customer:
        agreed = request.POST.get("consent") == "1"
        appt.customer.marketing_consent = agreed
        appt.customer.marketing_consent_at = timezone.now() if agreed else None
        appt.customer.save(update_fields=["marketing_consent", "marketing_consent_at"])
        messages.success(request, "Tercihiniz kaydedildi.")
    return redirect("public:appointment", slug, token)


def appointment_ics(request, slug, token):
    business, appt = _appointment(slug, token)
    fmt = "%Y%m%dT%H%M%SZ"
    utc = dt_timezone.utc
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//randevu//TR", "BEGIN:VEVENT",
        f"UID:{appt.token}@randevu",
        f"DTSTAMP:{timezone.now().astimezone(utc).strftime(fmt)}",
        f"DTSTART:{appt.start.astimezone(utc).strftime(fmt)}",
        f"DTEND:{appt.end.astimezone(utc).strftime(fmt)}",
        f"SUMMARY:{business.name} - {appt.summary}",
        f"LOCATION:{business.address}".replace(",", "\\,"),
        "END:VEVENT", "END:VCALENDAR",
    ]
    response = HttpResponse("\r\n".join(lines), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="randevu.ics"'
    return response


def _history(business, customer):
    """Müşterinin bu salondaki geçmişi: son ziyaret, sık yaptırdıkları, yaklaşan randevu ve liste."""
    tz = business_tz(business)
    now = timezone.now()
    appts = list(customer.appointments.select_related("staff", "style").defer("style__image", "style__thumb")
                 .prefetch_related("items").order_by("-start")[:40])
    rows, counts = [], {}
    for a in appts:
        rebook = urlencode([("h", i.service_id) for i in a.items.all() if i.service_id]
                           + [("b", a.staff_id)] + ([("m", a.style_id)] if a.style_id else []))
        rows.append({"a": a, "local": a.start.astimezone(tz),
                     "rebook": f"{reverse('public:book_time', args=[business.slug])}?{rebook}"})
        if a.status == Appointment.Status.COMPLETED:
            for item in a.items.all():
                counts[item.name] = counts.get(item.name, 0) + 1
    done = [r for r in rows if r["a"].status == Appointment.Status.COMPLETED]
    last = done[0] if done else None
    upcoming = [r for r in rows if r["a"].status == Appointment.Status.CONFIRMED and r["a"].start > now]
    return {
        "rows": rows, "last": last, "visits": len(done),
        "since": (now.astimezone(tz).date() - last["local"].date()).days if last else None,
        "upcoming": upcoming[-1] if upcoming else None,   # en yakın olan (liste yeniden eskiye sıralı)
        "favourites": sorted(counts.items(), key=lambda kv: -kv[1])[:3],
    }


def account(request, slug):
    """Müşteri hesabı: şifre yok. Telefon bir kez SMS koduyla doğrulanır, cihaz 90 gün hatırlanır.
    Randevu almadan da giriş yapılabilir (kayıt olmak = numarayı doğrulamak)."""
    business = _business(slug)
    customer = device_customer(request, business)
    pending = request.session.get("acct")
    if pending and pending.get("slug") != business.slug:
        pending = None
    if customer:
        return render(request, "public/account.html", {
            "business": business, "customer": customer, **_history(business, customer)})

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send" or (action == "resend" and pending):
            name = request.POST.get("name", "").strip()[:60] if action == "send" else pending.get("name", "")
            phone = otp.normalize_phone(request.POST.get("phone")) if action == "send" else pending["phone"]
            if not phone:
                messages.error(request, "Geçerli bir cep numarası yazın (05xx xxx xx xx).")
            elif action == "send" and not otp.verify_turnstile(request.POST.get("cf-turnstile-response"),
                                                              otp.client_ip(request)):
                messages.error(request, "Güvenlik kontrolü tamamlanamadı. Sayfayı yenileyip tekrar deneyin.")
            else:
                try:
                    code = otp.request_code(business, phone, otp.client_ip(request), purpose="login")
                except otp.OtpError as exc:
                    messages.error(request, str(exc))
                else:
                    request.session["acct"] = {"slug": business.slug, "phone": phone, "name": name}
                    if code:
                        messages.info(request, f"Tanıtım modu, SMS gönderilmedi. Kod: {code}")
            return redirect("public:account", slug)
        if action == "verify" and pending:
            try:
                otp.check_code(business, pending["phone"], request.POST.get("code"))
            except otp.OtpError as exc:
                messages.error(request, str(exc))
                return redirect("public:account", slug)
            customer = get_or_create_customer(business, pending["phone"], pending.get("name", ""), verified=True)
            request.session.pop("acct", None)
            if customer.blocked:
                messages.error(request, "Bu numara için online işlem kapalı. Lütfen salonu arayın.")
                return redirect("public:business", slug)
            messages.success(request, "Giriş yapıldı. Bu cihaz 90 gün hatırlanacak.")
            return remember_device(redirect("public:account", slug), business, customer)
        if action == "change":
            request.session.pop("acct", None)
            return redirect("public:account", slug)

    return render(request, "public/account.html", {
        "business": business, "customer": None, "pending": pending,
        "masked": mask_phone(pending["phone"]) if pending else "",
    })


@require_POST
def account_forget(request, slug):
    business = _business(slug)
    response = redirect("public:business", slug)
    response.delete_cookie(_cookie_name(business))
    return response
