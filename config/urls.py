from django.contrib import admin
from django.urls import include, path

from public.views import landing

urlpatterns = [
    path("", landing, name="landing"),
    path("yonetim/", admin.site.urls),
    path("panel/", include("panel.urls")),
    # Kuaför sayfaları en sonda: site.com/kuafor-adi/
    path("", include("public.urls")),
]
