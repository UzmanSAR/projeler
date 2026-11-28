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


def without_token_blocks(css):
    """Belirteç blokları (:root ile başlayanlar ve koyu tema medya blokları) çıkarılmış CSS: bileşen kuralları."""
    out, i = [], 0
    for m in re.finditer(r"^(:root[^{\n]*|@media \(prefers-color-scheme: dark\)) \{", css, re.M):
        if m.start() < i:
            continue
        out.append(css[i:m.start()])
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j
    out.append(css[i:])
    return "".join(out)


PLAIN = re.compile(r"\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))\s*")
TONES = ("turkuaz", "pembe", "yesil")


class ThemeTokenTests(TestCase):
    def setUp(self):
        self.css = (CSS / "app.css").read_text()
        self.media = block(self.css, "@media (prefers-color-scheme: dark)")
        self.auto_dark = tokens(block(self.media, ':root:not([data-theme="light"])'))
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
        plain = {k for k, v in self.light.items() if PLAIN.fullmatch(v)}
        missing = plain - set(self.auto_dark) - same_on_purpose
        self.assertFalse(missing, "koyu temada karşılığı yok: %s" % sorted(missing))

    def test_tones_redefine_the_same_tokens_in_light_and_dark(self):
        tone_media = block(self.css[self.css.index(':root[data-tone="turkuaz"] {'):], "@media (prefers-color-scheme: dark)")
        for tone in TONES:
            light = tokens(block(self.css, f':root[data-tone="{tone}"]'))
            auto = tokens(block(tone_media, f':root[data-tone="{tone}"]:not([data-theme="light"])'))
            chosen = tokens(block(self.css, f':root[data-tone="{tone}"][data-theme="dark"]'))
            self.assertTrue(light, tone)
            self.assertEqual(auto, chosen, tone)
            self.assertEqual(set(light), set(auto), tone)              # koyu temada her vurgu yeniden tanımlı
            self.assertFalse(set(light) - set(self.light), tone)      # yalnızca var olan belirteçler

    def test_paper_scope_dark_blocks_are_identical(self):
        auto = tokens(block(self.css, ':root:not([data-theme="light"]) .scope-paper'))
        chosen = tokens(block(self.css, ':root[data-theme="dark"] .scope-paper'))
        light = tokens(block(self.css, ":root .scope-paper"))
        self.assertTrue(auto)
        self.assertEqual(auto, chosen)
        self.assertEqual(set(auto), set(light))

    def test_component_rules_take_colours_from_tokens(self):
        rest = without_token_blocks(self.css)
        self.assertNotIn("--accent:", rest)                            # bütün belirteç blokları çıktı
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
        html = self.client.get(f"/{self.b.slug}/").content.decode()
        self.assertIn('<meta name="color-scheme" content="light dark">', html)
        self.assertIn('media="(prefers-color-scheme: dark)"', html)            # salon sayfası: çubuk temaya uyar
        self.assertNotIn("data-theme=", html.split("<body")[0].split("<html")[1].split(">")[0])  # sunucu tema seçmez
        landing = self.client.get("/").content.decode()
        self.assertIn('class="scope-paper"', landing)                          # ana sayfa: kâğıt gövde, siyah açılış
        self.assertIn('lp-intro scope-ink', landing)
        self.assertIn('content="#0c0d0f"', landing)

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

    def test_toggle_icon_on_every_page(self):
        pages = ["/", "/gizlilik/", "/iletisim/", "/gorus/", "/panel/giris/", "/panel/kayit/",
                 f"/{self.b.slug}/", f"/{self.b.slug}/randevu/", f"/{self.b.slug}/hesabim/"]
        for url in pages:
            html = self.client.get(url).content.decode()
            self.assertEqual(html.count("data-theme-toggle"), 1, url)    # tek simge, sayfanın üstünde
            self.assertIn('aria-label="Koyu tema"', html, url)
        self.client.force_login(self.user)
        for url in ("/panel/", "/panel/takvim/", "/panel/musteriler/", "/panel/raporlar/", "/panel/ayarlar/"):
            self.assertIn("data-theme-toggle", self.client.get(url).content.decode(), url)
        self.assertIn('onclick="flip()"', self.client.get("/cevrimdisi/").content.decode())

    def test_not_found_page_has_the_toggle(self):
        from django.test import override_settings
        with override_settings(DEBUG=False):
            r = self.client.get("/boyle-bir-salon-yok/")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Bu sayfa bulunamadı", r.content.decode())
        self.assertIn("data-theme-toggle", r.content.decode())

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


