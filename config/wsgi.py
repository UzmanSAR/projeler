"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()


def _refresh_demo():
    """Tanıtım kurulumu: örnek dükkâna yeni günleri ekler, geçmişe düşen örnek randevuları kapatır."""
    import logging

    from django.db import connection
    try:
        from core.demo import ensure_demo
        ensure_demo()
    except Exception:  # örnek veri yüzünden site açılmaz olmasın
        logging.getLogger(__name__).exception("Örnek dükkân güncellenemedi")
    finally:
        connection.close()


# Ücretsiz barındırmada süreç boşta kapanır, ilk ziyarette yeniden başlar: örnek salonlar her
# başlangıçta tazelenir. İstekleri bekletmemek için ayrı bir iş parçacığında, sunucu açılıp ilk
# istekler (ve sağlık yoklaması) yanıtlandıktan sonra çalışır: modüller aynı anda iki yerden yüklenmez.
if os.environ.get("SEED_DEMO") == "1":
    import threading

    timer = threading.Timer(20.0, _refresh_demo)
    timer.name, timer.daemon = "demo-refresh", True
    timer.start()
