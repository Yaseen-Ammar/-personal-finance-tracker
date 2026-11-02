"""Dashboard/analytics calculations. Everything is exact Decimal arithmetic."""
from datetime import date
from decimal import Decimal

import pytest

from app.models import FlowType
from app.services.account_service import archive_account, summarize_accounts
from app.services.analytics_service import (
    CategorySpend,
    Scope,
    activity_bounds,
    build_dashboard,
    build_year_analytics,
    category_totals,
    group_small_categories,
    monthly_totals,
    pct_change,
    period_totals,
    recent_transactions,
    savings_rate,
    validate_scope,
    year_choices,
)
from app.services.common import ServiceError
from app.services.periods import Month

from .conftest import add_account, add_transfer, add_txn, category_of

D = Decimal
JUNE = Month(date(2026, 6, 1))


@pytest.fixture
def acct(seeded_user):
    return add_account(seeded_user, "Checking", opening="1000.00")


def totals(user, month=JUNE, scope=Scope()):
    return period_totals(user.id, month.first, month.last, scope)


# ---- Empty / zero --------------------------------------------------------------------------
def test_user_with_no_data_gets_zeroes_everywhere(seeded_user):
    t = totals(seeded_user)
    assert (t.income, t.expenses, t.net, t.count, t.savings_rate) == (D("0.00"), D("0.00"), D("0.00"), 0, None)
    series = monthly_totals(seeded_user.id, JUNE.shift(-5), JUNE)
    assert len(series) == 6 and all(m.income == 0 and m.expenses == 0 and m.net == 0 for m in series)
    assert category_totals(seeded_user.id, FlowType.EXPENSE, JUNE.first, JUNE.last) == []
    assert recent_transactions(seeded_user.id) == []
    assert activity_bounds(seeded_user.id) is None


def test_dashboard_for_a_brand_new_user(seeded_user):
    data = build_dashboard(seeded_user.id, JUNE)
    assert data.has_transactions is False and data.recent == [] and data.spending == []
    assert data.income_change is None and data.expense_change is None
    assert len(data.trend) == 6


def test_account_without_transactions_has_only_its_opening_balance(seeded_user):
    add_account(seeded_user, "Empty", opening="42.00")
    summaries, total = summarize_accounts(seeded_user.id)
    assert [s.balance for s in summaries] == [D("42.00")] and total == D("42.00")
    assert totals(seeded_user).count == 0


# ---- Totals ---------------------------------------------------------------------------------------
def test_income_expenses_and_net(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "3000.00", on=date(2026, 6, 1))
    add_txn(seeded_user, acct, "Freelance", "250.50", on=date(2026, 6, 10))
    add_txn(seeded_user, acct, "Groceries", "120.25", on=date(2026, 6, 12))
    add_txn(seeded_user, acct, "Rent & Housing", "1000.00", on=date(2026, 6, 30))
    t = totals(seeded_user)
    assert (t.income, t.expenses, t.net, t.count) == (D("3250.50"), D("1120.25"), D("2130.25"), 4)
    assert t.savings_rate == D("65.5")  # 2130.25 / 3250.50


def test_totals_are_decimal_and_exact(seeded_user, acct):
    for _ in range(3):
        add_txn(seeded_user, acct, "Salary", "0.10", on=date(2026, 6, 2))
    t = totals(seeded_user)
    assert type(t.income) is D and t.income == D("0.30")  # float would be 0.30000000000000004
    assert type(t.net) is D


def test_negative_net_and_overspending_rate(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "100.00")
    add_txn(seeded_user, acct, "Shopping", "150.00")
    t = totals(seeded_user)
    assert t.net == D("-50.00") and t.savings_rate == D("-50.0")


def test_expenses_only_month_has_no_savings_rate(seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "10.00")
    assert totals(seeded_user).savings_rate is None


def test_month_boundaries_are_inclusive_and_exact(seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2026, 5, 31))   # day before
    add_txn(seeded_user, acct, "Groceries", "2.00", on=date(2026, 6, 1))    # first day
    add_txn(seeded_user, acct, "Groceries", "4.00", on=date(2026, 6, 30))   # last day
    add_txn(seeded_user, acct, "Groceries", "8.00", on=date(2026, 7, 1))    # day after
    assert totals(seeded_user).expenses == D("6.00")


