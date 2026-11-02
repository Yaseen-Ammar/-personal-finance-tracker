"""Read-only financial analytics. All money maths is Decimal; every query is
scoped to `user_id`.

Definitions
-----------
* income / expenses : rows of `transactions` only. Transfers live in their own
  table, so they can never be counted as either (no double counting).
* period flows      : include archived accounts' history, so a past month's
  numbers never change when an account is archived later.
* balances          : see account_service (active accounts only).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import extract, func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Account, Category, FlowType, Transaction

from .common import ServiceError
from .periods import Month, max_year, months_between
from .validation import CENT

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
PERCENT = Decimal("0.1")


@dataclass(frozen=True)
class Scope:
    """Optional narrowing of a query to one account and/or one category."""

    account_id: int | None = None
    category_id: int | None = None


def savings_rate(income: Decimal, net: Decimal) -> Decimal | None:
    """Share of income kept, as a percentage; None when there is no income."""
    if income <= 0:
        return None
    return (net / income * HUNDRED).quantize(PERCENT)


@dataclass(frozen=True)
class PeriodTotals:
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    count: int = 0

    @property
    def net(self) -> Decimal:
        return (self.income - self.expenses).quantize(CENT)

    @property
    def savings_rate(self) -> Decimal | None:
        return savings_rate(self.income, self.net)


@dataclass(frozen=True)
class MonthTotals:
    month: Month
    income: Decimal = ZERO
    expenses: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return (self.income - self.expenses).quantize(CENT)

    @property
    def savings_rate(self) -> Decimal | None:
        return savings_rate(self.income, self.net)


@dataclass(frozen=True)
class CategorySpend:
    category_id: int | None
    name: str
    total: Decimal
    share: Decimal  # percentage of the period total, 1 dp


def pct_change(current: Decimal, previous: Decimal) -> Decimal | None:
    """Percentage change from `previous` to `current`; None if previous is zero."""
    if previous == 0:
        return None
    return ((current - previous) / previous * HUNDRED).quantize(PERCENT)


def validate_scope(user_id: int, scope: Scope) -> None:
    """Reject account/category ids that don't belong to this user."""
    if scope.account_id is not None:
        owned = db.session.execute(
            select(Account.id).where(Account.id == scope.account_id, Account.user_id == user_id)
        ).first()
        if owned is None:
            raise ServiceError("Please choose a valid account.")
    if scope.category_id is not None:
        owned = db.session.execute(
            select(Category.id).where(Category.id == scope.category_id, Category.user_id == user_id)
        ).first()
        if owned is None:
            raise ServiceError("Please choose a valid category.")


def _conditions(user_id: int, start: date, end: date, scope: Scope) -> list:
    conditions = [
        Transaction.user_id == user_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ]
    if scope.account_id is not None:
        conditions.append(Transaction.account_id == scope.account_id)
    if scope.category_id is not None:
        conditions.append(Transaction.category_id == scope.category_id)
    return conditions


def period_totals(user_id: int, start: date, end: date, scope: Scope = Scope()) -> PeriodTotals:
    rows = db.session.execute(
        select(Transaction.type, func.sum(Transaction.amount), func.count(Transaction.id))
        .where(*_conditions(user_id, start, end, scope))
        .group_by(Transaction.type)
    ).all()
    income = expenses = ZERO
    count = 0
    for flow, total, number in rows:
        count += number
        if flow is FlowType.INCOME:
            income = Decimal(total).quantize(CENT)
        else:
            expenses = Decimal(total).quantize(CENT)
    return PeriodTotals(income, expenses, count)


def monthly_totals(
    user_id: int, first: Month, last: Month, scope: Scope = Scope()
) -> list[MonthTotals]:
    """One entry per month from `first` to `last` inclusive; empty months are zeros."""
    months = months_between(first, last)
    if not months:
        return []
    year, month = extract("year", Transaction.transaction_date), extract(
        "month", Transaction.transaction_date
    )
    rows = db.session.execute(
        select(year, month, Transaction.type, func.sum(Transaction.amount))
        .where(*_conditions(user_id, first.first, last.last, scope))
        .group_by(year, month, Transaction.type)
    ).all()

    income: dict[tuple[int, int], Decimal] = {}
    expenses: dict[tuple[int, int], Decimal] = {}
    for y, m, flow, total in rows:
        target = income if flow is FlowType.INCOME else expenses
        target[(int(y), int(m))] = Decimal(total).quantize(CENT)

    return [
        MonthTotals(
            m,
            income.get((m.year, m.number), ZERO),
            expenses.get((m.year, m.number), ZERO),
        )
        for m in months
    ]


def category_totals(
    user_id: int, flow: FlowType, start: date, end: date, scope: Scope = Scope()
) -> list[CategorySpend]:
    """Per-category totals for one direction (expense or income), largest first."""
    total_expr = func.sum(Transaction.amount)
    rows = db.session.execute(
        select(Category.id, Category.name, total_expr)
        .join(Category, Transaction.category_id == Category.id)
        .where(*_conditions(user_id, start, end, scope), Transaction.type == flow)
        .group_by(Category.id, Category.name)
        .order_by(total_expr.desc(), Category.name)
    ).all()
    grand = sum((Decimal(total) for _, _, total in rows), ZERO)
    return [
        CategorySpend(
            category_id,
            name,
            Decimal(total).quantize(CENT),
            (Decimal(total) / grand * HUNDRED).quantize(PERCENT) if grand else ZERO,
        )
        for category_id, name, total in rows
    ]


