"""Ana ekrana eklenebilen uygulama (PWA): bildirim dosyası, hizmet betiği ve çevrimdışı sayfası.

İki uygulama tanımı vardır. Kuaför paneli için olan platformun adını taşır ve panelde açılır;
her dükkânın kendi tanımı ise müşterinin ana ekranına dükkânın adıyla yerleşir ve o dükkânın
sayfasında açılır. Hizmet betiği hiçbir sayfayı ya da randevu verisini saklamaz: yalnızca bağlantı
yokken çevrimdışı sayfasını gösterir.
"""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static
from django.urls import reverse

from .context import static_version
from .models import Business

PAPER = "#f4f1ea"


def _short(name):
    """Ana ekrandaki etiket 12 harfi geçince kesilir: sığmıyorsa adın son sözü kullanılır."""
    return name if len(name) <= 12 else name.split()[-1][:12]


def _manifest(name, short_name, start, scope, description, shortcuts):
    version = static_version()
    icon = lambda file: f"{static('icons/' + file)}?v={version}"   # noqa: E731
    return JsonResponse({
        "id": start, "name": name, "short_name": short_name, "description": description,
        "start_url": start, "scope": scope, "display": "standalone", "lang": "tr", "dir": "ltr",
        "background_color": PAPER, "theme_color": PAPER,
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icon("maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [{"name": label, "url": url} for label, url in shortcuts],
    }, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


def manifest(request):
    """Kuaförün uygulaması: panelde açılır."""
    return _manifest(
        settings.SITE_NAME, _short(settings.SITE_NAME), reverse("panel:today"), "/",
        "Kuaför paneli: bugünün randevuları, takvim, müşteriler ve ciro.",
        [("Bugün", reverse("panel:today")), ("Takvim", reverse("panel:calendar"))])


def shop_manifest(request, slug):
    """Müşterinin uygulaması: dükkânın adıyla, dükkânın sayfasında açılır."""
    business = get_object_or_404(Business, slug=slug)
    home = reverse("public:business", args=[slug])
    return _manifest(
        business.name, _short(business.name), home, home, f"{business.name} · online randevu",
        [("Randevu al", reverse("public:book_select", args=[slug])),
         ("Randevularım", reverse("public:account", args=[slug]))])


def service_worker(request):
    response = render(request, "sw.js", {"version": static_version()}, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"   # tarayıcı her açılışta yenisini sorar
    return response


def offline(request):
    return render(request, "offline.html")
