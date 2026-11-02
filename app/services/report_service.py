"""Filtered reports and CSV export. Read-only; every query scoped to `user_id`."""
import csv
import io
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import FlowType, Transaction

from .analytics_service import (
    CategorySpend,
    MonthTotals,
    PeriodTotals,
    Scope,
    category_totals,
    monthly_totals,
    period_totals,
    validate_scope,
)
from .common import ServiceError
from .periods import Month, days_inclusive, year_start
from .validation import validate_date

MAX_RANGE_DAYS = 3660  # ~10 years: bounds the monthly table and export size
EXPORT_BATCH = 500
# Characters that make a spreadsheet treat a cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class ReportFilters:
    date_from: date
    date_to: date
    account_id: int | None = None
    category_id: int | None = None

    @property
    def scope(self) -> Scope:
        return Scope(self.account_id, self.category_id)


@dataclass(frozen=True)
class Report:
    filters: ReportFilters
    totals: PeriodTotals
    months: list[MonthTotals]
    expense_categories: list[CategorySpend]
    income_categories: list[CategorySpend]


def default_filters(today: date | None = None) -> ReportFilters:
    """Year to date."""
    today = today or date.today()
    return ReportFilters(year_start(today.year), today)


def validate_filters(user_id: int, filters: ReportFilters) -> ReportFilters:
    validate_date(filters.date_from, field="'From' date")
    validate_date(filters.date_to, field="'To' date")
    if filters.date_to < filters.date_from:
        raise ServiceError("'To' date must not be before 'From' date.")
    if days_inclusive(filters.date_from, filters.date_to) > MAX_RANGE_DAYS:
        raise ServiceError("Please choose a range of 10 years or less.")
    validate_scope(user_id, filters.scope)
    return filters


def build_report(user_id: int, filters: ReportFilters) -> Report:
    validate_filters(user_id, filters)
    scope = filters.scope
    return Report(
        filters=filters,
        totals=period_totals(user_id, filters.date_from, filters.date_to, scope),
        months=monthly_totals(
            user_id, Month.of(filters.date_from), Month.of(filters.date_to), scope
        ),
        expense_categories=category_totals(
            user_id, FlowType.EXPENSE, filters.date_from, filters.date_to, scope
        ),
        income_categories=category_totals(
            user_id, FlowType.INCOME, filters.date_from, filters.date_to, scope
        ),
    )


# ---- CSV ----------------------------------------------------------------------------------------
def safe_cell(value: str) -> str:
    """Neutralise CSV/formula injection.

    A description like "=HYPERLINK(...)" would run as a formula when the file
    is opened in Excel/Sheets. A leading apostrophe makes it plain text.
    """
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def plain_amount(value: Decimal) -> str:
    """Fixed-point text with no thousands separators or currency symbol."""
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def csv_stream(rows: Iterable[Sequence[str]]) -> Iterator[str]:
    """Yield CSV text row by row. Starts with a BOM so Excel reads it as UTF-8."""
    yield "﻿"
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


TRANSACTION_HEADER = ("Date", "Type", "Account", "Category", "Description", "Amount", "Signed amount")


def transaction_rows(user_id: int, filters: ReportFilters) -> Iterator[list[str]]:
    validate_filters(user_id, filters)
    stmt = (
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= filters.date_from,
            Transaction.transaction_date <= filters.date_to,
        )
        .options(joinedload(Transaction.account), joinedload(Transaction.category))
        .order_by(Transaction.transaction_date, Transaction.id)
        .execution_options(yield_per=EXPORT_BATCH)
    )
    if filters.account_id is not None:
        stmt = stmt.where(Transaction.account_id == filters.account_id)
    if filters.category_id is not None:
        stmt = stmt.where(Transaction.category_id == filters.category_id)

    yield list(TRANSACTION_HEADER)
    for txn in db.session.execute(stmt).scalars():
        signed = txn.amount if txn.type is FlowType.INCOME else -txn.amount
        yield [
            txn.transaction_date.isoformat(),
            txn.type.value,
            safe_cell(txn.account.name),
            safe_cell(txn.category.name),
            safe_cell(txn.description),
            plain_amount(txn.amount),
            plain_amount(signed),
        ]


SUMMARY_HEADER = ("Month", "Income", "Expenses", "Net", "Savings rate (%)")


def summary_rows(user_id: int, filters: ReportFilters) -> Iterator[list[str]]:
    report = build_report(user_id, filters)
    yield list(SUMMARY_HEADER)
    for entry in report.months:
        rate = entry.savings_rate
        yield [
            entry.month.param,
            plain_amount(entry.income),
            plain_amount(entry.expenses),
            plain_amount(entry.net),
            "" if rate is None else format(rate, "f"),
        ]
    totals = report.totals
    yield [
        "Total",
        plain_amount(totals.income),
        plain_amount(totals.expenses),
        plain_amount(totals.net),
        "" if totals.savings_rate is None else format(totals.savings_rate, "f"),
    ]


def export_filename(kind: str, filters: ReportFilters) -> str:
    """Built only from validated dates, so it can never carry user-supplied text."""
    return f"{kind}_{filters.date_from.isoformat()}_to_{filters.date_to.isoformat()}.csv"
