from django.contrib import admin
from django.urls import include, path

from core import pwa
from public.views import feedback, landing

urlpatterns = [
    path("", landing, name="landing"),
    path("yonetim/", admin.site.urls),
    path("panel/", include("panel.urls")),
    path("gorus/", feedback, name="feedback"),
    path("uygulama.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("cevrimdisi/", pwa.offline, name="offline"),
    # Kuaför sayfaları en sonda: site.com/kuafor-adi/
    path("", include("public.urls")),
]
