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

    def test_static_urls_carry_a_content_version(self):
        from core.context import static_version
        html = self.client.get("/").content.decode()
        version = static_version()
        self.assertRegex(version, r"^[0-9a-f]{10}$")
        for name in ("css/app.css", "js/app.js", "css/public.css", "js/public.js"):
            self.assertIn(f"{name}?v={version}", html)

    def test_kill_switch_spellings(self):
        """MOTION değeri ayar dosyasında sadeleşir: OFF, Off, 'off ', 0, false hepsi kapatır."""
        import os
        import subprocess
        import sys
        code = "from django.conf import settings; print(settings.MOTION)"
        for raw, want in (("OFF", "off"), ("Off ", "off"), ("0", "off"), ("false", "off"), ("kapalı", "off"),
                          ("Lite", "lite"), ("FULL", "full"), ("", "full")):
            env = dict(os.environ, MOTION=raw, DJANGO_SETTINGS_MODULE="config.settings")
            out = subprocess.run([sys.executable, "-c", code], env=env, cwd=settings.BASE_DIR,
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, want, f"MOTION={raw!r}")

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
