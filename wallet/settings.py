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
BANK_HONORS_IDEMPOTENCY = env_bool("BANK_HONORS_IDEMPOTENCY", default=True)
BANK_RETRY_MAX_ATTEMPTS = env_int("BANK_RETRY_MAX_ATTEMPTS", default=3)
BANK_RETRY_BASE_DELAY = env_float("BANK_RETRY_BASE_DELAY", default=0.2)
BANK_RETRY_MAX_DELAY = env_float("BANK_RETRY_MAX_DELAY", default=3.0)
BANK_MAX_RPS = env_float("BANK_MAX_RPS", default=0.0)
BANK_RATE_LIMIT_REDIS_URL = os.getenv(
    "BANK_RATE_LIMIT_REDIS_URL",
    "redis://127.0.0.1:6379/0",
)
BANK_RATE_LIMIT_KEY = os.getenv("BANK_RATE_LIMIT_KEY", "wallet:bank:rate_limit")
BANK_REDIS_SOCKET_CONNECT_TIMEOUT = env_float(
    "BANK_REDIS_SOCKET_CONNECT_TIMEOUT", default=0.5
)
BANK_REDIS_SOCKET_TIMEOUT = env_float("BANK_REDIS_SOCKET_TIMEOUT", default=0.5)
BANK_HTTP_MAX_CONNECTIONS = env_int("BANK_HTTP_MAX_CONNECTIONS", default=10)
BANK_HTTP_MAX_KEEPALIVE = env_int("BANK_HTTP_MAX_KEEPALIVE", default=10)
BANK_STATUS_URL_TEMPLATE = os.getenv("BANK_STATUS_URL_TEMPLATE", "").strip()

if BANK_TIMEOUT <= 0:
    raise ImproperlyConfigured("BANK_TIMEOUT must be greater than zero")
if BANK_RETRY_MAX_ATTEMPTS < 1:
    raise ImproperlyConfigured("BANK_RETRY_MAX_ATTEMPTS must be >= 1")
if BANK_RETRY_BASE_DELAY < 0:
    raise ImproperlyConfigured("BANK_RETRY_BASE_DELAY must be >= 0")
if BANK_RETRY_MAX_DELAY < 0:
    raise ImproperlyConfigured("BANK_RETRY_MAX_DELAY must be >= 0")
if BANK_RETRY_MAX_DELAY < BANK_RETRY_BASE_DELAY:
    raise ImproperlyConfigured("BANK_RETRY_MAX_DELAY must be >= BANK_RETRY_BASE_DELAY")
if BANK_MAX_RPS < 0:
    raise ImproperlyConfigured("BANK_MAX_RPS must be >= 0")
if BANK_REDIS_SOCKET_CONNECT_TIMEOUT <= 0:
    raise ImproperlyConfigured("BANK_REDIS_SOCKET_CONNECT_TIMEOUT must be > 0")
if BANK_REDIS_SOCKET_TIMEOUT <= 0:
    raise ImproperlyConfigured("BANK_REDIS_SOCKET_TIMEOUT must be > 0")
if BANK_HTTP_MAX_CONNECTIONS < 1:
    raise ImproperlyConfigured("BANK_HTTP_MAX_CONNECTIONS must be >= 1")
if BANK_HTTP_MAX_KEEPALIVE < 1:
    raise ImproperlyConfigured("BANK_HTTP_MAX_KEEPALIVE must be >= 1")

WITHDRAWAL_PROCESSING_STALE_SECONDS = env_int(
    "WITHDRAWAL_PROCESSING_STALE_SECONDS", default=30
)
if WITHDRAWAL_PROCESSING_STALE_SECONDS < 1:
    raise ImproperlyConfigured("WITHDRAWAL_PROCESSING_STALE_SECONDS must be >= 1")
WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS = env_int(
    "WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS",
    default=WITHDRAWAL_PROCESSING_STALE_SECONDS,
)
if WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS < 1:
    raise ImproperlyConfigured("WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS must be >= 1")

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
WORKER_LOOP_INTERVAL = env_float("WORKER_LOOP_INTERVAL", default=2.0)
if WORKER_LOOP_INTERVAL < 0:
    raise ImproperlyConfigured("WORKER_LOOP_INTERVAL must be >= 0")
WORKER_STARTUP_JITTER_MAX = env_float("WORKER_STARTUP_JITTER_MAX", default=0.0)
if WORKER_STARTUP_JITTER_MAX < 0:
    raise ImproperlyConfigured("WORKER_STARTUP_JITTER_MAX must be >= 0")
WORKER_LOOP_JITTER_MAX = env_float("WORKER_LOOP_JITTER_MAX", default=0.5)
if WORKER_LOOP_JITTER_MAX < 0:
    raise ImproperlyConfigured("WORKER_LOOP_JITTER_MAX must be >= 0")

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
