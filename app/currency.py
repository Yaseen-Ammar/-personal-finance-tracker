"""Currency formatting driven by configuration (never hard-coded).

Settings (env / config):
  CURRENCY_CODE    ISO 4217 code, e.g. USD, GBP, EUR, JPY   (default USD)
  CURRENCY_LOCALE  number-format locale, e.g. en_US, en_GB, de_DE (default en_US)

Amounts are stored as exact DECIMAL(14, 2) regardless of currency; the
setting changes presentation only, so it can be changed at any time without a
migration. Two decimals are always shown (the stored precision).
"""
from decimal import Decimal

from babel import Locale, UnknownLocaleError
from babel.numbers import format_currency, get_currency_symbol, list_currencies
from flask import current_app

from config import ConfigError


def validate_currency_settings(code: str, locale: str) -> tuple[str, str]:
    """Return (normalised code, locale) or raise ConfigError with a clear message."""
    normalised = (code or "").strip().upper()
    if normalised not in list_currencies():
        raise ConfigError(
            f"CURRENCY_CODE '{code}' is not a valid ISO 4217 currency code (e.g. USD, GBP, EUR)."
        )
    try:
        Locale.parse((locale or "").strip())
    except (UnknownLocaleError, ValueError):
        raise ConfigError(
            f"CURRENCY_LOCALE '{locale}' is not a valid locale (e.g. en_US, en_GB, de_DE)."
        ) from None
    return normalised, locale.strip()


def _settings() -> tuple[str, str]:
    return current_app.config["CURRENCY_CODE"], current_app.config["CURRENCY_LOCALE"]


def format_money(value) -> str:
    """Format a Decimal amount, e.g. Decimal('-1234.5') -> '-$1,234.50'."""
    code, locale = _settings()
    return format_currency(
        Decimal(value), code, locale=locale, currency_digits=False, format_type="standard"
    )


def currency_symbol() -> str:
    code, locale = _settings()
    return get_currency_symbol(code, locale=locale)


def currency_code() -> str:
    return current_app.config["CURRENCY_CODE"]
