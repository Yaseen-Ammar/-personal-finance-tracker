from datetime import date

import pytest

from app.services.periods import (
    Month,
    months_between,
    parse_month,
    parse_year,
    trailing_months,
)

TODAY = date(2026, 11, 2)


def test_month_properties():
    m = Month(date(2026, 2, 1))
    assert (m.year, m.number, m.last) == (2026, 2, date(2026, 2, 28))
    assert (m.label, m.short_label) == ("February 2026", "Feb 2026")


def test_leap_year_february():
    assert Month(date(2028, 2, 1)).last == date(2028, 2, 29)


@pytest.mark.parametrize("delta, expected", [(1, date(2026, 12, 1)), (2, date(2027, 1, 1)), (-11, date(2025, 12, 1)),
                                             (-12, date(2025, 11, 1)), (0, date(2026, 11, 1)), (25, date(2028, 12, 1))])
def test_shift_crosses_year_boundaries(delta, expected):
    assert Month(date(2026, 11, 1)).shift(delta).first == expected


def test_month_of_any_day_normalises_to_first():
    assert Month.of(date(2026, 3, 31)).first == date(2026, 3, 1)


def test_trailing_months_oldest_first_and_inclusive():
    months = trailing_months(Month(date(2026, 2, 1)), 4)
    assert [m.param for m in months] == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_months_between_inclusive_and_empty_when_reversed():
    assert len(months_between(Month(date(2026, 1, 1)), Month(date(2026, 12, 1)))) == 12
    assert months_between(Month(date(2026, 5, 1)), Month(date(2026, 4, 1))) == []
    assert len(months_between(Month(date(2026, 5, 1)), Month(date(2026, 5, 1)))) == 1


def test_parse_month_defaults_to_current():
    assert parse_month(None, None, TODAY) == (Month(date(2026, 11, 1)), True)
    assert parse_month("", "", TODAY) == (Month(date(2026, 11, 1)), True)


def test_parse_month_valid():
    month, valid = parse_month("2025", "3", TODAY)
    assert (month.first, valid) == (date(2025, 3, 1), True)


@pytest.mark.parametrize(
    "year, month",
    [("2026", "13"), ("2026", "0"), ("abc", "5"), ("2026", "x"), ("2026", None), (None, "5"), ("1999", "5"),
     ("2999", "5"), ("-2026", "5"), ("2026.5", "5"), ("2026", "1; DROP TABLE"), ("٢٠٢٦", "5"),
     ("²⁰²⁶", "5"), ("2026", "²"), ("2026", "①"), (" ", "5"), ("2026", "5\n7")],
)
def test_parse_month_invalid_falls_back_to_current(year, month):
    result, valid = parse_month(year, month, TODAY)
    assert result.first == date(2026, 11, 1) and valid is False


def test_parse_month_allows_up_to_next_year():
    assert parse_month("2027", "12", TODAY)[1] is True
    assert parse_month("2028", "1", TODAY)[1] is False


def test_parse_year():
    assert parse_year(None, TODAY) == (2026, True)
    assert parse_year("2024", TODAY) == (2024, True)
    for bad in ("abc", "1999", "2028", "-1", "20.5", "²⁰²⁶", "٢٠٢٦", "①"):
        assert parse_year(bad, TODAY) == (2026, False)
