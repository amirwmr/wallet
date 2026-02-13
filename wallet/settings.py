import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


def _env_float(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number") from exc


def _env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sqlite_name(raw_name):
    if raw_name == ":memory:":
        return raw_name
    path = Path(raw_name)
    if path.is_absolute():
        return str(path)
    return str(BASE_DIR / path)


def _database_from_url(database_url):
    parsed = urlparse(database_url)
    scheme = parsed.scheme.split("+", 1)[0]

    if scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }

    if scheme == "sqlite":
        if parsed.path in {"", "/"}:
            name = str(BASE_DIR / "db.sqlite3")
        else:
            name = unquote(parsed.path)
            if parsed.netloc:
                name = f"/{parsed.netloc}{name}"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _sqlite_name(name),
        }

    raise ImproperlyConfigured(
        "DATABASE_URL must use sqlite://, postgres://, or postgresql://"
    )


DEBUG = _env_bool("DEBUG", default=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-secret-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG=False")

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
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

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {"default": _database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
            "NAME": _sqlite_name(os.getenv("DB_NAME", "db.sqlite3")),
            "USER": os.getenv("DB_USER", ""),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", ""),
            "PORT": os.getenv("DB_PORT", ""),
        }
    }

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
BANK_TIMEOUT = _env_float("BANK_TIMEOUT", default=3.0)
BANK_RETRY_COUNT = _env_int("BANK_RETRY_COUNT", default=2)

if BANK_TIMEOUT <= 0:
    raise ImproperlyConfigured("BANK_TIMEOUT must be greater than zero")
if BANK_RETRY_COUNT < 0:
    raise ImproperlyConfigured("BANK_RETRY_COUNT must be >= 0")

# Backward-compatible aliases for older integration settings names.
BANK_CONNECT_TIMEOUT_SECONDS = BANK_TIMEOUT
BANK_READ_TIMEOUT_SECONDS = BANK_TIMEOUT
BANK_MAX_NETWORK_RETRIES = BANK_RETRY_COUNT

WITHDRAWAL_PROCESSING_STALE_SECONDS = _env_int(
    "WITHDRAWAL_PROCESSING_STALE_SECONDS", default=30
)
if WITHDRAWAL_PROCESSING_STALE_SECONDS < 1:
    raise ImproperlyConfigured("WITHDRAWAL_PROCESSING_STALE_SECONDS must be >= 1")

EXECUTOR_LOCK_CONTENTION_MAX_RETRIES = _env_int(
    "EXECUTOR_LOCK_CONTENTION_MAX_RETRIES", default=20
)
if EXECUTOR_LOCK_CONTENTION_MAX_RETRIES < 0:
    raise ImproperlyConfigured("EXECUTOR_LOCK_CONTENTION_MAX_RETRIES must be >= 0")

EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS = _env_float(
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
