from django.core.management.base import BaseCommand

from core.sms import send_due


class Command(BaseCommand):
    help = "Zamanı gelmiş hatırlatma mesajlarını gönderir. Cron ile dakikada bir çalıştırın."

    def handle(self, *args, **options):
        self.stdout.write(f"{send_due()} mesaj gönderildi")
