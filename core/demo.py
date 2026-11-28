"""Örnek salonlar: tanıtım sitesinde müşteri sayfası, panel ve raporlar dolu görünsün diye üretilen veri.
İki örnek vardır: erkek kuaförü (MEN, /ornek-berber/) ve kadın kuaförü ile güzellik hizmetleri (SALON, /ornek-salon/).

ensure_demo() tekrar tekrar çalıştırılabilir; eksik olanı tamamlar, var olana dokunmaz:

- Dükkân, berberler, hizmetler ve müşteriler yoksa oluşturulur.
- Her günün hedef randevu sayısı tarihten türetilir. O gün için oluşmuş randevu hedefin altındaysa
  aradaki fark eklenir. Böylece ilk kurulumda geçmiş dolar, zaman geçtikçe de yeni günler eklenir.
- Geçmişe düşmüş örnek randevular kapatılır (tamamlandı ya da gelmedi); ziyaretçilerin kendi
  aldığı deneme randevularına dokunulmaz.

Müşteriler kendi düzenlerine göre gelir (iki ile altı hafta arası), çoğu aynı berbere gider. Her gün
bir iki yeni müşteri eklenir; her müşteri belli sayıda ziyaretten sonra gelmeyi bırakır. Panelde
"kaybedilme riski olanlar" listesi ve raporda "yeni müşteri" rakamı bu yüzden dolu görünür.
"""
import random
from datetime import datetime, time, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count, Max, Q
from django.utils import timezone

from . import billing
from .availability import business_tz, day_slots
from .booking import (BookingError, cancel_appointment, close_appointment, create_appointment,
                      eligible_staff, get_or_create_customer)
from .models import Appointment, Business, Customer, Service, Staff, TimeOff
from .setup import create_business

SLUG = "ornek-berber"   # adres aynı kalır: eski bağlantılar çalışmaya devam eder
SHOP_NAME, SHOP_ABOUT = "Örnek Kuaför", "Mahallenin kuaförü. Saç, sakal ve cilt bakımı."
EMAIL, PASSWORD = "demo@example.com", "demo-sifre-1"
HISTORY_DAYS, AHEAD_DAYS, CUSTOMERS = 84, 21, 360
LOCK_ID = 7270001   # pg_advisory_lock anahtarı

# (ad, unvan, yapmadığı işlemler, seçilme ağırlığı)
STAFF = [
    ("Ali", "usta", (), 32),
    ("Mert", "usta", (), 30),
    ("Kaan", "kalfa", ("Damat tıraşı", "Saç boyama"), 23),
    ("Emir", "kalfa", ("Damat tıraşı", "Saç boyama", "Cilt bakımı", "İple yüz temizliği", "Saç + sakal"), 15),
]
# (ad, süre dk, fiyat ₺, seçilme ağırlığı). İlk üçü kurulum şablonundan gelir.
SERVICES = [
    ("Saç kesimi", 30, 400, 30),
    ("Sakal tıraşı", 20, 250, 12),
    ("Saç + sakal", 45, 600, 30),
    ("Cilt bakımı", 30, 500, 5),
    ("Çocuk tıraşı", 20, 250, 7),
    ("Yıkama ve fön", 15, 150, 5),
    ("İple yüz temizliği", 15, 200, 4),
    ("Saç boyama", 45, 900, 3),
    ("Damat tıraşı", 90, 2500, 1),
]
ADDONS = ("Yıkama ve fön", "İple yüz temizliği")
WEEKDAY_TARGET = (22, 24, 24, 27, 34, 42, 0)   # pazartesi ... pazar

