"""Proje ayarları. Gizli değerler ortam değişkenlerinden okunur (.env.example dosyasına bak)."""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


DEBUG = env("DEBUG", "1") == "1"
SECRET_KEY = env("SECRET_KEY", "dev-only-insecure-key-change-me")
if not DEBUG and SECRET_KEY.startswith("dev-only"):
    raise RuntimeError("Yayın ortamında SECRET_KEY ortam değişkeni zorunludur.")

ALLOWED_HOSTS = [h for h in env("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
# Render kendi alan adını bu değişkenlerle bildirir.
if env("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))
    CSRF_TRUSTED_ORIGINS.append("https://" + env("RENDER_EXTERNAL_HOSTNAME"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "core",
    "public",
    "panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "berber"),
        "USER": env("DB_USER", "berber"),
        "PASSWORD": env("DB_PASSWORD", "berber"),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "5432"),
    }
}

# Barındırma hizmetleri bağlantıyı tek satırda verir: postgres://kullanici:sifre@sunucu:port/ad
if env("DATABASE_URL"):
    _db = urlparse(env("DATABASE_URL"))
    DATABASES["default"].update(
        NAME=_db.path.lstrip("/"), USER=unquote(_db.username or ""),
        PASSWORD=unquote(_db.password or ""), HOST=_db.hostname or "", PORT=str(_db.port or 5432),
    )

# Doğrulama kodları ve gönderim sınırları önbellekte tutulur. Birden fazla
# sunucu süreci varsa REDIS_URL zorunludur; yoksa sınırlar süreç başına sayılır.
if env("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL"),
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "panel:login"
LOGIN_REDIRECT_URL = "panel:today"
LOGOUT_REDIRECT_URL = "panel:login"

SESSION_COOKIE_HTTPONLY = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30

# ---- Ürün ayarları -------------------------------------------------------
SITE_NAME = env("SITE_NAME", "Berber Randevu")
SITE_URL = env("SITE_URL") or env("RENDER_EXTERNAL_URL") or "http://localhost:8000"

# SMS: geliştirmede mesajlar konsola yazılır. Yayında gerçek sağlayıcı sınıfı verilir.
SMS_BACKEND = env("SMS_BACKEND", "core.sms.ConsoleBackend")
SMS_UNIT_COST = env("SMS_UNIT_COST", "0.17")
SMS_OTP_UNIT_COST = env("SMS_OTP_UNIT_COST", "0.24")
# Gerçek SMS gitmediğinde doğrulama kodunu ekranda göster. Geliştirmede kendiliğinden
# açıktır; tanıtım sitesinde SMS_SHOW_CODE=1 ile açılır. Gerçek sağlayıcı bağlanınca
# kapatılmalıdır, yoksa telefon doğrulaması anlamsız kalır.
SMS_SHOW_CODE = SMS_BACKEND.endswith("ConsoleBackend") and (DEBUG or env("SMS_SHOW_CODE") == "1")

# Doğrulama kodu sınırları (rapor, Bölüm 7)
OTP_TTL_SECONDS = 180
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 30
OTP_PER_PHONE_HOUR = 3
OTP_PER_PHONE_DAY = 6
OTP_PER_IP_HOUR = 10
OTP_PER_BUSINESS_DAY = 300
DEVICE_REMEMBER_DAYS = 90

# Cloudflare Turnstile (isteğe bağlı). İkisi de doluysa kod gönderiminden önce doğrulanır.
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET = env("TURNSTILE_SECRET", "")

TRIAL_DAYS = 14

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"sms": {"handlers": ["console"], "level": "INFO"}},
}
