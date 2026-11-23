from django import forms

from core.models import Feedback


class FeedbackForm(forms.Form):
    sender = forms.ChoiceField(label="Kimsin?", choices=Feedback.Sender.choices)
    message = forms.CharField(
        label="Önerin ya da görüşün", min_length=5, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 6, "maxlength": 2000, "required": True}),
        error_messages={"required": "Görüşünü yazmadan gönderemeyiz.",
                        "min_length": "Biraz daha ayrıntı yazar mısın?"})
    name = forms.CharField(label="Adın", max_length=60, required=False)
    contact = forms.CharField(label="Telefon ya da e-posta", max_length=120, required=False)
    # Tuzak alan: insan görmez ve doldurmaz, otomatik gönderimler doldurur.
    website = forms.CharField(required=False)