# İlk otuz ad eski örnek veriyle aynıdır: kurulu sitedeki kayıtların adı değişmesin.
FIRST_30 = ["Ahmet Yılmaz", "Mehmet Kaya", "Mustafa Demir", "Emre Şahin", "Burak Çelik", "Can Yıldız",
            "Oğuz Aydın", "Serkan Arslan", "Hakan Doğan", "Kerem Kılıç", "Onur Aslan", "Tolga Çetin",
            "Volkan Kara", "Barış Koç", "Deniz Kurt", "Efe Özkan", "Furkan Polat", "Gökhan Öztürk",
            "Halil Şimşek", "İsmail Korkmaz", "Kaan Erdoğan", "Levent Yavuz", "Murat Can", "Nihat Acar",
            "Okan Güneş", "Selim Bulut", "Taner Aksoy", "Ufuk Tekin", "Yusuf Bozkurt", "Zafer Özdemir"]
FIRST = ["Ahmet", "Mehmet", "Mustafa", "Emre", "Burak", "Can", "Oğuz", "Serkan", "Hakan", "Kerem", "Onur",
         "Tolga", "Volkan", "Barış", "Deniz", "Efe", "Furkan", "Gökhan", "Halil", "İsmail", "Levent", "Murat",
         "Nihat", "Okan", "Selim", "Taner", "Ufuk", "Yusuf", "Zafer", "Berk", "Cem", "Doğan", "Eren", "Fatih",
         "Görkem", "Hasan", "İlker", "Koray", "Mert", "Orhan", "Özgür", "Recep", "Sinan", "Tuna", "Umut"]
LAST = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Aydın", "Arslan", "Doğan", "Kılıç", "Aslan",
        "Çetin", "Kara", "Koç", "Kurt", "Özkan", "Polat", "Öztürk", "Şimşek", "Korkmaz", "Erdoğan", "Yavuz",
        "Acar", "Güneş", "Bulut", "Aksoy", "Tekin", "Bozkurt", "Özdemir", "Uçar", "Sarı", "Keskin", "Turan",
        "Avcı", "Ateş", "Yiğit", "Duman", "Işık", "Çakır", "Erdem", "Güler", "Tunç", "Başaran"]
NOTES = ["Yanlar kısa, üst uzun kalsın.", "Sakal üç numara.", "Ense jiletle alınmasın.",
         "Cumartesi öğleden sonra gelir.", "Çayı şekersiz içer.", "Oğluyla birlikte gelir.",
         "Her seferinde yıkama ister.", "Favoriler düz kesilsin."]


# İkinci örnek: kadın kuaförü ve güzellik hizmetleri. Ana sayfadaki "örnek salon" bağlantısı buna gider.
SALON_STAFF = [
    ("Selin", "stilist", ("Cilt bakımı", "Kirpik lifting", "Manikür", "Kalıcı oje"), 30),
    ("Merve", "stilist", ("Cilt bakımı", "Kirpik lifting"), 27),
    ("Ayşe", "renk uzmanı", ("Cilt bakımı", "Kirpik lifting", "Gelin saçı", "Kaş tasarımı"), 21),
    ("Ece", "güzellik uzmanı", ("Kesim", "Fön", "Kesim + fön", "Dip boya", "Röfle", "Keratin bakım", "Gelin saçı"), 22),
]
SALON_SERVICES = [
    ("Fön", 30, 350, 24),
    ("Kesim + fön", 60, 850, 22),
    ("Kesim", 45, 650, 10),
    ("Manikür", 40, 450, 12),
    ("Kaş tasarımı", 20, 300, 12),
    ("Dip boya", 90, 1500, 8),
    ("Kalıcı oje", 60, 650, 7),
    ("Röfle", 150, 3200, 3),
    ("Cilt bakımı", 60, 1200, 4),
    ("Keratin bakım", 120, 2800, 2),
    ("Kirpik lifting", 60, 900, 3),
    ("Gelin saçı", 120, 4000, 1),
]
SALON_FIRST = ["Ayşe", "Fatma", "Zeynep", "Elif", "Merve", "Esra", "Büşra", "Selin", "Gizem", "Ece", "Derya", "Seda",
               "Burcu", "Ceren", "Damla", "Ebru", "Gamze", "Hande", "İrem", "Kübra", "Melis", "Nazlı", "Özge", "Pınar",
               "Sinem", "Tuğba", "Yasemin", "Zehra", "Aslı", "Berna", "Cansu", "Dilara", "Ezgi", "Gül", "Hilal", "Leyla",
               "Nur", "Rabia", "Sevgi", "Şule", "Tülay", "Duygu", "Ebru", "Feride", "Gonca"]
