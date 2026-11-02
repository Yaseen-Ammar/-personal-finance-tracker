from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Account, Budget, Category, FlowType, Transaction, User

from .conftest import (
    make_account,
    make_category,
    make_transaction,
    make_user,
)


# ---- User ----------------------------------------------------------------
def test_password_is_hashed_not_stored_plaintext(user):
    assert user.password_hash != "Sup3rSecret!"
    assert "Sup3rSecret!" not in user.password_hash
    assert user.check_password("Sup3rSecret!")
    assert not user.check_password("wrong")


def test_production_hash_method_is_scrypt():
    from config import BaseConfig, DevelopmentConfig, ProductionConfig

    assert BaseConfig.PASSWORD_HASH_METHOD == "scrypt"
    assert DevelopmentConfig.PASSWORD_HASH_METHOD == "scrypt"
    assert ProductionConfig.PASSWORD_HASH_METHOD == "scrypt"


def test_scrypt_hash_format(app):
    app.config["PASSWORD_HASH_METHOD"] = "scrypt"
    u = User(email="s@example.com", display_name="S")
    u.set_password("Sup3rSecret!")
    assert u.password_hash.startswith("scrypt:")
    assert u.check_password("Sup3rSecret!")


def test_same_password_gets_different_hashes(user, other_user):
    other_user.set_password("Sup3rSecret!")
    assert user.password_hash != other_user.password_hash  # per-password salt


def test_email_is_normalised_to_lowercase(app):
    u = make_user(email="  MiXed@Example.COM ")
    assert u.email == "mixed@example.com"


def test_duplicate_email_rejected(user):
    db.session.add(User(email="alice@example.com", display_name="Dup", password_hash="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_user_repr_never_leaks_hash(user):
    assert user.password_hash not in repr(user)


# ---- Accounts / categories ------------------------------------------------
def test_account_name_unique_per_user_but_reusable_across_users(user, other_user):
    make_account(user, "Savings")
    make_account(other_user, "Savings")  # allowed: different owner
    db.session.add(Account(user_id=user.id, name="Savings"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_category_same_name_allowed_for_different_type(user):
    make_category(user, "Other", FlowType.EXPENSE)
    make_category(user, "Other", FlowType.INCOME)
    db.session.add(Category(user_id=user.id, name="Other", type=FlowType.INCOME))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---- Transactions: money + isolation ---------------------------------------
def test_amount_keeps_exact_decimal_value(user):
    txn = make_transaction(user, make_account(user), make_category(user), "0.10")
    db.session.expire_all()
    stored = db.session.get(Transaction, txn.id)
    assert isinstance(stored.amount, Decimal)
    assert stored.amount == Decimal("0.10")


@pytest.mark.parametrize("amount", ["0.00", "-5.00"])
def test_non_positive_amount_rejected(user, amount):
    account, category = make_account(user), make_category(user)
    with pytest.raises(IntegrityError):
        make_transaction(user, account, category, amount)
    db.session.rollback()


def test_transaction_cannot_use_another_users_account(user, other_user):
    bobs_account = make_account(other_user)
    alices_category = make_category(user)
    with pytest.raises(IntegrityError):
        make_transaction(user, bobs_account, alices_category)
    db.session.rollback()


def test_transaction_cannot_use_another_users_category(user, other_user):
    alices_account = make_account(user)
    bobs_category = make_category(other_user)
    with pytest.raises(IntegrityError):
        make_transaction(user, alices_account, bobs_category)
    db.session.rollback()


def test_cannot_delete_account_that_has_transactions(user):
    account = make_account(user)
    make_transaction(user, account, make_category(user))
    db.session.delete(account)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_relationships_navigate_both_ways(user):
    account, category = make_account(user), make_category(user)
    txn = make_transaction(user, account, category)
    assert txn.account is account
    assert txn.category is category
    assert account.transactions == [txn]
    assert category.transactions == [txn]
    assert user.accounts == [account]


# ---- Budgets -----------------------------------------------------------------
def _budget(user, category, month=date(2026, 6, 1), amount="200.00"):
    budget = Budget(
        user_id=user.id, category_id=category.id, month=month, amount=Decimal(amount)
    )
    db.session.add(budget)
    db.session.commit()
    return budget


def test_budget_month_normalised_to_first_day(user):
    budget = _budget(user, make_category(user), month=date(2026, 6, 23))
    assert budget.month == date(2026, 6, 1)


def test_one_budget_per_category_per_month(user):
    category = make_category(user)
    _budget(user, category)
    with pytest.raises(IntegrityError):
        _budget(user, category, month=date(2026, 6, 28))  # same month
    db.session.rollback()


def test_budget_cannot_use_another_users_category(user, other_user):
    with pytest.raises(IntegrityError):
        _budget(user, make_category(other_user))
    db.session.rollback()


def test_budget_must_be_positive(user):
    with pytest.raises(IntegrityError):
        _budget(user, make_category(user), amount="0")
    db.session.rollback()
