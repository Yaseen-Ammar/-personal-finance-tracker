"""Input validation for money, dates and text. The service layer is the
authority; form validators simply call these so the rules live in one place."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .common import ServiceError

MAX_AMOUNT = Decimal("999999999999.99")  # fits DECIMAL(14, 2)
CENT = Decimal("0.01")
MIN_DATE = date(2000, 1, 1)
MAX_FUTURE_DAYS = 366


def validate_amount(value, *, field: str = "Amount", allow_negative: bool = False) -> Decimal:
    """Return `value` as an exact 2-dp Decimal or raise ServiceError.

    allow_negative=True is for balances (opening balance of a credit card can
    be negative or zero). Otherwise the amount must be strictly positive.
    """
    if isinstance(value, float):  # floats are never accepted for money
        raise ServiceError(f"{field} must be a valid number.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise ServiceError(f"{field} must be a valid number.") from None

    # NaN/Infinity parse as Decimals but break comparisons: reject them first.
    if not amount.is_finite():
        raise ServiceError(f"{field} must be a valid number.")
    if amount.as_tuple().exponent < -2:
        raise ServiceError(f"{field} can have at most 2 decimal places.")
    if not allow_negative and amount <= 0:
        raise ServiceError(f"{field} must be greater than zero.")
    if abs(amount) > MAX_AMOUNT:
        raise ServiceError(f"{field} is too large.")
    return amount.quantize(CENT)


def validate_date(value, *, field: str = "Date") -> date:
    if not isinstance(value, date):
        raise ServiceError(f"{field} is required.")
    latest = date.today() + timedelta(days=MAX_FUTURE_DAYS)
    if value < MIN_DATE or value > latest:
        raise ServiceError(
            f"{field} must be between {MIN_DATE.isoformat()} and {latest.isoformat()}."
        )
    return value


def clean_text(value, *, field: str, max_len: int, required: bool = False) -> str:
    text = (value or "").strip()
    if required and not text:
        raise ServiceError(f"{field} is required.")
    if len(text) > max_len:
        raise ServiceError(f"{field} must be at most {max_len} characters.")
    if any(ord(ch) < 32 for ch in text):
        raise ServiceError(f"{field} contains invalid characters.")
    return text
