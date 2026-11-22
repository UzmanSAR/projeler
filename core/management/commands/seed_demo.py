"""Denemek için örnek dükkân ve yaklaşık yedi haftalık randevu geçmişi üretir.

    python manage.py seed_demo
    Panel girişi: demo@example.com / demo-sifre-1   Sayfa: /ornek-berber/
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.availability import business_tz, day_slots
from core.booking import BookingError, close_appointment, create_appointment, get_or_create_customer
from core.models import Business, Service, Staff
from core.setup import create_business

NAMES = ["Ahmet Yılmaz", "Mehmet Kaya", "Mustafa Demir", "Emre Şahin", "Burak Çelik", "Can Yıldız",
         "Oğuz Aydın", "Serkan Arslan", "Hakan Doğan", "Kerem Kılıç", "Onur Aslan", "Tolga Çetin",
         "Volkan Kara", "Barış Koç", "Deniz Kurt", "Efe Özkan", "Furkan Polat", "Gökhan Öztürk",
         "Halil Şimşek", "İsmail Korkmaz", "Kaan Erdoğan", "Levent Yavuz", "Murat Can", "Nihat Acar",
         "Okan Güneş", "Selim Bulut", "Taner Aksoy", "Ufuk Tekin", "Yusuf Bozkurt", "Zafer Özdemir"]


class Command(BaseCommand):
    help = "Örnek dükkân ve randevu geçmişi oluşturur."

    def handle(self, *args, **options):
        if Business.objects.filter(slug="ornek-berber").exists():
            self.stdout.write("Örnek dükkân zaten var.")
            return
        rnd = random.Random(7)
        User = get_user_model()
        user = User.objects.create_user("demo@example.com", "demo@example.com", "demo-sifre-1")
        b = create_business(user, "Örnek Berber Salonu", "ornek-berber", "Ali", phone="05320000000")
        b.description = "Mahallenin berberi. Saç, sakal ve cilt bakımı."
        b.address = "Örnek Mah. Çarşı Cad. No: 12"
        b.district = "Örnek Mahallesi"
        b.save()
        extra = [Service.objects.create(business=b, name="Cilt bakımı", duration=30, price=500, order=3),
                 Service.objects.create(business=b, name="Çocuk tıraşı", duration=20, price=250, order=4)]
        ali = b.staff.get()
        ali.services.add(*extra)
        mert = Staff.objects.create(business=b, name="Mert", order=1)
        mert.services.set(b.services.all())
        services = list(b.services.all())
        weights = [30, 12, 34, 6, 6]
        customers = [get_or_create_customer(b, f"0532{1000000 + i:07d}", n, verified=True)
                     for i, n in enumerate(NAMES)]

        tz = business_tz(b)
        now = timezone.now()
        today = now.astimezone(tz).date()
        created = 0
        for offset in range(-48, 6):
            day = today + timedelta(days=offset)
            booked_at = datetime.combine(day, time(6), tz) - timedelta(days=1)
            target = rnd.randint(9, 15) + (6 if day.weekday() in (4, 5) else 0)
            if offset > 0:
                target = max(2, target // (offset + 1))
            for _ in range(target):
                service = rnd.choices(services, weights)[0]
                slots = day_slots(b, [ali, mert], day, service.duration, now=booked_at,
                                  enforce_rules=False)
                staff = rnd.choice([ali, mert])
                times = slots[staff.id]
                if not times:
                    continue
                # Akşam saatleri daha yoğun
                start = rnd.choices(times, [1 + 2 * (t.astimezone(tz).hour >= 16) for t in times])[0]
                source = rnd.choices(["online", "manual", "walkin"], [45, 30, 25])[0]
                customer = None if source == "walkin" and rnd.random() < .5 else rnd.choice(customers)
                if source == "online" and customer is None:
                    source = "manual"
                try:
                    appt = create_appointment(b, [service], start, staff=staff, customer=customer,
                                              source="manual" if source == "walkin" else source,
                                              now=booked_at, notify=False)
                except BookingError:
                    continue
                if source == "walkin":
                    appt.source = "walkin"
                    appt.save(update_fields=["source"])
                created += 1
                if appt.end < now:
                    if rnd.random() < .07 and source != "walkin":
                        close_appointment(appt, "no_show")
                    else:
                        tip = rnd.choice([0, 0, 0, 50])
                        close_appointment(appt, "completed", amount=appt.planned_total + tip,
                                          payment=rnd.choice(["cash", "cash", "card"]))
        self.stdout.write(self.style.SUCCESS(
            f"{created} randevu oluşturuldu. Panel: demo@example.com / demo-sifre-1 · Sayfa: /ornek-berber/"))