def group_small_categories(items: list[CategorySpend], keep: int = 7) -> list[CategorySpend]:
    """Keep the `keep` largest and fold the rest into one 'Other' slice (for charts)."""
    if len(items) <= keep + 1:
        return items
    head, tail = items[:keep], items[keep:]
    total = sum((c.total for c in tail), ZERO).quantize(CENT)
    share = sum((c.share for c in tail), ZERO)
    return head + [CategorySpend(None, f"Other ({len(tail)} categories)", total, share)]


def recent_transactions(
    user_id: int, limit: int = 8, today: date | None = None
) -> list[Transaction]:
    """Latest transactions up to and including today (future-dated ones aren't 'recent')."""
    return list(
        db.session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.transaction_date <= (today or date.today()))
            .options(joinedload(Transaction.account), joinedload(Transaction.category))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(limit)
        )
        .scalars()
        .unique()
    )


def activity_bounds(user_id: int) -> tuple[date, date] | None:
    """(earliest, latest) transaction dates, or None when the user has none."""
    row = db.session.execute(
        select(func.min(Transaction.transaction_date), func.max(Transaction.transaction_date)).where(
            Transaction.user_id == user_id
        )
    ).one()
    return (row[0], row[1]) if row[0] is not None else None


def year_choices(user_id: int, today: date | None = None) -> list[int]:
    """Years offered in selectors: from the first activity (or this year) to next year."""
    today = today or date.today()
    bounds = activity_bounds(user_id)
    first = min(bounds[0].year, today.year) if bounds else today.year
    last = max(max_year(today), bounds[1].year if bounds else today.year)
    return list(range(first, last + 1))


# ---- Dashboard ----------------------------------------------------------------------------
TREND_MONTHS = 6


@dataclass(frozen=True)
class Dashboard:
    month: Month
    totals: PeriodTotals
    previous: PeriodTotals
    income_change: Decimal | None
    expense_change: Decimal | None
    trend: list[MonthTotals]
    spending: list[CategorySpend]
    recent: list[Transaction]
    has_transactions: bool


def build_dashboard(user_id: int, month: Month, today: date | None = None) -> Dashboard:
    previous_month = month.shift(-1)
    totals = period_totals(user_id, month.first, month.last)
    previous = period_totals(user_id, previous_month.first, previous_month.last)
    trend = monthly_totals(user_id, month.shift(-(TREND_MONTHS - 1)), month)
    return Dashboard(
        month=month,
        totals=totals,
        previous=previous,
        income_change=pct_change(totals.income, previous.income),
        expense_change=pct_change(totals.expenses, previous.expenses),
        trend=trend,
        spending=category_totals(user_id, FlowType.EXPENSE, month.first, month.last),
        recent=recent_transactions(user_id, today=today),
        has_transactions=activity_bounds(user_id) is not None,
    )


# ---- Analytics (one calendar year) ------------------------------------------------------------
@dataclass(frozen=True)
class MonthRow:
    totals: MonthTotals
    income_change: Decimal | None
    expense_change: Decimal | None
    cumulative_net: Decimal
    # A month that hasn't started yet and has no entries: shown as a gap, not
    # as a collapse to zero, and never compared against the previous month.
    pending: bool = False


@dataclass(frozen=True)
class YearAnalytics:
    year: int
    totals: PeriodTotals
    rows: list[MonthRow]
    spending: list[CategorySpend]
    income_sources: list[CategorySpend]
    busiest_spending_month: MonthTotals | None


def build_year_analytics(user_id: int, year: int, today: date | None = None) -> YearAnalytics:
    first = Month(date(year, 1, 1))
    last = Month(date(year, 12, 1))
    this_month = Month.of(today or date.today())
    # Fetch the previous December too so January can be compared with it.
    series = monthly_totals(user_id, first.shift(-1), last)
    prior, months = series[0], series[1:]

    rows, running, previous = [], ZERO, prior
    for entry in months:
        pending = entry.month.first > this_month.first and entry.income == 0 and entry.expenses == 0
        running = (running + entry.net).quantize(CENT)
        rows.append(
            MonthRow(
                entry,
                None if pending else pct_change(entry.income, previous.income),
                None if pending else pct_change(entry.expenses, previous.expenses),
                running,
                pending,
            )
        )
        previous = entry

    spending_months = [m for m in months if m.expenses > 0]
    return YearAnalytics(
        year=year,
        totals=period_totals(user_id, first.first, last.last),
        rows=rows,
        spending=category_totals(user_id, FlowType.EXPENSE, first.first, last.last),
        income_sources=category_totals(user_id, FlowType.INCOME, first.first, last.last),
        busiest_spending_month=max(spending_months, key=lambda m: m.expenses, default=None),
    )
