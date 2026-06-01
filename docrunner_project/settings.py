"""
docrunner_project/settings.py

Single-owner DocRunner. Configuration mirrors PyRunner: env-driven, SQLite,
single data volume, django-q2 worker, Fernet-encrypted secrets. The one new
dependency is LibreOffice (bundled in the image; see Dockerfile), used by the
generation worker for PDF conversion.

Required env vars (container refuses to start without them):
    SECRET_KEY        Django secret key
    ENCRYPTION_KEY    Fernet key for the Secret model (urlsafe base64, 32 bytes)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# All persistent state lives under one volume, like PyRunner's /app/data.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# Required secrets (fail fast if missing)
# ──────────────────────────────────────────────
# SECRET_KEY — required in production, falls back to an insecure default so
# management commands (migrate, collectstatic) work during container startup
# before Coolify injects env vars. Gunicorn will serve with the real key.
SECRET_KEY = os.environ.get("SECRET_KEY", "insecure-fallback-change-me-in-production")

# ENCRYPTION_KEY — evaluated lazily by the Secret model; a missing key will
# raise a clear error only when a Secret is actually read/written.
_enc_key_str = os.environ.get("ENCRYPTION_KEY", "")
ENCRYPTION_KEY = _enc_key_str.encode() if _enc_key_str else b""


# ──────────────────────────────────────────────
# Core Django
# ──────────────────────────────────────────────
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_q",
    "docrunner",
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

ROOT_URLCONF = "docrunner_project.urls"
WSGI_APPLICATION = "docrunner_project.wsgi.application"

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
            ],
        },
    },
]


# ──────────────────────────────────────────────
# Database — SQLite on the data volume (matches PyRunner)
# ──────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "docrunner.sqlite3",
        # Allow the web process and the q-cluster worker to share the file.
        "OPTIONS": {"timeout": 20},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ──────────────────────────────────────────────
# Files — templates in, generated docs out, both on the volume
# ──────────────────────────────────────────────
MEDIA_ROOT = DATA_DIR / "media"
MEDIA_URL = "/media/"
# Cap uploaded template size (templates are small; this also guards memory).
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB

STATIC_URL = "/static/"
STATIC_ROOT = DATA_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# ──────────────────────────────────────────────
# django-q2 — the worker that runs every generation + delivery
# ──────────────────────────────────────────────
Q_CLUSTER = {
    "name": "docrunner",
    "workers": int(os.environ.get("Q_WORKERS", "2")),
    "timeout": 600,          # a long batch + PDF cold-start can take a while
    "retry": 1200,           # > timeout so q2 never double-runs a slow task
    "max_attempts": 1,       # we manage our own retries (see deliveries.py)
    "catch_up": False,       # missed schedules don't stampede on restart
    "orm": "default",        # use the SQLite DB as the broker — no Redis needed
    "label": "DocRunner Tasks",
}


# ──────────────────────────────────────────────
# Email (SMTP) — used by deliveries.py
# ──────────────────────────────────────────────
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "True").lower() == "true"
# The SMTP password is NOT read from env — it's a row in the Secret table,
# looked up by this name, so it's encrypted at rest like every other credential.
SMTP_PASSWORD_SECRET = os.environ.get("SMTP_PASSWORD_SECRET", "SMTP_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "docrunner@localhost")

# Django's own mail (magic-link login) uses the same SMTP host.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = SMTP_HOST
EMAIL_PORT = SMTP_PORT
EMAIL_HOST_USER = SMTP_USER
EMAIL_USE_TLS = SMTP_USE_TLS


# ──────────────────────────────────────────────
# LibreOffice (PDF conversion in the worker)
# ──────────────────────────────────────────────
# Path to the soffice binary; overridable for non-standard installs.
SOFFICE_BIN = os.environ.get("SOFFICE_BIN", "soffice")


# ──────────────────────────────────────────────
# Security (tightened when DEBUG is off)
# ──────────────────────────────────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Inbound webhook endpoint is exempt from CSRF (it's token+HMAC authenticated,
# not session-based) — handled per-view, not globally.

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