class ToneTests(TestCase):
    """İşletmenin rengi: erkek kuaförü turkuaz, kadın kuaförü ve güzellik merkezi pembe, karma yeşil; ayardan değişir."""

    def setUp(self):
        cache.clear()
        self.b, self.user = make_business("ali")

    def html_tag(self, url):
        html = self.client.get(url).content.decode()
        return html[html.index("<html"):html.index(">", html.index("<html")) + 1], html

    def test_tone_follows_kind_unless_chosen(self):
        from core.models import Business
        expected = {Business.Kind.MEN: "turkuaz", Business.Kind.WOMEN: "pembe",
                    Business.Kind.BEAUTY: "pembe", Business.Kind.UNISEX: "yesil"}
        for kind, tone in expected.items():
            self.b.kind = kind
            self.assertEqual(self.b.active_tone, tone, kind)
        self.b.kind, self.b.tone = Business.Kind.MEN, Business.Tone.PINK
        self.assertEqual(self.b.active_tone, "pembe")
        self.assertTrue(self.b.lights)
        self.b.tone = Business.Tone.GREEN
        self.assertFalse(self.b.lights)

    def test_shop_pages_carry_tone_lights_and_emblem(self):
        tag, html = self.html_tag(f"/{self.b.slug}/")
        self.assertIn('data-tone="turkuaz"', tag)
        self.assertIn("data-lights", tag)
        self.assertIn('class="emblem"', html)
        self.assertIn('class="card lit"', html)                 # hizmet listesi çerçevesi
        self.b.kind = "karma"; self.b.save()
        tag, _ = self.html_tag(f"/{self.b.slug}/randevu/")
        self.assertIn('data-tone="yesil"', tag)
        self.assertNotIn("data-lights", tag)                    # yeşil temada ışık dönmez
        tag, _ = self.html_tag("/")
        self.assertNotIn("data-tone", tag)                      # platform sayfaları kurumsal renkte

    def test_panel_takes_the_tone_and_settings_change_it(self):
        self.client.force_login(self.user)
        tag, _ = self.html_tag("/panel/")
        self.assertIn('data-tone="turkuaz"', tag)
        self.assertNotIn("data-lights", tag)                    # panelde ışık yok, yalnızca renk
        settings_page = self.client.get("/panel/ayarlar/").content.decode()
        self.assertIn('name="tone"', settings_page)
        from panel.forms import BusinessForm
        data = {k: v for k, v in BusinessForm(instance=self.b).initial.items() if v is not None}
        data.update(tone="pembe", remind_manual="on" if self.b.remind_manual else "")
        r = self.client.post("/panel/ayarlar/", data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        self.b.refresh_from_db()
        self.assertEqual(self.b.tone, "pembe")
        tag, _ = self.html_tag(f"/{self.b.slug}/")
        self.assertIn('data-tone="pembe"', tag)

    def test_emblem_drawing_per_kind(self):
        from django.template.loader import render_to_string
        men = render_to_string("public/_emblem.html", {"kind": "erkek"})
        women = render_to_string("public/_emblem.html", {"kind": "kadin"})
        beauty = render_to_string("public/_emblem.html", {"kind": "guzellik"})
        self.assertIn('class="solid"', men)                     # ustura sapı
        self.assertIn('class="spark"', women)                   # fön makinesinin hava çizgileri
        self.assertIn('class="star"', beauty)
        self.assertEqual(len({men, women, beauty}), 3)


class CalendarTests(TestCase):
    def setUp(self):
        cache.clear()
        self.b, self.user = make_business("ali")
        self.client.force_login(self.user)

    def test_staff_chips_counts_and_readable_events(self):
        from datetime import datetime, time, timedelta
        from core.booking import create_appointment, get_or_create_customer
        from core.tests import TZ
        self.b.staff.create(name="Veli")
        ali = self.b.staff.get(name="Ali")
        cut = self.b.services.get(name="Saç kesimi")
        day = datetime.now(TZ).date() + timedelta(days=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        customer = get_or_create_customer(self.b, "05321112233", "Ayşe Kara", verified=True)
        create_appointment(self.b, [cut], datetime.combine(day, time(10, 0), TZ), staff=ali, customer=customer)
        html = self.client.get(f"/panel/takvim/?g={day:%Y-%m-%d}").content.decode()
        self.assertIn('class="cal-staff"', html)
        self.assertIn("1 randevu", html)                        # Ali'nin sütun başlığı
        self.assertIn("Boş", html)                              # Veli'nin sütunu
        self.assertIn("10:00<span class=\"end\">–10:30</span>", html)
        self.assertIn("Ayşe Kara", html)
        self.assertIn("Bugüne dön", html)
        self.assertNotIn("Siyah kenar", html)
