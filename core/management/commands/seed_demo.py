"""Örnek dükkânı oluşturur ya da günceller (core/demo.py).

    python manage.py seed_demo
    Panel girişi: demo@example.com / demo-sifre-1   Sayfa: /ornek-berber/

Tekrar çalıştırılabilir: eksik günleri doldurur, geçmişe düşen örnek randevuları kapatır.
"""
from django.core.management.base import BaseCommand

from core import demo


class Command(BaseCommand):
    help = "Örnek dükkânı ve randevu geçmişini oluşturur ya da günceller."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=demo.HISTORY_DAYS, help="kaç günlük geçmiş")
        parser.add_argument("--ahead", type=int, default=demo.AHEAD_DAYS, help="kaç gün ilerisi")

    def handle(self, *args, **options):
        result = demo.ensure_demo(history_days=options["days"], ahead_days=options["ahead"])
        self.stdout.write(self.style.SUCCESS(
            f"Örnek dükkân güncel: {result['created']} randevu eklendi, {result['closed']} randevu kapatıldı. "
            f"Panel: {demo.EMAIL} / {demo.PASSWORD} · Sayfa: /{demo.SLUG}/"))
