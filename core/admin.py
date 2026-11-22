"""Süper yönetici paneli: kuaför hesapları, abonelik durumu, SMS kullanımı."""
from django.contrib import admin
from django.db.models import Count, Q, Sum

from .models import (Appointment, AuditLog, Business, Customer, Membership, MessageLog,
                     Service, Staff, TimeOff, WorkingHours)

admin.site.site_header = "Platform yönetimi"
admin.site.site_title = "Platform yönetimi"


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "status", "trial_ends", "sms_credit",
                    "appointments_30d", "sms_sent", "sms_delivery", "created_at")
    list_filter = ("status", "plan")
    list_editable = ("status", "plan")
    search_fields = ("name", "slug", "phone")
    inlines = [MembershipInline]
    actions = ["add_sms_credit", "suspend", "activate"]

    def get_queryset(self, request):
        from django.utils import timezone
        since = timezone.now() - timezone.timedelta(days=30)
        return super().get_queryset(request).annotate(
            _appts=Count("appointments", filter=Q(appointments__created_at__gte=since), distinct=True),
        )

    @admin.display(description="Randevu (30 gün)", ordering="_appts")
    def appointments_30d(self, obj):
        return obj._appts

    @admin.display(description="Gönderilen SMS")
    def sms_sent(self, obj):
        return obj.messages.filter(status="sent").aggregate(n=Sum("segments"))["n"] or 0

    @admin.display(description="SMS teslim")
    def sms_delivery(self, obj):
        sent = obj.messages.filter(status="sent").count()
        failed = obj.messages.filter(status="failed").count()
        return f"%{100 * sent / (sent + failed):.0f}" if sent + failed else "—"

    @admin.action(description="500 SMS kredisi ekle")
    def add_sms_credit(self, request, queryset):
        for b in queryset:
            b.sms_credit += 500
            b.save(update_fields=["sms_credit"])

    @admin.action(description="Hesabı kapat")
    def suspend(self, request, queryset):
        queryset.update(status=Business.Status.SUSPENDED)

    @admin.action(description="Hesabı aktif yap")
    def activate(self, request, queryset):
        queryset.update(status=Business.Status.ACTIVE)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("start", "business", "staff", "customer", "status", "source", "planned_total")
    list_filter = ("status", "source", "business")
    date_hierarchy = "start"
    raw_id_fields = ("customer",)


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ("scheduled_at", "business", "phone", "kind", "status", "segments", "cost", "error")
    list_filter = ("status", "kind", "business")
    date_hierarchy = "scheduled_at"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "business", "no_show_count", "blocked", "marketing_consent")
    list_filter = ("business", "blocked")
    search_fields = ("name", "phone")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "business", "action", "appointment", "user", "detail")
    list_filter = ("action", "business")


for model in (Service, Staff, WorkingHours, TimeOff):
    admin.site.register(model)
