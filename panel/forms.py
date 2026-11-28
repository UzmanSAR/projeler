from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.text import slugify

from core.images import MAX_UPLOAD
from core.models import Business, Service, Staff, Style, WorkingHours, validate_slug_free

User = get_user_model()


class SignupForm(forms.Form):
    kind = forms.ChoiceField(label="İşletme türü", choices=Business.Kind.choices, initial=Business.Kind.WOMEN,
                             help_text="Hazır hizmet listesi buna göre gelir; sonra değiştirebilirsiniz.")
    business_name = forms.CharField(label="İşletme adı", max_length=80)
    slug = forms.CharField(
        label="Sayfa adresi", max_length=40,
        help_text="Müşterilerinizin göreceği bağlantı: site.com/adres. Örn. atelier-sac",
    )
    owner_name = forms.CharField(label="Adınız (takvimde görünür)", max_length=40)
    phone = forms.CharField(label="İşletme telefonu", max_length=20, required=False)
    closed_weekday = forms.TypedChoiceField(
        label="Haftalık kapalı gün", coerce=int, initial=6,
        choices=WorkingHours.WEEKDAYS + [(7, "Kapalı gün yok")],
    )
    open_at = forms.TimeField(label="Açılış", initial="09:00",
                              widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    close_at = forms.TimeField(label="Kapanış", initial="20:00",
                               widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    email = forms.EmailField(label="E-posta (giriş için)")
    password = forms.CharField(label="Şifre", widget=forms.PasswordInput, min_length=8)

    def clean_slug(self):
        # "Ali'nin Yeri" yazılsa da geçerli adrese çevrilir (ı harfi ayrıca ele alınır).
        slug = slugify(self.cleaned_data["slug"].replace("ı", "i").replace("İ", "i"))
        if not slug:
            raise forms.ValidationError("Geçerli bir adres yazın.")
        validate_slug_free(slug)
        if Business.objects.filter(slug=slug).exists():
            raise forms.ValidationError("Bu adres alınmış.")
        return slug

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError("Bu e-posta ile kayıtlı bir hesap var.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password

    def clean(self):
        data = super().clean()
        if data.get("open_at") and data.get("close_at") and data["close_at"] <= data["open_at"]:
            self.add_error("close_at", "Kapanış, açılıştan sonra olmalı.")
        return data


class BusinessForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ["name", "kind", "description", "address", "district", "phone", "whatsapp", "maps_url",
                  "slot_step", "min_notice_minutes", "max_days_ahead", "cancel_limit_minutes",
                  "max_open_per_phone", "remind_manual"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_slot_step(self):
        step = self.cleaned_data["slot_step"]
        if step not in (5, 10, 15, 20, 30, 60):
            raise forms.ValidationError("5, 10, 15, 20, 30 ya da 60 olmalı.")
        return step


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "duration", "buffer", "price", "order", "active"]

    def clean_duration(self):
        duration = self.cleaned_data["duration"]
        if not 5 <= duration <= 480:
            raise forms.ValidationError("Süre 5 ile 480 dakika arasında olmalı.")
        return duration


class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ["name", "title", "services", "order", "active"]
        widgets = {"services": forms.CheckboxSelectMultiple}

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["services"].queryset = Service.objects.filter(business=business)


class StyleForm(forms.ModelForm):
    photo = forms.ImageField(
        label="Fotoğraf", required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        help_text="Telefonundan çekebilir ya da galeriden seçebilirsin. Konum bilgisi silinerek kaydedilir.")

    class Meta:
        model = Style
        fields = ["title", "note", "service", "order", "active"]
        labels = {"title": "Model adı"}

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = business.services.all()
        self.fields["service"].empty_label = "Bağlı işlem yok"
        self.fields["title"].widget.attrs["placeholder"] = "Örn. Kısa bob, Fade, Gelin topuzu"
        if self.instance.pk is None:
            self.fields["photo"].required = True

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > MAX_UPLOAD:
            raise forms.ValidationError("Fotoğraf çok büyük (en fazla 15 MB).")
        return photo