# ---- Transfers must not inflate anything --------------------------------------------------------------
def test_transfers_never_change_income_or_expenses(seeded_user, acct):
    other = add_account(seeded_user, "Savings")
    add_txn(seeded_user, acct, "Salary", "500.00", on=date(2026, 6, 5))
    before = (totals(seeded_user), category_totals(seeded_user.id, FlowType.EXPENSE, JUNE.first, JUNE.last))
    add_transfer(seeded_user, acct, other, "999.99", on=date(2026, 6, 6))
    add_transfer(seeded_user, other, acct, "100.00", on=date(2026, 6, 7))
    after = (totals(seeded_user), category_totals(seeded_user.id, FlowType.EXPENSE, JUNE.first, JUNE.last))
    assert before == after
    t = totals(seeded_user)
    assert (t.income, t.expenses, t.count) == (D("500.00"), D("0.00"), 1)
    assert all(m.income + m.expenses == (D("500.00") if m.month == JUNE else 0)
               for m in monthly_totals(seeded_user.id, JUNE, JUNE.shift(1)))


def test_transfers_move_balances_but_not_the_total(seeded_user, acct):
    other = add_account(seeded_user, "Savings", opening="10.00")
    _, before = summarize_accounts(seeded_user.id)
    add_transfer(seeded_user, acct, other, "300.00")
    summaries, after = summarize_accounts(seeded_user.id)
    assert after == before == D("1010.00")
    assert {s.account.name: s.balance for s in summaries} == {"Checking": D("700.00"), "Savings": D("310.00")}


# ---- Archived accounts ----------------------------------------------------------------------------------------
def test_archived_accounts_leave_balances_but_keep_history_in_flows(seeded_user, acct):
    old = add_account(seeded_user, "Old card")
    add_txn(seeded_user, old, "Salary", "100.00", on=date(2026, 6, 3))
    add_txn(seeded_user, old, "Groceries", "100.00", on=date(2026, 6, 4))  # now zero balance
    archive_account(seeded_user.id, old.id)

    summaries, total = summarize_accounts(seeded_user.id)
    assert [s.account.name for s in summaries] == ["Checking"] and total == D("1000.00")
    t = totals(seeded_user)  # last month's figures must not change because of archiving
    assert (t.income, t.expenses) == (D("100.00"), D("100.00"))


# ---- Scoping -------------------------------------------------------------------------------------------------------
def test_scope_by_account_and_category(seeded_user, acct):
    second = add_account(seeded_user, "Card")
    add_txn(seeded_user, acct, "Groceries", "10.00")
    add_txn(seeded_user, second, "Groceries", "20.00")
    add_txn(seeded_user, second, "Transport", "5.00")
    assert totals(seeded_user, scope=Scope(account_id=second.id)).expenses == D("25.00")
    groceries = category_of(seeded_user, "Groceries").id
    assert totals(seeded_user, scope=Scope(category_id=groceries)).expenses == D("30.00")
    assert totals(seeded_user, scope=Scope(second.id, groceries)).expenses == D("20.00")


# ---- Cross-user isolation ----------------------------------------------------------------------------------------------
def test_other_users_data_never_leaks_into_any_calculation(seeded_user, seeded_other, acct):
    theirs = add_account(seeded_other, "Theirs")
    add_txn(seeded_other, theirs, "Salary", "9999.00", on=date(2026, 6, 2), desc="their pay")
    add_txn(seeded_other, theirs, "Groceries", "8888.00", on=date(2026, 6, 3))
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2026, 6, 4))

    assert (totals(seeded_user).income, totals(seeded_user).expenses) == (D("0.00"), D("1.00"))
    assert [m.expenses for m in monthly_totals(seeded_user.id, JUNE, JUNE)] == [D("1.00")]
    assert [c.total for c in category_totals(seeded_user.id, FlowType.EXPENSE, JUNE.first, JUNE.last)] == [D("1.00")]
    assert [t.description for t in recent_transactions(seeded_user.id)] == [""]
    assert activity_bounds(seeded_user.id) == (date(2026, 6, 4), date(2026, 6, 4))
    _, total = summarize_accounts(seeded_user.id)
    assert total == D("999.00")


