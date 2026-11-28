"""Veri modeli. Her kayıt bir işletmeye (kiracı) bağlıdır; sorgular her zaman
işletme kimliğiyle filtrelenir."""
import secrets
from datetime import time

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Func, Q
from django.utils import timezone

RESERVED_SLUGS = {
    "panel", "yonetim", "admin", "static", "media", "api", "giris", "kayit",
    "fiyatlar", "hakkinda", "destek", "kvkk", "robots.txt", "favicon.ico",
    "gorus", "cevrimdisi", "uygulama", "sw", "manifest", "m", "hesap", "gizlilik", "iletisim",
    "kosullar", "hakkimizda",
}

slug_validator = RegexValidator(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*$", "Yalnızca küçük harf, rakam ve tire kullanın."
)


def validate_slug_free(value):
    if value in RESERVED_SLUGS:
        raise ValidationError("Bu adres kullanılamaz.")


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Business(models.Model):
    class Kind(models.TextChoices):
        WOMEN = "kadin", "Kadın kuaförü"
        MEN = "erkek", "Erkek kuaförü"
        UNISEX = "karma", "Kadın ve erkek kuaförü"
        BEAUTY = "guzellik", "Güzellik merkezi"

    class Tone(models.TextChoices):
        """Müşteri sayfalarının ve panelin rengi (static/css/app.css: [data-tone])."""
        AUTO = "", "İşletme türüne göre"
        TURQUOISE = "turkuaz", "Turkuaz"
        PINK = "pembe", "Pembe"
        GREEN = "yesil", "Yeşil"

    class Plan(models.TextChoices):
        SOLO = "solo", "Tek Koltuk"
        SHOP = "shop", "Dükkân"
        SALON = "salon", "Salon"

    class Status(models.TextChoices):
        TRIAL = "trial", "Deneme"
        ACTIVE = "active", "Aktif"
        PAST_DUE = "past_due", "Ödeme bekliyor"
        SUSPENDED = "suspended", "Kapalı"

    name = models.CharField("işletme adı", max_length=80)
    kind = models.CharField("işletme türü", max_length=10, choices=Kind.choices, default=Kind.MEN)
    tone = models.CharField("renk", max_length=10, choices=Tone.choices, default=Tone.AUTO, blank=True,
                            help_text="Müşteri sayfanın ve panelin rengi. İşletme türüne göre seçildiğinde erkek "
                                      "kuaförü turkuaz, kadın kuaförü ve güzellik merkezi pembe, karma salon yeşil olur.")
    slug = models.CharField(
        "sayfa adresi", max_length=40, unique=True,
        validators=[slug_validator, validate_slug_free],
    )
    description = models.TextField("tanıtım", blank=True, max_length=600)
    address = models.CharField("adres", max_length=200, blank=True)
    district = models.CharField("semt / ilçe", max_length=60, blank=True)
    phone = models.CharField("telefon", max_length=20, blank=True)
    whatsapp = models.CharField("WhatsApp numarası", max_length=20, blank=True)
    maps_url = models.URLField("harita linki", blank=True)
    timezone = models.CharField(max_length=40, default="Europe/Istanbul")

    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.SOLO)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIAL)
    trial_ends = models.DateField(null=True, blank=True)
    # Aylık üyelik: bu tarihe kadar ödenmiştir; sonraki ödeme o gün beklenir. Elle yazılmaz: her zaman
    # ödeme kayıtlarından hesaplanır (core/billing.py sync). Ücretsiz süre 0 ₺'lik ödeme satırıyla verilir.
    paid_until = models.DateField("üyelik bitişi", null=True, blank=True, editable=False)
    monthly_price = models.DecimalField(
        "özel aylık ücret (₺)", max_digits=8, decimal_places=0, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Boş bırakılırsa platformun genel aylık ücreti uygulanır.")
    # Ödeme döngüsünün ay günü: kısa aydan sonra gün kaymasın diye tutulur (31 Oca -> 28 Şub -> 31 Mar).
    billing_day = models.PositiveSmallIntegerField("ödeme günü (ayın kaçı)", null=True, blank=True, editable=False)
    sms_credit = models.IntegerField("SMS kredisi", default=100)

    # Randevu kuralları
    slot_step = models.PositiveSmallIntegerField("saat aralığı (dk)", default=15)
    min_notice_minutes = models.PositiveIntegerField("en geç kaç dk önce alınabilir", default=60)
    max_days_ahead = models.PositiveSmallIntegerField("en fazla kaç gün sonrası", default=30)
    cancel_limit_minutes = models.PositiveIntegerField("iptal süresi (dk önce)", default=120)
    max_open_per_phone = models.PositiveSmallIntegerField("numara başına açık randevu", default=2)
    remind_manual = models.BooleanField(
        "elle girilen randevuya da hatırlatma gönder", default=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "işletme"
        verbose_name_plural = "işletmeler"

    def __str__(self):
        return self.name

    @property
    def accepts_bookings(self):
        """Ödeme gecikince hesap kapanmaz; yalnızca yeni online randevu durur."""
        return self.status in (self.Status.TRIAL, self.Status.ACTIVE)

    @property
    def staff_word(self):
        """Müşterinin gördüğü personel sözü: kuaförlerde "Kuaför", güzellik merkezinde "Uzman"."""
        return "Uzman" if self.kind == self.Kind.BEAUTY else "Kuaför"

    KIND_TONE = {Kind.MEN: Tone.TURQUOISE, Kind.WOMEN: Tone.PINK, Kind.BEAUTY: Tone.PINK, Kind.UNISEX: Tone.GREEN}

    @property
    def active_tone(self):
        """Seçilen renk; seçilmediyse işletme türünün rengi."""
        return self.tone or self.KIND_TONE.get(self.kind, self.Tone.GREEN)

    @property
    def lights(self):
        """Randevu ekranında dönen ışıklar: turkuaz ve pembe temada."""
        return self.active_tone in (self.Tone.TURQUOISE, self.Tone.PINK)

    @property
    def staff_plural(self):
        return "Uzmanlar" if self.kind == self.Kind.BEAUTY else "Kuaförler"

    @property
    def billing(self):
        """Üyelik özeti (ücret, ödeme günü, kalan gün); şablonlarda request.business.billing."""
        from . import billing
        return billing.summary(self)


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Sahip"
        STAFF = "staff", "Personel"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)

    class Meta:
        verbose_name = "panel üyeliği"
        verbose_name_plural = "panel üyelikleri"

    def __str__(self):
        return f"{self.user} @ {self.business}"


class Service(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="services")
    name = models.CharField("işlem", max_length=60)
    duration = models.PositiveSmallIntegerField("süre (dk)", default=30)
    buffer = models.PositiveSmallIntegerField("hazırlık payı (dk)", default=0)
    price = models.DecimalField("fiyat (₺)", max_digits=8, decimal_places=0)
    order = models.PositiveSmallIntegerField("sıra", default=0)
    active = models.BooleanField("aktif", default=True)
    price_updated_at = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "hizmet"
        verbose_name_plural = "hizmetler"

    def __str__(self):
        return self.name


class Staff(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="staff")
    name = models.CharField("ad", max_length=40)
    title = models.CharField("unvan", max_length=30, blank=True, help_text="Örn. usta, stilist, uzman, kalfa")
    services = models.ManyToManyField(Service, blank=True, verbose_name="yapabildiği işlemler")
    order = models.PositiveSmallIntegerField("sıra", default=0)
    active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "personel"
        verbose_name_plural = "personel"

    def __str__(self):
        return self.name


class Style(models.Model):
    """Örnek model ya da çalışma fotoğrafı: müşteri beğendiğini seçer, randevusunda görünür.
    Fotoğraf veritabanında, küçültülmüş ve konum bilgisi silinmiş olarak durur (core/images.py)."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="styles")
    title = models.CharField("ad", max_length=60)
    note = models.CharField("kısa açıklama", max_length=140, blank=True)
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL,
                                verbose_name="ilgili işlem",
                                help_text="Müşteri bu modeli seçince işlem kendiliğinden işaretlenir.")
    image = models.BinaryField(editable=False)
    thumb = models.BinaryField(editable=False)
    width = models.PositiveSmallIntegerField(default=0, editable=False)
    height = models.PositiveSmallIntegerField(default=0, editable=False)
    digest = models.CharField(max_length=12, editable=False)   # adres değişsin, tarayıcı eskiyi göstermesin
    order = models.PositiveSmallIntegerField("sıra", default=0)
    active = models.BooleanField("yayında", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    MAX_PER_BUSINESS = 60

    class Meta:
        ordering = ["order", "-id"]
        verbose_name = "model"
        verbose_name_plural = "modeller"

    def __str__(self):
        return self.title

    @property
    def image_url(self):
        from django.urls import reverse
        return reverse("style_image", args=[self.pk, self.digest])

    @property
    def thumb_url(self):
        from django.urls import reverse
        return reverse("style_thumb", args=[self.pk, self.digest, "k"])


class WorkingHours(models.Model):
    WEEKDAYS = [
        (0, "Pazartesi"), (1, "Salı"), (2, "Çarşamba"), (3, "Perşembe"),
        (4, "Cuma"), (5, "Cumartesi"), (6, "Pazar"),
    ]
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="hours")
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    closed = models.BooleanField(default=False)
    open = models.TimeField(default=time(9, 0))
    close = models.TimeField(default=time(20, 0))
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(fields=["business", "weekday"], name="one_row_per_weekday")
        ]
        verbose_name = "çalışma saati"
        verbose_name_plural = "çalışma saatleri"


class TimeOff(models.Model):
    """Kapalı gün, resmî tatil, izin ya da elle kapatılan saat. staff boşsa tüm dükkân."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="timeoffs")
    staff = models.ForeignKey(Staff, null=True, blank=True, on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["start"]
        verbose_name = "kapalı zaman"
        verbose_name_plural = "kapalı zamanlar"


class Customer(models.Model):
    """Müşteri kaydı işletmeye özeldir; kuaförler birbirinin müşterisini göremez."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="customers")
    phone = models.CharField(max_length=11)
    name = models.CharField(max_length=60, blank=True)
    note = models.TextField("berberin notu", blank=True, max_length=500)
    verified_at = models.DateTimeField(null=True, blank=True)
    no_show_count = models.PositiveSmallIntegerField(default=0)
    blocked = models.BooleanField("online randevu kapalı", default=False)
    marketing_consent = models.BooleanField(default=False)
    marketing_consent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "phone"], name="one_customer_per_phone")
        ]
        verbose_name = "müşteri"
        verbose_name_plural = "müşteriler"

    def __str__(self):
        return self.name or self.phone

    @property
    def masked_phone(self):
        return mask_phone(self.phone)


def mask_phone(p):
    """05xx xxx xx xx -> 05•• ••• •• xx (ekranda tam numara görünmez)."""
    return f"{p[:2]}•• ••• •• {p[-2:]}" if len(p) == 11 else p


def new_token():
    return secrets.token_urlsafe(16)


class Appointment(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Onaylı"
        COMPLETED = "completed", "Tamamlandı"
        NO_SHOW = "no_show", "Gelmedi"
        CANCELLED_CUSTOMER = "cancelled_customer", "Müşteri iptali"
        CANCELLED_BUSINESS = "cancelled_business", "İşletme iptali"

    class Source(models.TextChoices):
        ONLINE = "online", "Online"
        MANUAL = "manual", "Elle"
        WALKIN = "walkin", "Randevusuz"

    class Payment(models.TextChoices):
        CASH = "cash", "Nakit"
        CARD = "card", "Kart"

    # Takvimde yer tutan durumlar. İptaller saati boşaltır.
    ACTIVE = [Status.CONFIRMED, Status.COMPLETED, Status.NO_SHOW]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="appointments")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name="appointments")
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="appointments"
    )
    # Müşterinin seçtiği örnek model (isteğe bağlı); model silinse de randevu kalır.
    style = models.ForeignKey("Style", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="appointments", verbose_name="seçilen model")
    start = models.DateTimeField()
    end = models.DateTimeField()
    block_end = models.DateTimeField(help_text="Bitiş + hazırlık payı")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ONLINE)
    planned_total = models.DecimalField(max_digits=9, decimal_places=0, default=0)
    actual_total = models.DecimalField(max_digits=9, decimal_places=0, null=True, blank=True)
    payment = models.CharField(max_length=5, choices=Payment.choices, blank=True)
    token = models.CharField(max_length=32, unique=True, default=new_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["business", "start"])]
        constraints = [
            # Çakışma kontrolü veritabanında: aynı berbere aynı anda iki kayıt girilemez.
            ExclusionConstraint(
                name="no_overlap_per_staff",
                expressions=[
                    (TsTzRange("start", "block_end", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("staff", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=["confirmed", "completed", "no_show"]),
            ),
            models.CheckConstraint(condition=Q(end__gt=models.F("start")), name="end_after_start"),
        ]
        verbose_name = "randevu"
        verbose_name_plural = "randevular"

    def __str__(self):
        return f"{self.start:%d.%m %H:%M} {self.staff}"

    @property
    def summary(self):
        return " + ".join(i.name for i in self.items.all())

    @property
    def is_open(self):
        return self.status == self.Status.CONFIRMED

    def can_cancel_online(self, now=None):
        now = now or timezone.now()
        limit = self.start - timezone.timedelta(minutes=self.business.cancel_limit_minutes)
        return self.is_open and now <= limit


class AppointmentItem(models.Model):
    """Fiyat ve süre randevu anında kopyalanır; sonradan fiyat değişse geçmiş ciro bozulmaz."""
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=60)
    price = models.DecimalField(max_digits=8, decimal_places=0)
    duration = models.PositiveSmallIntegerField()


class MessageLog(models.Model):
    class Kind(models.TextChoices):
        OTP = "otp", "Doğrulama kodu"
        CONFIRM = "confirm", "Randevu onayı"
        REMINDER = "reminder", "Hatırlatma"
        CANCEL = "cancel", "İptal bildirimi"

    class Status(models.TextChoices):
        QUEUED = "queued", "Sırada"
        SENT = "sent", "Gönderildi"
        FAILED = "failed", "Başarısız"
        CANCELLED = "cancelled", "Vazgeçildi"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="messages")
    appointment = models.ForeignKey(
        Appointment, null=True, blank=True, on_delete=models.CASCADE, related_name="messages"
    )
    phone = models.CharField(max_length=11)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    body = models.CharField(max_length=320)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    scheduled_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    segments = models.PositiveSmallIntegerField(default=1)
    cost = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "scheduled_at"])]
        verbose_name = "mesaj kaydı"
        verbose_name_plural = "mesaj kayıtları"


class AuditLog(models.Model):
    """Kim, ne zaman, hangi randevuyu değiştirdi; uyuşmazlıkta tek kanıt."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="audit")
    appointment = models.ForeignKey(Appointment, null=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    detail = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "işlem kaydı"
        verbose_name_plural = "işlem kayıtları"


class PlatformSettings(models.Model):
    """Platformun tek satırlık ayarları: yönetim panelinden değiştirilir."""
    monthly_price = models.DecimalField("aylık üyelik ücreti (₺)", max_digits=8, decimal_places=0, default=499,
                                        validators=[MinValueValidator(0)])
    payment_note = models.TextField(
        "ödeme bilgisi", blank=True, max_length=600,
        help_text="Kuaförün üyelik sayfasında 'Nasıl ödenir' başlığı altında görünür: "
                  "IBAN, alıcı adı, açıklamaya ne yazılacağı gibi.")
    # Kurumsal bilgiler: sitenin alt bilgisinde, iletişim ve gizlilik sayfalarında görünür. Boşsa gösterilmez.
    company_name = models.CharField("şirket unvanı", max_length=120, blank=True,
                                    help_text="Örn. Ad Soyad Bilişim Hizmetleri ya da ... Ltd. Şti.")
    contact_email = models.EmailField("iletişim e-postası", blank=True)
    contact_phone = models.CharField("iletişim telefonu", max_length=20, blank=True)
    address = models.CharField("adres", max_length=200, blank=True)
    tax_info = models.CharField("vergi dairesi ve numarası", max_length=80, blank=True)

    class Meta:
        verbose_name = "platform ayarları"
        verbose_name_plural = "platform ayarları"

    def __str__(self):
        return "Platform ayarları"

    def save(self, *args, **kwargs):
        self.pk = 1   # tek satır
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class SubscriptionPayment(models.Model):
    """Kuaförün aylık üyelik ödemesi. Kayıt girilince üyelik bitişi dönem sonuna ilerler."""
    class Method(models.TextChoices):
        TRANSFER = "transfer", "Havale / EFT"
        CARD = "card", "Kart"
        CASH = "cash", "Nakit"
        OTHER = "other", "Diğer"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="payments",
                                 verbose_name="işletme")
    amount = models.DecimalField("tutar (₺)", max_digits=8, decimal_places=0, null=True, blank=True,
                                 validators=[MinValueValidator(0)],
                                 help_text="Boş bırakılırsa işletmenin aylık ücreti yazılır.")
    paid_on = models.DateField("ödeme tarihi", default=timezone.localdate)
    period_start = models.DateField("dönem başı", null=True, blank=True,
                                    help_text="Boş bırakılırsa üyeliğin bittiği günden (geçtiyse bugünden) başlar.")
    period_end = models.DateField("dönem sonu", null=True, blank=True,
                                  help_text="Boş bırakılırsa dönem başından bir ay sonrası yazılır.")
    method = models.CharField("yöntem", max_length=10, choices=Method.choices, default=Method.TRANSFER)
    note = models.CharField("not", max_length=120, blank=True)
    # Bu ödeme hesabı aktif yaptıysa önceki durum (deneme / ödeme bekliyor): kayıt silinirse geri dönülür.
    status_before = models.CharField(max_length=10, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]
        verbose_name = "üyelik ödemesi"
        verbose_name_plural = "üyelik ödemeleri"

    def __str__(self):
        return f"{self.business} · {self.paid_on:%d.%m.%Y} · {self.amount} ₺"

    def clean(self):
        from . import billing
        if self.paid_on and self.paid_on > timezone.localdate():
            raise ValidationError({"paid_on": "Ödeme tarihi bugünden ileri olamaz."})
        # Dönem başı boşsa kayıtta doldurulacak olan başlangıçla karşılaştırılır.
        start = self.period_start
        if start is None and self.paid_on and self.business_id:
            start = billing.period_start_for(self)
        if start and self.period_end and self.period_end <= start:
            raise ValidationError({"period_end": "Dönem sonu, dönem başından sonra olmalı."})

    def save(self, *args, **kwargs):
        """Boş alanlar her kayıtta tamamlanır; üyelik bitişi kalan ödemelerden yeniden hesaplanır
        (ödeme silinince de: core/billing.py içindeki post_delete alıcısı)."""
        from . import billing
        new = self._state.adding
        billing.fill_payment(self)
        super().save(*args, **kwargs)
        billing.apply_payment(self, new)


class Feedback(models.Model):
    """Programla ilgili öneri ve görüş: müşteri ya da işletme sahibi yazar, platform yönetimi okur."""
    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Müşteri"
        OWNER = "owner", "Kuaför / işletme sahibi"
        OTHER = "other", "Diğer"

    sender = models.CharField("yazan", max_length=10, choices=Sender.choices, default=Sender.OTHER)
    business = models.ForeignKey(Business, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="feedback", verbose_name="işletme")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             verbose_name="kullanıcı")
    name = models.CharField("ad", max_length=60, blank=True)
    contact = models.CharField("iletişim", max_length=120, blank=True)
    message = models.TextField("görüş", max_length=2000)
    page = models.CharField("geldiği sayfa", max_length=200, blank=True)
    is_read = models.BooleanField("okundu", default=False)
    created_at = models.DateTimeField("tarih", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "geri bildirim"
        verbose_name_plural = "geri bildirimler"

    def __str__(self):
        return f"{self.get_sender_display()} · {self.created_at:%d.%m.%Y}"

