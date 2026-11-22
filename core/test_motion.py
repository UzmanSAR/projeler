"""Hareket katmanının bağlantıları: şablon kancaları ve app.js içindeki ekran sırası tablosu."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

import panel.urls
import public.urls

# static/js/app.js içindeki SCREENS tablosu bu adres parçalarını tanır (ekran adı ve sırası).
RANKED = {"giris", "kayit", "takvim", "musteriler", "raporlar", "ayarlar",
          "randevu", "saat", "bilgi", "kod", "hesabim"}
# Bilerek tabloya alınmayanlar: sayfa göstermeyen ya da kendi sırası olmayan adresler.
IGNORED = {"cikis", "randevusuz", "r"}


def first_literal(route):
    """Adresin ilk sabit parçası; yalnızca <değişken>lerden oluşuyorsa None."""
    for part in str(route).split("/"):
        if part and not part.startswith("<"):
            return part
    return None


class MotionWiringTests(TestCase):
    @override_settings(MOTION="full")
    def test_base_template_is_wired(self):
        html = self.client.get("/").content.decode()
        self.assertIn("js/app.js", html)
        self.assertIn('id="eof"', html)
        self.assertIn('data-motion="full"', html)
        self.assertIn("@view-transition", html)
        with override_settings(MOTION="off"):   # kapatma düğmesi: geçiş izni sayfaya hiç yazılmaz
            html = self.client.get("/").content.decode()
        self.assertIn('data-motion="off"', html)
        self.assertNotIn("@view-transition", html)

    def test_rank_table_mirrors_urls(self):
        js = (Path(settings.BASE_DIR) / "static" / "js" / "app.js").read_text(encoding="utf-8")
        for literal in sorted(RANKED):
            self.assertIn(literal, js, f"app.js içindeki sıra tablosunda '{literal}' yok")
        for module in (public.urls, panel.urls):
            for pattern in module.urlpatterns:
                literal = first_literal(pattern.pattern)
                if literal is None:
                    continue
                self.assertIn(
                    literal, RANKED | IGNORED,
                    f"{module.__name__}: '{pattern.pattern}' için app.js içindeki SCREENS tablosunda sıra kararı "
                    "verilmeli (RANKED) ya da adres bilerek dışarıda bırakılmalı (IGNORED).",
                )
