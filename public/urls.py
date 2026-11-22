from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("<slug:slug>/", views.business_page, name="business"),
    path("<slug:slug>/randevu/", views.book_select, name="book_select"),
    path("<slug:slug>/randevu/saat/", views.book_time, name="book_time"),
    path("<slug:slug>/randevu/bilgi/", views.book_details, name="book_details"),
    path("<slug:slug>/randevu/kod/", views.book_verify, name="book_verify"),
    path("<slug:slug>/hesabim/", views.account, name="account"),
    path("<slug:slug>/hesabim/unut/", views.account_forget, name="account_forget"),
    path("<slug:slug>/r/<str:token>/", views.appointment, name="appointment"),
    path("<slug:slug>/r/<str:token>/iptal/", views.appointment_cancel, name="appointment_cancel"),
    path("<slug:slug>/r/<str:token>/izin/", views.appointment_consent, name="appointment_consent"),
    path("<slug:slug>/r/<str:token>/takvim.ics", views.appointment_ics, name="appointment_ics"),
]