def test_scope_with_another_users_ids_is_rejected(seeded_user, seeded_other, acct):
    theirs = add_account(seeded_other, "Theirs")
    their_cat = category_of(seeded_other, "Groceries")
    with pytest.raises(ServiceError, match="valid account"):
        validate_scope(seeded_user.id, Scope(account_id=theirs.id))
    with pytest.raises(ServiceError, match="valid category"):
        validate_scope(seeded_user.id, Scope(category_id=their_cat.id))
    validate_scope(seeded_user.id, Scope(account_id=acct.id))  # own ids are fine
    validate_scope(seeded_user.id, Scope())


# ---- Monthly series & categories ----------------------------------------------------------------------------------------------
def test_monthly_series_is_zero_filled_and_crosses_years(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "100.00", on=date(2025, 12, 31))
    add_txn(seeded_user, acct, "Groceries", "40.00", on=date(2026, 2, 1))
    series = monthly_totals(seeded_user.id, Month(date(2025, 11, 1)), Month(date(2026, 3, 1)))
    assert [m.month.param for m in series] == ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
    assert [(m.income, m.expenses) for m in series] == [
        (D("0.00"), D("0.00")), (D("100.00"), D("0.00")), (D("0.00"), D("0.00")),
        (D("0.00"), D("40.00")), (D("0.00"), D("0.00"))]


def test_monthly_series_empty_range(seeded_user):
    assert monthly_totals(seeded_user.id, JUNE, JUNE.shift(-1)) == []


def test_category_totals_sorted_with_shares(seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "60.00")
    add_txn(seeded_user, acct, "Groceries", "40.00")
    add_txn(seeded_user, acct, "Transport", "50.00")
    add_txn(seeded_user, acct, "Health", "50.00")  # ties with Transport: name breaks the tie
    add_txn(seeded_user, acct, "Salary", "999.00")  # income never appears in spending
    rows = category_totals(seeded_user.id, FlowType.EXPENSE, JUNE.first, JUNE.last)
    assert [(r.name, r.total, r.share) for r in rows] == [
        ("Groceries", D("100.00"), D("50.0")), ("Health", D("50.00"), D("25.0")), ("Transport", D("50.00"), D("25.0"))]
    income = category_totals(seeded_user.id, FlowType.INCOME, JUNE.first, JUNE.last)
    assert [(r.name, r.share) for r in income] == [("Salary", D("100.0"))]


def test_group_small_categories_folds_the_tail():
    items = [CategorySpend(i, f"c{i}", D(100 - i), D("10.0")) for i in range(12)]
    grouped = group_small_categories(items, keep=7)
    assert len(grouped) == 8 and grouped[-1].name == "Other (5 categories)"
    assert grouped[-1].total == sum((i.total for i in items[7:]), D("0")) and grouped[-1].category_id is None
    assert group_small_categories(items[:8], keep=7) == items[:8]  # not worth folding one item


# ---- Comparisons ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "current, previous, expected",
    [("150", "100", "50.0"), ("50", "100", "-50.0"), ("100", "100", "0.0"), ("1", "3", "-66.7"), ("5", "0", None), ("0", "0", None)],
)
def test_pct_change(current, previous, expected):
    result = pct_change(D(current), D(previous))
    assert result == (None if expected is None else D(expected))


def test_savings_rate_helper():
    assert savings_rate(D("0"), D("0")) is None
    assert savings_rate(D("200"), D("50")) == D("25.0")


def test_dashboard_compares_with_previous_month(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "1000.00", on=date(2026, 5, 10))
    add_txn(seeded_user, acct, "Groceries", "200.00", on=date(2026, 5, 11))
    add_txn(seeded_user, acct, "Salary", "1500.00", on=date(2026, 6, 10))
    add_txn(seeded_user, acct, "Groceries", "100.00", on=date(2026, 6, 11))
    data = build_dashboard(seeded_user.id, JUNE)
    assert data.income_change == D("50.0") and data.expense_change == D("-50.0")
    assert (data.previous.income, data.previous.expenses) == (D("1000.00"), D("200.00"))
    assert data.has_transactions and [m.month.param for m in data.trend][-1] == "2026-06"


