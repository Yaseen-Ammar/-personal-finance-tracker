"""Calendar helpers for month/year based views. Pure functions, no database."""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .validation import MIN_DATE

MAX_YEAR_AHEAD = 1  # selectors reach to next year, matching how far ahead dates may be entered


@dataclass(frozen=True)
class Month:
    """One calendar month. `first` is always day 1."""

    first: date

    @property
    def year(self) -> int:
        return self.first.year

    @property
    def number(self) -> int:
        return self.first.month

    @property
    def last(self) -> date:
        return date(self.year, self.number, calendar.monthrange(self.year, self.number)[1])

    @property
    def param(self) -> str:
        return f"{self.year:04d}-{self.number:02d}"

    @property
    def label(self) -> str:
        return self.first.strftime("%B %Y")

    @property
    def short_label(self) -> str:
        return self.first.strftime("%b %Y")

    def shift(self, months: int) -> "Month":
        index = self.year * 12 + (self.number - 1) + months
        return Month(date(index // 12, index % 12 + 1, 1))

    @staticmethod
    def of(day: date) -> "Month":
        return Month(day.replace(day=1))


def current_month(today: date | None = None) -> Month:
    return Month.of(today or date.today())


def max_year(today: date | None = None) -> int:
    return (today or date.today()).year + MAX_YEAR_AHEAD


def _is_ascii_number(value: str | None) -> bool:
    """True only for plain 0-9 digits.

    str.isdigit() is NOT enough: it accepts characters like '²' and Arabic-Indic
    digits, and int('²') then raises ValueError (a 500 from a crafted URL).
    """
    if not value:
        return False
    text = value.strip()
    return text.isascii() and text.isdigit()


def parse_month(
    year: str | None, month: str | None, today: date | None = None
) -> tuple[Month, bool]:
    """Parse `?year=2026&month=10`. Returns (month, was_valid).

    Both missing -> current month (valid). Anything malformed or out of range
    -> current month with was_valid=False, so the page can say so instead of
    failing. Two plain parameters (not 'YYYY-MM') so a no-JS <select> form works.
    """
    now = current_month(today)
    if not year and not month:
        return now, True
    if not (_is_ascii_number(year) and _is_ascii_number(month)):
        return now, False
    y, m = int(year), int(month)
    if not (1 <= m <= 12) or y < MIN_DATE.year or y > max_year(today):
        return now, False
    return Month(date(y, m, 1)), True


def parse_year(value: str | None, today: date | None = None) -> tuple[int, bool]:
    now_year = (today or date.today()).year
    if value is None or value == "":
        return now_year, True
    if not _is_ascii_number(value):
        return now_year, False
    year = int(value)
    if year < MIN_DATE.year or year > max_year(today):
        return now_year, False
    return year, True


def months_between(start: Month, end: Month) -> list[Month]:
    """Inclusive list of months from `start` to `end` (empty if end < start)."""
    out, cursor = [], start
    while cursor.first <= end.first:
        out.append(cursor)
        cursor = cursor.shift(1)
    return out


def trailing_months(end: Month, count: int) -> list[Month]:
    """The `count` months ending at (and including) `end`, oldest first."""
    return [end.shift(-offset) for offset in range(count - 1, -1, -1)]


def days_inclusive(start: date, end: date) -> int:
    return (end - start).days + 1


def year_start(year: int) -> date:
    return date(year, 1, 1)


def tomorrow(today: date | None = None) -> date:
    return (today or date.today()) + timedelta(days=1)
