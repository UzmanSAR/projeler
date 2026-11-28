"""Kurulum sihirbazı: yeni işletme beş dakikada yayında olsun diye türüne göre hazır şablon."""
from datetime import time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Business, Membership, Service, Staff, WorkingHours

# (ad, süre dk, fiyat ₺): işletme sonradan değiştirir, ekler, siler.
TEMPLATE_SERVICES = {
    Business.Kind.MEN: [("Saç kesimi", 30, 400), ("Sakal tıraşı", 20, 250), ("Saç + sakal", 45, 600)],
    Business.Kind.WOMEN: [("Kesim", 45, 600), ("Fön", 30, 350), ("Dip boya", 90, 1500)],
    Business.Kind.UNISEX: [("Kadın kesim", 45, 600), ("Erkek kesim", 30, 400), ("Fön", 30, 350)],
    Business.Kind.BEAUTY: [("Cilt bakımı", 60, 1200), ("Kaş tasarımı", 20, 300), ("Manikür", 40, 450)],
}


@transaction.atomic
def create_business(user, name, slug, owner_name, closed_weekday=6,
                    open_at=time(9, 0), close_at=time(20, 0), phone="", kind=Business.Kind.MEN):
    business = Business.objects.create(
        name=name, slug=slug, phone=phone, whatsapp=phone, kind=kind,
        trial_ends=timezone.localdate() + timedelta(days=settings.TRIAL_DAYS),
    )
    Membership.objects.create(user=user, business=business)
    WorkingHours.objects.bulk_create([
        WorkingHours(business=business, weekday=d, closed=(d == closed_weekday),
                     open=open_at, close=close_at)
        for d in range(7)
    ])
    services = [
        Service.objects.create(business=business, name=n, duration=d, price=p, order=i)
        for i, (n, d, p) in enumerate(TEMPLATE_SERVICES[kind])
    ]
    staff = Staff.objects.create(business=business, name=owner_name)
    staff.services.set(services)
    return business
