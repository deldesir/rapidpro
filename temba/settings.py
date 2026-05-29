import os
import logging

logger = logging.getLogger(__name__)

# Ensure exceptions are logged
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": True,
        },
    },
}

# ----------------------------------------------------------------------------------
# RapidPro settings file for IIAB
# ----------------------------------------------------------------------------------

from .settings_common import *  # noqa

# Disable debug mode for production
DEBUG = False

# SECURITY: Use a unique secret key per deployment
SECRET_KEY = "Jdo59sl2eMntjbdRtpzXejoe84nfOhdw"



# The hostname of the IIAB box
# Hardcoded for Android/Proot stability
ALLOWED_HOSTS = ["*"]
INTERNAL_IPS = ["127.0.0.1"]

HOSTNAME = "box"
BRAND["domain"] = "box"
BRAND["hosts"] = ["box", "localhost", "127.0.0.1", "box.lan"]

# ----------------------------------------------------------------------------------
# Databases
# ----------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": "temba",
        "USER": "temba",
        "PASSWORD": "temba",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}
DATABASES["readonly"] = DATABASES["default"]

# ----------------------------------------------------------------------------------
# Caching
# ----------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_valkey.cache.ValkeyCache",
        "LOCATION": "redis://127.0.0.1:6379/0",
        "OPTIONS": {"CLIENT_CLASS": "django_valkey.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = "redis://127.0.0.1:6379/15"

# ----------------------------------------------------------------------------------
# DynamoDB — disabled (local-first: all data stays in PostgreSQL)
# ----------------------------------------------------------------------------------
DYNAMO_TABLE_PREFIX = ""
DYNAMO_ENDPOINT_URL = None

# ----------------------------------------------------------------------------------
# Storage — Local Filesystem (no AWS dependencies)
# ----------------------------------------------------------------------------------
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "archives": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "public": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

STORAGE_URL = "/rp/media"

# ----------------------------------------------------------------------------------
# Mailroom - localhost for dev, no auth token
# ----------------------------------------------------------------------------------
MAILROOM_URL = os.environ.get("MAILROOM_URL", "http://127.0.0.1:8091")
MAILROOM_AUTH_TOKEN = os.environ.get("MAILROOM_AUTH_TOKEN")

# ----------------------------------------------------------------------------------
# Use Celery for background tasks
# ----------------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = False

# ----------------------------------------------------------------------------------
# Asset compression — reduces page load time
# ----------------------------------------------------------------------------------
COMPRESS_ENABLED = True
COMPRESS_OFFLINE = False

# ----------------------------------------------------------------------------------
# Default user timezone
# ----------------------------------------------------------------------------------
USER_TIME_ZONE = "America/Port-au-Prince"

FORCE_SCRIPT_NAME = "/rp/"
STATIC_URL = "/rp/static/"
MEDIA_URL = "/rp/media/"
LOGIN_URL = "/rp/accounts/login/"
LOGIN_REDIRECT_URL = "/rp/org/choose/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/rp/"

# ----------------------------------------------------------------------------------
# Email
# ----------------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ----------------------------------------------------------------------------------
# Security
# ----------------------------------------------------------------------------------
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"

# ----------------------------------------------------------------------------------
# Allauth / Rate-limiting
# Tell allauth that exactly 1 trusted reverse proxy (nginx) sits in front,
# so it reads the real client IP from X-Forwarded-For instead of REMOTE_ADDR.
# Without this, logins return 403 "Unable to determine client IP address"
# because REMOTE_ADDR is empty/invalid on unix sockets.
# ----------------------------------------------------------------------------------
ALLAUTH_TRUSTED_PROXY_COUNT = 1

# Use HTTPS cookies and proxy headers
SECURE_PROXY_SSL_HEADER = None
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Cookie security
SESSION_COOKIE_AGE = 1209600  # 2 weeks
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_AGE = 1209600  # 2 weeks

# Password requirements
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
