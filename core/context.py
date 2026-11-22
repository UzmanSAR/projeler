from django.conf import settings


def site(request):
    return {"SITE_NAME": settings.SITE_NAME, "TURNSTILE_SITE_KEY": settings.TURNSTILE_SITE_KEY,
            "MOTION": settings.MOTION}
