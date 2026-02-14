import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from wallet.config import (
    build_databases,
    env_bool,
    env_float,
    env_int,
    env_list,
    load_environment,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_environment(BASE_DIR)


DEBUG = env_bool("DEBUG", default=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-secret-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG=False")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set when DEBUG=False")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "wallets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wallet.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wallet.wsgi.application"

DATABASE_URL, DATABASES = build_databases(BASE_DIR)

if not DEBUG and not DATABASE_URL and not os.getenv("DB_NAME"):
    raise ImproperlyConfigured("Set DATABASE_URL or DB_NAME when DEBUG=False")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "EXCEPTION_HANDLER": "wallets.api.exceptions.custom_exception_handler",
}

BANK_BASE_URL = os.getenv("BANK_BASE_URL", "http://127.0.0.1:8010")
BANK_TIMEOUT = env_float("BANK_TIMEOUT", default=3.0)
BANK_RETRY_COUNT = env_int("BANK_RETRY_COUNT", default=2)

if BANK_TIMEOUT <= 0:
    raise ImproperlyConfigured("BANK_TIMEOUT must be greater than zero")
if BANK_RETRY_COUNT < 0:
    raise ImproperlyConfigured("BANK_RETRY_COUNT must be >= 0")

WITHDRAWAL_PROCESSING_STALE_SECONDS = env_int(
    "WITHDRAWAL_PROCESSING_STALE_SECONDS", default=30
)
if WITHDRAWAL_PROCESSING_STALE_SECONDS < 1:
    raise ImproperlyConfigured("WITHDRAWAL_PROCESSING_STALE_SECONDS must be >= 1")

EXECUTOR_LOCK_CONTENTION_MAX_RETRIES = env_int(
    "EXECUTOR_LOCK_CONTENTION_MAX_RETRIES", default=20
)
if EXECUTOR_LOCK_CONTENTION_MAX_RETRIES < 0:
    raise ImproperlyConfigured("EXECUTOR_LOCK_CONTENTION_MAX_RETRIES must be >= 0")

EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS = env_float(
    "EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS", default=0.05
)
if EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS < 0:
    raise ImproperlyConfigured("EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS must be >= 0")

LOG_LEVEL = os.getenv("WALLET_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": (
                '{"ts":"%(asctime)s","level":"%(levelname)s",'
                '"logger":"%(name)s","message":"%(message)s"}'
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "loggers": {
        "wallets.tasks.execute_withdrawals": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "wallets.integrations.bank_client": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
