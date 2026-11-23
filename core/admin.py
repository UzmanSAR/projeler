"""Süper yönetici paneli: kuaför hesapları, abonelik durumu, SMS kullanımı."""
from django.contrib import admin
from django.db.models import Count, Q, Sum

from . import billing
from .models import (Appointment, AuditLog, Business, Customer, Feedback, Membership, MessageLog,
                     PlatformSettings, Service, Staff, SubscriptionPayment, TimeOff, WorkingHours)

admin.site.site_header = "Platform yönetimi"
admin.site.site_title = "Platform yönetimi"


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


class PaymentInline(admin.TabularInline):
    """Ödeme satırı eklenince üyelik bitişi kendiliğinden ilerler; tutar ve dönem boş bırakılabilir."""
    model = SubscriptionPayment
    extra = 0
    fields = ("paid_on", "amount", "period_start", "period_end", "method", "note")


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "status", "trial_ends", "paid_until", "price", "sms_credit",
                    "appointments_30d", "sms_sent", "sms_delivery", "created_at")
    list_filter = ("status", "plan")
    list_editable = ("status", "plan")
    search_fields = ("name", "slug", "phone")
    inlines = [MembershipInline, PaymentInline]
    actions = ["record_month", "add_sms_credit", "suspend", "activate"]

    @admin.display(description="Aylık ücret")
    def price(self, obj):
        return f"{billing.price_for(obj):.0f} ₺"

    @admin.action(description="1 aylık üyelik ödemesi kaydet (ödendi)", permissions=["change"])
    def record_month(self, request, queryset):
        for b in queryset:
            p = billing.record_payment(b)
            self.message_user(request, f"{b.name}: {p.amount:.0f} ₺ kaydedildi, üyelik "
                                       f"{p.period_end:%d.%m.%Y} tarihine kadar geçerli.")

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


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("business", "paid_on", "amount", "period_start", "period_end", "method", "note")
    list_filter = ("method",)
    search_fields = ("business__name", "business__slug", "note")
    autocomplete_fields = ("business",)
    date_hierarchy = "paid_on"


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    """Tek satır: aylık ücret ve kuaföre gösterilecek ödeme bilgisi."""
    list_display = ("__str__", "monthly_price")

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        PlatformSettings.load()   # ilk açılışta satır hazır olsun
        return super().changelist_view(request, extra_context)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("created_at", "sender", "business", "short", "name", "contact", "is_read")
    list_filter = ("is_read", "sender")
    list_editable = ("is_read",)
    search_fields = ("message", "name", "contact", "business__name")
    readonly_fields = ("sender", "business", "user", "name", "contact", "message", "page", "created_at")
    actions = ["mark_read"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Görüş")
    def short(self, obj):
        return obj.message[:90] + ("…" if len(obj.message) > 90 else "")

    @admin.action(description="Okundu işaretle")
    def mark_read(self, request, queryset):
        queryset.update(is_read=True)

