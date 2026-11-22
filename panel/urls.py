from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("giris/", auth_views.LoginView.as_view(template_name="panel/login.html"), name="login"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("kayit/", views.signup, name="signup"),
    path("", views.today, name="today"),
    path("randevu/<int:pk>/kapat/", views.appointment_close, name="close"),
    path("randevu/<int:pk>/iptal/", views.appointment_cancel, name="cancel"),
    path("randevusuz/", views.walkin, name="walkin"),
    path("takvim/", views.calendar, name="calendar"),
    path("takvim/ekle/", views.manual_create, name="manual_create"),
    path("takvim/kapat/", views.timeoff_create, name="timeoff_create"),
    path("takvim/kapat/<int:pk>/sil/", views.timeoff_delete, name="timeoff_delete"),
    path("musteriler/", views.customers, name="customers"),
    path("musteriler/<int:pk>/", views.customer_detail, name="customer"),
    path("raporlar/", views.report, name="report"),
    path("ayarlar/", views.settings_view, name="settings"),
    path("ayarlar/saatler/", views.hours, name="hours"),
    path("ayarlar/hizmet/", views.service_edit, name="service_add"),
    path("ayarlar/hizmet/<int:pk>/", views.service_edit, name="service_edit"),
    path("ayarlar/personel/", views.staff_edit, name="staff_add"),
    path("ayarlar/personel/<int:pk>/", views.staff_edit, name="staff_edit"),
]
