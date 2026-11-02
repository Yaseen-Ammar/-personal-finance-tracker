"""Balance calculation, income/expense categorisation and archive rules."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Account, FlowType
from app.services.account_service import (
    archive_account,
    list_accounts,
    restore_account,
    summarize_accounts,
)
from app.services.common import ServiceError
from app.services.transaction_service import TransactionInput, create_transaction

from .conftest import (
    JUNE,
    add_account,
    add_transfer,
    add_txn,
    balance_of,
    category_of,
)

D = Decimal


def test_balance_is_opening_plus_income_minus_expenses(seeded_user):
    acct = add_account(seeded_user, opening="100.00")
    add_txn(seeded_user, acct, "Salary", "500.00")
    add_txn(seeded_user, acct, "Groceries", "42.50")
    add_txn(seeded_user, acct, "Rent & Housing", "300.00")
    assert balance_of(seeded_user, acct) == D("257.50")


def test_account_with_no_activity_has_opening_balance(seeded_user):
    assert balance_of(seeded_user, add_account(seeded_user, opening="75.25")) == D("75.25")


def test_negative_opening_balance_supported(seeded_user):
    acct = add_account(seeded_user, "Credit card", opening="-200.00")
    add_txn(seeded_user, acct, "Groceries", "50.00")
    assert balance_of(seeded_user, acct) == D("-250.00")


def test_decimal_arithmetic_is_exact(seeded_user):
    acct = add_account(seeded_user)
    for _ in range(3):
        add_txn(seeded_user, acct, "Salary", "0.10")
    assert balance_of(seeded_user, acct) == D("0.30")  # float would give 0.30000000000000004


def test_transfers_move_money_without_changing_total(seeded_user):
    checking = add_account(seeded_user, "Checking", opening="1000.00")
    savings = add_account(seeded_user, "Savings", opening="50.00")
    add_transfer(seeded_user, checking, savings, "250.00")
    assert balance_of(seeded_user, checking) == D("750.00")
    assert balance_of(seeded_user, savings) == D("300.00")
    _, total = summarize_accounts(seeded_user.id)
    assert total == D("1050.00")


def test_transfer_is_not_counted_as_income_or_expense(seeded_user):
    from app.models import Transaction

    a, b = add_account(seeded_user, "A", opening="100.00"), add_account(seeded_user, "B")
    add_transfer(seeded_user, a, b, "40.00")
    assert db.session.query(Transaction).count() == 0


def test_category_type_must_match_transaction_type(seeded_user):
    acct = add_account(seeded_user)
    salary = category_of(seeded_user, "Salary")  # an INCOME category
    with pytest.raises(ServiceError, match="not an expense category"):
        create_transaction(
            seeded_user.id,
            TransactionInput(FlowType.EXPENSE, acct.id, salary.id, D("5"), JUNE),
        )
    groceries = category_of(seeded_user, "Groceries")  # an EXPENSE category
    with pytest.raises(ServiceError, match="not an income category"):
        create_transaction(
            seeded_user.id,
            TransactionInput(FlowType.INCOME, acct.id, groceries.id, D("5"), JUNE),
        )


def test_balances_are_isolated_between_users(seeded_user, seeded_other):
    mine = add_account(seeded_user, "Main", opening="10.00")
    theirs = add_account(seeded_other, "Main", opening="999.00")
    add_txn(seeded_other, theirs, "Salary", "1.00")
    assert balance_of(seeded_user, mine) == D("10.00")
    summaries, total = summarize_accounts(seeded_user.id)
    assert [s.account.id for s in summaries] == [mine.id]
    assert total == D("10.00")


def test_total_balance_sums_active_accounts(seeded_user):
    add_account(seeded_user, "A", opening="10.00")
    add_account(seeded_user, "B", opening="-4.50")
    _, total = summarize_accounts(seeded_user.id)
    assert total == D("5.50")


# ---- Archiving -----------------------------------------------------------------
def test_cannot_archive_account_with_balance(seeded_user):
    acct = add_account(seeded_user, opening="10.00")
    with pytest.raises(ServiceError, match="zero"):
        archive_account(seeded_user.id, acct.id)
    assert not db.session.get(Account, acct.id).is_archived


def test_archive_zero_balance_account_hides_and_freezes_it(seeded_user):
    acct = add_account(seeded_user, "Old")
    add_account(seeded_user, "Live", opening="5.00")
    archive_account(seeded_user.id, acct.id)

    assert [a.name for a in list_accounts(seeded_user.id)] == ["Live"]
    assert {a.name for a in list_accounts(seeded_user.id, include_archived=True)} == {"Old", "Live"}
    with pytest.raises(ServiceError, match="archived"):
        add_txn(seeded_user, acct, "Salary", "1.00")


def test_archived_account_excluded_from_total_and_restorable(seeded_user):
    acct = add_account(seeded_user, "Old")
    live = add_account(seeded_user, "Live", opening="5.00")
    archive_account(seeded_user.id, acct.id)
    _, total = summarize_accounts(seeded_user.id)
    assert total == D("5.00")

    restore_account(seeded_user.id, acct.id)
    add_txn(seeded_user, acct, "Salary", "1.00")  # allowed again
    assert balance_of(seeded_user, acct) == D("1.00")
    assert live.id != acct.id
