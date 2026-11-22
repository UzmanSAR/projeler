"""Platform yöneticisini ortam değişkenlerinden oluşturur (komut satırı olmayan barındırma için).

SUPERUSER_EMAIL ve SUPERUSER_PASSWORD verilmişse çalışır. Kullanıcı zaten varsa
şifresine dokunmaz; yalnızca yönetici yetkisini verir.
"""
import os

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "SUPERUSER_EMAIL / SUPERUSER_PASSWORD ile platform yöneticisi oluşturur."

    def handle(self, *args, **options):
        email = os.environ.get("SUPERUSER_EMAIL", "").strip().lower()
        password = os.environ.get("SUPERUSER_PASSWORD", "")
        if not email or not password:
            self.stdout.write("SUPERUSER_EMAIL / SUPERUSER_PASSWORD verilmemiş; atlandı.")
            return
        User = get_user_model()
        user = User.objects.filter(username=email).first()
        if user is None:
            try:
                password_validation.validate_password(password)
            except ValidationError as exc:
                raise CommandError("SUPERUSER_PASSWORD yeterince güçlü değil: " + " ".join(exc.messages))
            User.objects.create_superuser(username=email, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Platform yöneticisi oluşturuldu: {email}"))
        elif not (user.is_superuser and user.is_staff):
            user.is_superuser = user.is_staff = True
            user.save(update_fields=["is_superuser", "is_staff"])
            self.stdout.write(self.style.SUCCESS(f"{email} platform yöneticisi yapıldı (şifre değişmedi)."))
        else:
            self.stdout.write(f"Platform yöneticisi zaten var: {email}")
