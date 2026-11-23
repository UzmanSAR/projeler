import hashlib
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def static_version():
    """static/ altındaki css ve js içeriğinin kısa özeti: adreslerin sonundaki ?v= değeri."""
    digest = hashlib.sha1()
    for path in sorted((settings.BASE_DIR / "static").rglob("*")):
        if path.suffix in {".css", ".js"}:
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def site(request):
    if settings.DEBUG:  # geliştirmede dosyalar süreç yaşarken değişir
        static_version.cache_clear()
    return {"SITE_NAME": settings.SITE_NAME, "TURNSTILE_SITE_KEY": settings.TURNSTILE_SITE_KEY,
            "MOTION": settings.MOTION, "STATIC_V": static_version()}
