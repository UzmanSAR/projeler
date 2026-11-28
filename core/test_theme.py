"""Açık ve koyu tema: renkler yalnızca belirteçlerden gelir, iki koyu blok aynı kalır, seçim düğmesi sayfalarda durur."""
import re
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from core.tests import make_business

CSS = Path(settings.BASE_DIR) / "static" / "css"
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")


def block(css, selector):
    """`selector {` ile açılan bloğun içi (iç içe süslü parantezler sayılır)."""
    start = css.index(selector + " {") + len(selector) + 2
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start:i - 1]


def tokens(body):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))


class ThemeTokenTests(TestCase):
    def setUp(self):
        self.css = (CSS / "app.css").read_text()
        media = block(self.css, "@media (prefers-color-scheme: dark)")
        self.auto_dark = tokens(block(media, ':root:not([data-theme="light"])'))
        self.chosen_dark = tokens(block(self.css, ':root[data-theme="dark"]'))
        self.light = tokens(block(self.css, ":root"))

    def test_both_dark_blocks_are_identical(self):
        self.assertTrue(self.auto_dark)
        self.assertEqual(self.auto_dark, self.chosen_dark)

    def test_every_dark_token_exists_in_light(self):
        missing = set(self.auto_dark) - set(self.light)
        self.assertFalse(missing, "koyu temada olup açık temada tanımsız: %s" % sorted(missing))

    def test_colour_tokens_are_redefined_for_dark(self):
        # açık temadaki her düz renk belirteci koyu temada da yeniden tanımlanır (bilerek aynı kalanlar hariç)
        same_on_purpose = {"--on-band", "--on-band-dim", "--band"}
        plain = {k for k, v in self.light.items() if re.fullmatch(r"\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))\s*", v)}
        missing = plain - set(self.auto_dark) - same_on_purpose
        self.assertFalse(missing, "koyu temada karşılığı yok: %s" % sorted(missing))

    def test_component_rules_take_colours_from_tokens(self):
        rest = self.css
        for sel in (":root", ':root[data-theme="dark"]'):
            rest = rest.replace(block(rest, sel), "", 1)
        rest = rest.replace(block(rest, "@media (prefers-color-scheme: dark)"), "", 1)
        allowed = ["rgba(0, 0, 0, .08)", "rgba(45, 106, 74, .5)", "rgba(45, 106, 74, 0)"]   # meşgul düğme gölgesi, onay halkası
        for a in allowed:
            rest = rest.replace(a, "")
        self.assertEqual(COLOR.findall(rest), [], "app.css içinde belirteç dışı renk")

    def test_other_stylesheets(self):
        self.assertEqual(COLOR.findall((CSS / "public.css").read_text()), [])
        landing = (CSS / "landing.css").read_text()
        # izin verilenler: örnek model görsellerinin geçişleri ve iki temada da koyu yeşil kalan kapanış bandı
        landing = re.sub(r"\.lp-look\.l\d i \{[^}]*\}", "", landing)
        landing = re.sub(r"\.lp-final[^{]*\{[^}]*\}", "", landing)
        self.assertEqual(COLOR.findall(landing), [])


class ThemeSwitchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.user = make_business("ali")

    def test_head_follows_the_phone(self):
        html = self.client.get("/").content.decode()
        self.assertIn('<meta name="color-scheme" content="light dark">', html)
        self.assertIn('media="(prefers-color-scheme: dark)"', html)
        self.assertNotIn("data-theme=", html.split("<body")[0].split("<html")[1].split(">")[0])  # sunucu tema seçmez

    def test_switch_on_corporate_shop_and_panel_pages(self):
        for url in ("/", "/gizlilik/", "/panel/giris/", f"/{self.b.slug}/", f"/{self.b.slug}/hesabim/"):
            html = self.client.get(url).content.decode()
            self.assertIn("data-theme-switch", html, url)
            self.assertIn('data-theme-set="dark"', html, url)
            self.assertNotIn("{#", html, url)   # Django'da {# #} tek satırlıktır; çok satırlı not sayfaya yazı olarak düşer
        self.client.force_login(self.user)
        html = self.client.get("/panel/ayarlar/").content.decode()
        self.assertIn("data-theme-switch", html)
        self.assertIn("Görünüm", html)

    def test_script_applies_the_choice_before_paint(self):
        js = (Path(settings.BASE_DIR) / "static" / "js" / "app.js").read_text()
        self.assertIn("localStorage.getItem(THEME)", js)
        self.assertIn("applyTheme(themeChoice());", js)
        html = self.client.get("/").content.decode()
        head = html.split("</head>")[0]
        self.assertIn("js/app.js", head)
        self.assertNotRegex(head, r'<script[^>]*app\.js[^>]*\b(defer|async)\b')

    def test_offline_page_has_both_themes(self):
        html = self.client.get("/cevrimdisi/").content.decode()
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn('data-theme="dark"', html)
