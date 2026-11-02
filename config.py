"""Application configuration.

All secrets come from environment variables (loaded from a local .env file).
Nothing sensitive is hardcoded here.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def build_database_url() -> URL:
    """Build the MySQL URL as a structured object.

    Using sqlalchemy.engine.URL (instead of an f-string) automatically
    escapes special characters in the password (@, :, /, #...), and its
    repr masks the password so it does not leak into logs.
    """
    return URL.create(
        drivername="mysql+pymysql",
        username=_require("MYSQL_USER"),
        password=_require("MYSQL_PASSWORD"),
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        database=_require("MYSQL_DATABASE"),
        query={"charset": "utf8mb4"},
    )


class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # drop dead connections transparently
        "pool_recycle": 280,     # recycle before MySQL's wait_timeout
    }
    # Cookie hardening (safe on plain http://localhost)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True
    # Werkzeug hash method. scrypt (salted, memory-hard) in real use.
    PASSWORD_HASH_METHOD = "scrypt"
    # Display currency (presentation only; validated in create_app).
    CURRENCY_CODE = os.environ.get("CURRENCY_CODE", "USD")
    CURRENCY_LOCALE = os.environ.get("CURRENCY_LOCALE", "en_US")

    @staticmethod
    def secret_key() -> str:
        return _require("SECRET_KEY")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True    # requires HTTPS
    REMEMBER_COOKIE_SECURE = True


class TestingConfig(BaseConfig):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret-key-not-for-production"
    # Deliberately cheap so the suite runs in seconds. Tests only; never in prod.
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"
    # Fixed so a developer's .env can't change what the tests expect.
    CURRENCY_CODE = "USD"
    CURRENCY_LOCALE = "en_US"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
