from django.contrib import admin
from django.urls import include, path, re_path

from core import pwa
from public.views import feedback, landing, style_image

urlpatterns = [
    path("", landing, name="landing"),
    path("yonetim/", admin.site.urls),
    path("panel/", include("panel.urls")),
    path("gorus/", feedback, name="feedback"),
    re_path(r"^m/(?P<pk>\d+)-(?P<digest>[0-9a-f]{12})\.webp$", style_image, name="style_image"),
    re_path(r"^m/(?P<pk>\d+)-(?P<digest>[0-9a-f]{12})-(?P<size>k)\.webp$", style_image, name="style_thumb"),
    path("uygulama.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("cevrimdisi/", pwa.offline, name="offline"),
    # Kuaför sayfaları en sonda: site.com/kuafor-adi/
    path("", include("public.urls")),
]
