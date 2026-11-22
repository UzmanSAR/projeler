"""SMS doğrulama kodu ve gönderim sınırları (rapor, Bölüm 7: katman 2-4)."""
import hashlib
import hmac
import json
import re
import secrets
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

from .models import MessageLog
from .sms import send_sms


class OtpError(Exception):
    """Kullanıcıya gösterilecek mesajı taşır."""


def normalize_phone(raw):
    """Yalnızca Türkiye cep numarası: 05XXXXXXXXX. Geçersizse None."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("90") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("5"):
        digits = "0" + digits
    return digits if re.fullmatch(r"05\d{9}", digits) else None


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd and not settings.DEBUG:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _hash(code, phone):
    return hmac.new(settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _bump(key, ttl, limit):
    """Sayaç sınırı aşıldıysa False döner."""
    cache.add(key, 0, ttl)
    try:
        return cache.incr(key) <= limit
    except ValueError:  # anahtar tam o anda düştüyse
        cache.set(key, 1, ttl)
        return True


def verify_turnstile(token, ip):
    """Anahtar tanımlı değilse kontrol atlanır (geliştirme)."""
    if not settings.TURNSTILE_SECRET:
        return True
    if not token:
        return False
    data = urllib.parse.urlencode(
        {"secret": settings.TURNSTILE_SECRET, "response": token, "remoteip": ip}
    ).encode()
    try:
        with urllib.request.urlopen(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=5
        ) as resp:
            return bool(json.load(resp).get("success"))
    except Exception:
        return False


def request_code(business, phone, ip):
    """Kod üretir ve SMS ile gönderir. Geliştirmede kodu döndürür."""
    if cache.get(f"otp:cool:{business.id}:{phone}"):
        raise OtpError("Kod az önce gönderildi. Lütfen yarım dakika bekleyin.")
    if not _bump(f"otp:ph:h:{phone}", 3600, settings.OTP_PER_PHONE_HOUR) or \
       not _bump(f"otp:ph:d:{phone}", 86400, settings.OTP_PER_PHONE_DAY):
        raise OtpError("Bu numaraya çok fazla kod istendi. Daha sonra tekrar deneyin ya da dükkânı arayın.")
    if not _bump(f"otp:ip:{ip}", 3600, settings.OTP_PER_IP_HOUR):
        raise OtpError("Çok fazla deneme yapıldı. Daha sonra tekrar deneyin.")
    if not _bump(f"otp:biz:{business.id}", 86400, settings.OTP_PER_BUSINESS_DAY):
        raise OtpError("Online randevu geçici olarak durduruldu. Lütfen dükkânı arayın.")

    code = f"{secrets.randbelow(10**6):06d}"
    cache.set(f"otp:code:{business.id}:{phone}", {"h": _hash(code, phone), "tries": 0},
              settings.OTP_TTL_SECONDS)
    cache.set(f"otp:cool:{business.id}:{phone}", 1, settings.OTP_RESEND_SECONDS)
    send_sms(
        business, phone,
        f"{business.name} randevu onay kodunuz: {code}. Bu kod yalnizca randevunuzu onaylar.",
        MessageLog.Kind.OTP,
    )
    return code if settings.SMS_SHOW_CODE else None


def check_code(business, phone, code):
    key = f"otp:code:{business.id}:{phone}"
    entry = cache.get(key)
    if not entry:
        raise OtpError("Kodun süresi doldu. Yeni kod isteyin.")
    if entry["tries"] >= settings.OTP_MAX_ATTEMPTS:
        cache.delete(key)
        raise OtpError("Çok fazla yanlış deneme. Yeni kod isteyin.")
    if not hmac.compare_digest(entry["h"], _hash(re.sub(r"\D", "", code or ""), phone)):
        entry["tries"] += 1
        cache.set(key, entry, settings.OTP_TTL_SECONDS)
        raise OtpError("Kod hatalı. Tekrar deneyin.")
    cache.delete(key)  # tek kullanımlık
    return True
