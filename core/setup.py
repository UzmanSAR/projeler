"""Kurulum sihirbazı: yeni dükkân beş dakikada yayında olsun diye hazır şablon."""
from datetime import time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Business, Membership, Service, Staff, WorkingHours

TEMPLATE_SERVICES = [
    ("Saç kesimi", 30, 400),
    ("Sakal tıraşı", 20, 250),
    ("Saç + sakal", 45, 600),
]


@transaction.atomic
def create_business(user, name, slug, owner_name, closed_weekday=6,
                    open_at=time(9, 0), close_at=time(20, 0), phone=""):
    business = Business.objects.create(
        name=name, slug=slug, phone=phone, whatsapp=phone,
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
        for i, (n, d, p) in enumerate(TEMPLATE_SERVICES)
    ]
    staff = Staff.objects.create(business=business, name=owner_name)
    staff.services.set(services)
    return business
