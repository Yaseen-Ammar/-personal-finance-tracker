from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.common import ServiceError
from app.services.validation import clean_text, validate_amount, validate_date


@pytest.mark.parametrize(
    "raw, expected",
    [("12.5", "12.50"), ("0.01", "0.01"), ("1000", "1000.00"), (Decimal("3"), "3.00"),
     ("999999999999.99", "999999999999.99")],
)
def test_valid_amounts_are_normalised_to_two_places(raw, expected):
    assert validate_amount(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw",
    ["0", "0.00", "-1", "abc", "", "NaN", "Infinity", "-Infinity", "1.005", "1e20",
     "1000000000000.00", 1.5, None],
)
def test_invalid_amounts_rejected(raw):
    with pytest.raises(ServiceError):
        validate_amount(raw)


def test_negative_and_zero_allowed_for_balances():
    assert validate_amount("-5.00", allow_negative=True) == Decimal("-5.00")
    assert validate_amount("0", allow_negative=True) == Decimal("0.00")
    with pytest.raises(ServiceError):
        validate_amount("NaN", allow_negative=True)


def test_float_artifacts_cannot_sneak_in():
    # Decimal(0.1) would be 0.1000000000000000055...; floats are refused outright.
    with pytest.raises(ServiceError):
        validate_amount(0.1)


def test_dates():
    assert validate_date(date.today()) == date.today()
    with pytest.raises(ServiceError):
        validate_date(date(1999, 12, 31))
    with pytest.raises(ServiceError):
        validate_date(date.today() + timedelta(days=400))
    with pytest.raises(ServiceError):
        validate_date(None)
    with pytest.raises(ServiceError):
        validate_date("2026-01-01")


def test_clean_text_rules():
    assert clean_text("  hi  ", field="F", max_len=5) == "hi"
    assert clean_text(None, field="F", max_len=5) == ""
    with pytest.raises(ServiceError):
        clean_text("", field="F", max_len=5, required=True)
    with pytest.raises(ServiceError):
        clean_text("toolong", field="F", max_len=5)
    with pytest.raises(ServiceError):
        clean_text("a\nb", field="F", max_len=10)