def test_recent_transactions_newest_first_and_limited(seeded_user, acct):
    for day in range(1, 13):
        add_txn(seeded_user, acct, "Groceries", f"{day}.00", on=date(2026, 6, day), desc=f"d{day:02d}")
    recent = recent_transactions(seeded_user.id, limit=8)
    assert [t.description for t in recent] == [f"d{d:02d}" for d in range(12, 4, -1)]


# ---- Year analytics -------------------------------------------------------------------------------------------------------------------
def test_year_analytics_rows_comparison_and_running_net(seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "100.00", on=date(2025, 12, 15))   # previous December
    add_txn(seeded_user, acct, "Salary", "1000.00", on=date(2026, 1, 15))
    add_txn(seeded_user, acct, "Groceries", "150.00", on=date(2026, 1, 20))
    add_txn(seeded_user, acct, "Groceries", "300.00", on=date(2026, 2, 20))
    add_txn(seeded_user, acct, "Salary", "9999.00", on=date(2027, 1, 1))        # other year: ignored
    year = build_year_analytics(seeded_user.id, 2026)
    assert len(year.rows) == 12
    jan, feb, mar = year.rows[0], year.rows[1], year.rows[2]
    assert jan.expense_change == D("50.0")            # 150 vs December's 100
    assert jan.income_change is None                   # nothing in December to compare
    assert feb.expense_change == D("100.0")           # 300 vs January's 150
    assert feb.income_change == D("-100.0")           # 0 vs January's 1000: income fell by all of it
    assert (jan.cumulative_net, feb.cumulative_net, mar.cumulative_net) == (D("850.00"), D("550.00"), D("550.00"))
    assert (year.totals.income, year.totals.expenses) == (D("1000.00"), D("450.00"))
    assert year.busiest_spending_month.month.param == "2026-02"
    assert [c.name for c in year.spending] == ["Groceries"] and [c.name for c in year.income_sources] == ["Salary"]


def test_pending_months_are_flagged_and_not_compared(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "100.00", on=date(2026, 3, 2))
    add_txn(seeded_user, acct, "Groceries", "10.00", on=date(2026, 8, 2))    # future month WITH data
    year = build_year_analytics(seeded_user.id, 2026, today=date(2026, 3, 15))
    flags = [r.pending for r in year.rows]
    assert flags == [False, False, False, True, True, True, True, False, True, True, True, True]
    assert all(r.income_change is None and r.expense_change is None for r in year.rows if r.pending)
    assert year.rows[7].totals.expenses == D("10.00") and year.rows[7].expense_change is None  # prev month empty
    assert not any(r.pending for r in build_year_analytics(seeded_user.id, 2026, today=date(2026, 12, 31)).rows)


def test_recent_transactions_exclude_future_dates(seeded_user, acct):
    today = date(2026, 6, 10)
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2026, 6, 9), desc="yesterday")
    add_txn(seeded_user, acct, "Groceries", "2.00", on=today, desc="today")
    add_txn(seeded_user, acct, "Groceries", "3.00", on=date(2026, 6, 11), desc="tomorrow")
    assert [t.description for t in recent_transactions(seeded_user.id, today=today)] == ["today", "yesterday"]
    # ...but they still count towards the month they belong to.
    assert period_totals(seeded_user.id, JUNE.first, JUNE.last).expenses == D("6.00")


def test_year_with_no_activity(seeded_user):
    year = build_year_analytics(seeded_user.id, 2024)
    assert len(year.rows) == 12 and year.busiest_spending_month is None
    assert year.totals.count == 0 and year.spending == [] and year.rows[-1].cumulative_net == D("0.00")


def test_year_choices_cover_activity_and_next_year(seeded_user, acct):
    today = date(2026, 11, 2)
    assert year_choices(seeded_user.id, today) == [2026, 2027]
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2023, 5, 1))
    assert year_choices(seeded_user.id, today) == [2023, 2024, 2025, 2026, 2027]