SALON_NOTES = ["Boya numarası 6.1, oksidan yüzde 6.", "Kalıcı ojede açık tonları sever.", "Saçları ince, fön düşük ısıda.",
               "Kaşta ince form istiyor.", "Cumartesi sabah gelir.", "Kızıyla birlikte gelir.",
               "Keratin sonrası üç gün yıkama yok.", "Röfleyi iki ayda bir tazeler."]

MEN = SimpleNamespace(
    slug=SLUG, name=SHOP_NAME, about=SHOP_ABOUT, email=EMAIL, password=PASSWORD,
    kind="erkek", staff=STAFF, services=SERVICES, addons=ADDONS, weekday_target=WEEKDAY_TARGET,
    first_30=FIRST_30, first=FIRST, notes=NOTES, everyday=5, saturday_only="Damat tıraşı", fallback=2,
    address="Örnek Mah. Çarşı Cad. No: 12", district="Örnek Mahallesi")
SALON = SimpleNamespace(
    slug="ornek-salon", name="Örnek Saç ve Güzellik", about="Saç tasarımı, renk, manikür ve cilt bakımı.",
    email="salon@example.com", password=PASSWORD,
    kind="kadin", staff=SALON_STAFF, services=SALON_SERVICES, addons=("Kaş tasarımı",),
    weekday_target=(15, 17, 17, 19, 24, 30, 0), first_30=[], first=SALON_FIRST, notes=SALON_NOTES,
    everyday=5, saturday_only="Gelin saçı", fallback=1,
    address="Örnek Mah. Lale Sok. No: 4", district="Örnek Mahallesi")
SPECS = (MEN, SALON)


def _phone(i):
    return f"0532{1000000 + i:07d}"


def _is_demo(phone):
    """Örnek müşteri numaraları: baştan gelenler 05321..., sonradan katılanlar 0533..."""
    return phone.startswith(("05321", "0533"))


def _name(i, spec=MEN):
    if i < len(spec.first_30):
        return spec.first_30[i]
    return f"{spec.first[i % len(spec.first)]} {LAST[(i * 7 + i // len(spec.first)) % len(LAST)]}"


def _profile(phone, spec=MEN):
    """Müşterinin düzeni: kaç günde bir gelir, hangi berbere gider, ne yaptırır. Numarasından türer."""
    key = int(phone[4:])
    rnd = random.Random(f"musteri-{key}")
    short = key % 31 == 7         # üç ziyaretten sonra bırakan düzenli müşteri
    return {
        "interval": 14 if short else rnd.choices((14, 21, 28, 35, 42), (10, 30, 35, 15, 10))[0],
        "staff": rnd.choices(range(len(spec.staff)), [s[3] for s in spec.staff])[0],
        "service": rnd.choices(range(spec.everyday), [s[3] for s in spec.services[:spec.everyday]])[0],   # gündelik işlemlerden biri
        "visits": 3 if short else rnd.randint(6, 40),   # bu kadar ziyaretten sonra gelmeyi bırakır
        "flaky": key % 57 == 5,   # sık sık gelmeyen müşteri
        "phase": rnd.random(),
    }


def _card(customer, seed, spec=MEN):
    """Müşteri kartına berber notu ve kampanya izni (bazılarında)."""
    rnd = random.Random(f"kart-{seed}")
    if rnd.random() < .12:
        customer.note = rnd.choice(spec.notes)
    if rnd.random() < .35:
        customer.marketing_consent, customer.marketing_consent_at = True, timezone.now()
    customer.save(update_fields=["note", "marketing_consent", "marketing_consent_at"])
    return customer


