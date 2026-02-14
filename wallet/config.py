import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


def load_environment(base_dir):
    load_dotenv(base_dir / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


def env_float(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number") from exc


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sqlite_name(base_dir, raw_name):
    if raw_name == ":memory:":
        return raw_name
    path = Path(raw_name)
    if path.is_absolute():
        return str(path)
    return str(base_dir / path)


def _database_from_url(base_dir, database_url):
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
            name = str(base_dir / "db.sqlite3")
        else:
            name = unquote(parsed.path)
            if parsed.netloc:
                name = f"/{parsed.netloc}{name}"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _sqlite_name(base_dir, name),
        }

    raise ImproperlyConfigured(
        "DATABASE_URL must use sqlite://, postgres://, or postgresql://"
    )


def build_databases(base_dir):
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url, {"default": _database_from_url(base_dir, database_url)}

    db_engine = os.getenv("DB_ENGINE", "django.db.backends.sqlite3")
    raw_db_name = os.getenv("DB_NAME", "db.sqlite3")
    db_name = (
        _sqlite_name(base_dir, raw_db_name)
        if db_engine == "django.db.backends.sqlite3"
        else raw_db_name
    )

    return database_url, {
        "default": {
            "ENGINE": db_engine,
            "NAME": db_name,
            "USER": os.getenv("DB_USER", ""),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", ""),
            "PORT": os.getenv("DB_PORT", ""),
        }
    }
