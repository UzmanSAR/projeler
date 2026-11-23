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


# Ücretsiz barındırmada süreç boşta kapanır, ilk ziyarette yeniden başlar: örnek dükkân her
# başlangıçta tazelenir. İstekleri bekletmemek için ayrı bir iş parçacığında çalışır.
if os.environ.get("SEED_DEMO") == "1":
    import threading

    threading.Thread(target=_refresh_demo, name="demo-refresh", daemon=True).start()