def _membership(business, today=None):
    """Örnek dükkânın üyeliği hep geçerli görünür: geçmişte üç aylık ödeme, bitişe on günden az
    kalınca bir ay daha. Üyelik sayfasında gösterecek bir geçmiş olsun diye."""
    today = today or timezone.localdate()
    if not business.payments.exists():
        business.trial_ends = today - timedelta(days=76)
        business.paid_until = None
        business.save(update_fields=["trial_ends", "paid_until"])
        paid_on = business.trial_ends
        for _ in range(3):
            paid_on = billing.record_payment(business, paid_on=paid_on).period_end - timedelta(days=2)
    billing.sync(business)   # elle boşaltılmış bitiş tarihi ödeme kayıtlarından geri gelir
    while business.paid_until and (business.paid_until - today).days < 10:
        billing.record_payment(business, paid_on=min(today, business.paid_until - timedelta(days=2)))


def _shop(spec=MEN):
    """Salon, çalışanlar ve hizmetler: yoksa oluşturur, varsa eksik olanı ekler."""
    business = Business.objects.filter(slug=spec.slug).first()
    if business is None:
        User = get_user_model()
        user = (User.objects.filter(username=spec.email).first()
                or User.objects.create_user(spec.email, spec.email, spec.password))
        business = create_business(user, spec.name, spec.slug, spec.staff[0][0], phone="05320000000", kind=spec.kind)
        business.description = spec.about
        business.address = spec.address
        business.district = spec.district
        business.save()
    _membership(business)
    services = {}
    for order, (name, duration, price, _) in enumerate(spec.services):
        services[name], _ = Service.objects.get_or_create(
            business=business, name=name, defaults={"duration": duration, "price": price, "order": order})
    staff = []
    for order, (name, title, cannot, _) in enumerate(spec.staff):
        person, created = Staff.objects.get_or_create(
            business=business, name=name, defaults={"title": title, "order": order})
        if created or not person.services.exists():
            person.services.set(s for n, s in services.items() if n not in cannot)
        elif not cannot:   # ustalar sonradan eklenen işlemleri de yapar
            person.services.add(*services.values())
        staff.append(person)
    return business, staff, [services[s[0]] for s in spec.services]


def _customers(business, spec=MEN):
    """Baştan beri gelen müşteriler yoksa oluşturulur; sonradan katılanlarla birlikte hepsi döner."""
    pool = Customer.objects.filter(business=business).filter(
        Q(phone__startswith="05321") | Q(phone__startswith="0533"))
    have = set(pool.values_list("phone", flat=True))
    for i in range(CUSTOMERS):
        if _phone(i) not in have:
            _card(get_or_create_customer(business, _phone(i), _name(i, spec), verified=True), i, spec)
    return list(pool.order_by("phone"))


def _close(appt, rnd, flaky=False):
    if appt.customer_id and appt.source != Appointment.Source.WALKIN and rnd.random() < (.4 if flaky else .05):
        close_appointment(appt, Appointment.Status.NO_SHOW)
    else:
        close_appointment(appt, Appointment.Status.COMPLETED,
                          amount=appt.planned_total + rnd.choice((0, 0, 0, 50)),
                          payment=rnd.choice(("cash", "cash", "card")))


def _close_past(business, now):
    """Geçmişe düşmüş örnek randevuları kapatır. Ziyaretçinin kendi numarasıyla aldığı randevu kalır."""
    stale = Appointment.objects.filter(business=business, status=Appointment.Status.CONFIRMED,
                                       end__lt=now).select_related("customer")
    closed = 0
    for appt in stale:
        if appt.customer is None or _is_demo(appt.customer.phone):
            _close(appt, random.Random(f"kapat-{appt.id}"))
            closed += 1
    return closed


def _time_off(business, staff, today, tz):
    """Takvimde örnek bir izin: önümüzdeki günlerde yoksa bir tane ekler."""
    if TimeOff.objects.filter(business=business, end__gt=datetime.combine(today, time(0), tz)).exists():
        return
    day = today + timedelta(days=3)
    while day.weekday() != 2:   # çarşamba
        day += timedelta(days=1)
    TimeOff.objects.create(business=business, staff=staff[1], reason="İzin",
                           start=datetime.combine(day, time(14), tz), end=datetime.combine(day, time(17), tz))


def ensure_demo(history_days=HISTORY_DAYS, ahead_days=AHEAD_DAYS, now=None):
    """Örnek salonları güncel tutar; oluşturduğu ve kapattığı randevu sayısını (ikisinin toplamı) ve
    ilk örneği (erkek kuaförü) döndürür.

    Aynı anda yalnızca bir kez çalışır (veritabanı kilidi): yayın sırasındaki kurulum adımı ile
    uyanan sunucu süreci aynı günleri iki kez doldurmasın.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
        if not cursor.fetchone()[0]:
            return {"created": 0, "closed": 0, "business": Business.objects.filter(slug=SLUG).first()}
    try:
        now = now or timezone.now()
        results = [_ensure_demo(history_days, ahead_days, now, spec) for spec in SPECS]
        first = results[0]
        return {"created": sum(r["created"] for r in results), "closed": sum(r["closed"] for r in results),
                "business": first["business"]}
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])


def _ensure_demo(history_days, ahead_days, now, spec=MEN):
    business, staff, services = _shop(spec)
    customers = _customers(business, spec)
    profiles = [_profile(c.phone, spec) for c in customers]
    tz = business_tz(business)
    today = now.astimezone(tz).date()
    first_day = today - timedelta(days=history_days)
    closed = _close_past(business, now)
    _time_off(business, staff, today, tz)

    # Müşterinin bir sonraki gelişi: son randevusundan düzeni kadar sonra; hiç gelmediyse dönemin başında.
    seen_before = {row[0]: row[1:] for row in Appointment.objects.filter(business=business, customer__in=customers)
                   .exclude(status__startswith="cancelled").values_list("customer_id")
                   .annotate(Max("start"), Count("id"))}
    due, visits = {}, {}
    for c, p in zip(customers, profiles):
        if c.id in seen_before:
            due[c.id] = seen_before[c.id][0].astimezone(tz).date() + timedelta(days=p["interval"])
            visits[c.id] = seen_before[c.id][1]
        else:
            due[c.id] = first_day + timedelta(days=int(p["phase"] * p["interval"]))
            visits[c.id] = 0

    counts = {}
    for start in Appointment.objects.filter(
            business=business, start__gte=datetime.combine(first_day, time(0), tz),
    ).exclude(status__startswith="cancelled").values_list("start", flat=True):
        day = start.astimezone(tz).date()
        counts[day] = counts.get(day, 0) + 1

    weights = [s[3] for s in spec.services]
    addons = [s for s in services if s.name in spec.addons]
    created = 0
    for offset in range(-history_days, ahead_days + 1):
        day = today + timedelta(days=offset)
        existing = counts.get(day, 0)
        rnd = random.Random(f"gun-{day.isoformat()}")
        target = spec.weekday_target[day.weekday()] + rnd.randint(-3, 3) if spec.weekday_target[day.weekday()] else 0
        if offset > 0:   # ileriki günler yaklaştıkça dolar
            target = round(target * (.75 if offset <= 2 else .5 if offset <= 7 else .3 if offset <= 14 else .15))
        need = target - existing
        if need <= 0:
            continue
        rnd = random.Random(f"gun-{day.isoformat()}-{existing}")   # tamamlama turu aynı çekilişi yinelemesin
        booked_at = datetime.combine(day, time(6), tz) - timedelta(days=1)
        coming = [(c, p) for c, p in zip(customers, profiles) if visits[c.id] < p["visits"]]
        waiting = [cp for cp in coming if due[cp[0].id] <= day]
        # Günün ilk doldurulmasında bir iki yeni müşteri de gelir (numarası tarihten türer).
        newcomers = random.Random(f"yeni-{day.isoformat()}").choices((0, 1, 2), (45, 40, 15))[0] if existing == 0 else 0
        rnd.shuffle(waiting)
        waiting.sort(key=lambda cp: due[cp[0].id], reverse=True)   # günü en çok geçen sonda: önce o gelir
        seen = set()
        made = tries = 0
        while made < need and tries < need * 3:
            tries += 1
            kind = rnd.choices(("online", "manual", "walkin"), (50, 22, 28))[0]
            if kind == "walkin" and offset > 0:   # randevusuz müşteri ileri bir güne yazılamaz
                kind = "manual"
            customer = profile = None
            if newcomers and kind != "walkin":
                newcomers -= 1
                phone = f"0533{day:%y%j}{newcomers:02d}"
                customer = _card(get_or_create_customer(
                    business, phone, _name(len(spec.first_30) + (day.toordinal() * 3 + newcomers) % 1900, spec),
                    verified=True), phone, spec)
                profile = _profile(phone, spec)
                customers.append(customer)
                profiles.append(profile)
                due[customer.id], visits[customer.id] = day, 0
            elif waiting and (kind != "walkin" or rnd.random() < .4):
                customer, profile = waiting.pop()
            elif kind != "walkin":   # sırası gelmiş kimse kalmadıysa biri erken gelir
                customer, profile = rnd.choice(coming)
            if customer and customer.id in seen:
                continue
            if profile and rnd.random() < .8:
                chosen = [services[profile["service"]]]
            else:
                chosen = [rnd.choices(services, weights)[0]]
            if chosen[0].name == spec.saturday_only and day.weekday() != 5:
                chosen = [services[spec.fallback]]
            if chosen[0].duration >= 30 and chosen[0].name != spec.saturday_only and addons and rnd.random() < .15:
                chosen.append(rnd.choice(addons))
            able = eligible_staff(business, chosen)
            if not able:
                continue
            favourite = staff[profile["staff"]] if profile else None
            person = favourite if favourite in able and rnd.random() < .75 else rnd.choices(
                able, [spec.staff[staff.index(s)][3] if s in staff else 10 for s in able])[0]
            duration = sum(s.duration for s in chosen)
            times = day_slots(business, [person], day, duration, now=booked_at, enforce_rules=False)[person.id]
            if kind == "walkin":   # bugün içinde de ileri bir saate yazılamaz
                times = [t for t in times if t <= now]
            if not times:
                continue
            # Akşam saatleri ve cumartesi öğleden sonrası daha yoğun
            start = rnd.choices(times, [1 + 2 * (t.astimezone(tz).hour >= 16) for t in times])[0]
            try:
                appt = create_appointment(business, chosen, start, staff=person, customer=customer,
                                          source="manual" if kind == "walkin" else kind,
                                          now=booked_at, notify=False)
            except BookingError:
                continue
            if kind == "walkin":
                appt.source = Appointment.Source.WALKIN
                appt.save(update_fields=["source"])
            made += 1
            if customer:
                seen.add(customer.id)
                visits[customer.id] += 1
                due[customer.id] = day + timedelta(days=profile["interval"] + rnd.randint(-3, 4))
            if appt.end < now:
                _close(appt, rnd, flaky=bool(profile and profile["flaky"]))
        # Günün ilk doldurulmasında bir iki iptal de olur (hedefe sayılmaz).
        if existing == 0 and waiting and rnd.random() < .5:
            customer, profile = waiting.pop()
            person = staff[profile["staff"]]
            chosen = [services[0]]
            times = day_slots(business, [person], day, 30, now=booked_at, enforce_rules=False)[person.id]
            if times:
                try:
                    appt = create_appointment(business, chosen, rnd.choice(times), staff=person,
                                              customer=customer, now=booked_at, notify=False)
                    cancel_appointment(appt, by_customer=True, now=booked_at)
                except BookingError:
                    pass
        created += made
    return {"created": created, "closed": closed, "business": business}
