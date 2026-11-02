from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Account, Category, FlowType
from app.services.category_service import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    seed_default_categories,
)

from .conftest import add_account, add_txn, category_of

D = Decimal


def my_accounts(user):
    db.session.expire_all()
    return db.session.execute(select(Account).filter_by(user_id=user.id)).scalars().all()


# ---- Accounts ------------------------------------------------------------------
def test_create_account(alice_client, seeded_user):
    r = alice_client.post("/accounts/new", data={"name": " Cash ", "account_type": "cash", "opening_balance": "20.50"})
    assert r.status_code == 302
    (a,) = my_accounts(seeded_user)
    assert (a.name, a.opening_balance, a.is_archived) == ("Cash", D("20.50"), False)


def test_accounts_page_shows_balances_and_total(alice_client, seeded_user):
    a = add_account(seeded_user, "Checking", opening="100.00")
    add_account(seeded_user, "Savings", opening="50.25")
    add_txn(seeded_user, a, "Groceries", "10.00")
    html = alice_client.get("/accounts/").get_data(as_text=True)
    assert "90.00" in html and "50.25" in html and "140.25" in html


@pytest.mark.parametrize(
    "data",
    [{"name": "", "opening_balance": "0"}, {"name": "x" * 101, "opening_balance": "0"},
     {"name": "A", "opening_balance": "abc"}, {"name": "A", "opening_balance": "NaN"},
     {"name": "A", "opening_balance": "1.005"}, {"name": "A", "opening_balance": ""},
     {"name": "A", "opening_balance": "0", "account_type": "bogus"}],
)
def test_invalid_account_rejected(alice_client, seeded_user, data):
    payload = {"account_type": "cash", **data}
    assert alice_client.post("/accounts/new", data=payload).status_code == 200
    assert my_accounts(seeded_user) == []


def test_duplicate_account_name_rejected_case_insensitively(alice_client, seeded_user):
    add_account(seeded_user, "Savings")
    r = alice_client.post("/accounts/new", data={"name": "SAVINGS", "account_type": "savings", "opening_balance": "0"})
    assert b"already have an account" in r.data
    assert len(my_accounts(seeded_user)) == 1


def test_two_users_may_use_the_same_account_name(seeded_user, seeded_other):
    add_account(seeded_user, "Savings")
    add_account(seeded_other, "Savings")  # no error


def test_edit_account_name_and_opening_balance(alice_client, seeded_user):
    a = add_account(seeded_user, "Old", opening="10.00")
    r = alice_client.post(f"/accounts/{a.id}/edit", data={"name": "New", "account_type": "savings", "opening_balance": "-5.00"})
    assert r.status_code == 302
    db.session.expire_all()
    a = db.session.get(Account, a.id)
    assert (a.name, a.opening_balance, a.account_type.value) == ("New", D("-5.00"), "savings")


def test_archive_and_restore_via_http(alice_client, seeded_user):
    a = add_account(seeded_user, "Zero")
    assert alice_client.post(f"/accounts/{a.id}/archive").status_code == 302
    db.session.expire_all()
    assert db.session.get(Account, a.id).is_archived
    assert b"Zero" not in alice_client.get("/accounts/").data
    assert b"Zero" in alice_client.get("/accounts/?archived=1").data
    assert alice_client.get(f"/accounts/{a.id}/edit").status_code == 302  # read-only while archived
    alice_client.post(f"/accounts/{a.id}/restore")
    db.session.expire_all()
    assert not db.session.get(Account, a.id).is_archived


def test_archive_with_balance_refused_via_http(alice_client, seeded_user):
    a = add_account(seeded_user, "Rich", opening="5.00")
    r = alice_client.post(f"/accounts/{a.id}/archive", follow_redirects=True)
    assert b"balance down to zero" in r.data
    db.session.expire_all()
    assert not db.session.get(Account, a.id).is_archived


# ---- Categories ----------------------------------------------------------------------
def test_registration_seeds_default_categories(client):
    client.post("/auth/register", data={
        "display_name": "Dee", "email": "dee@example.com",
        "password": "Passw0rd123", "confirm_password": "Passw0rd123"})
    db.session.expire_all()
    cats = db.session.execute(select(Category)).scalars().all()
    assert len(cats) == len(DEFAULT_EXPENSE_CATEGORIES) + len(DEFAULT_INCOME_CATEGORIES)
    assert all(c.is_default for c in cats)
    assert {c.type for c in cats} == {FlowType.INCOME, FlowType.EXPENSE}


def test_seeding_is_idempotent_and_per_user(seeded_user, seeded_other):
    seed_default_categories(seeded_user.id)
    db.session.commit()
    mine = db.session.execute(select(Category).filter_by(user_id=seeded_user.id)).scalars().all()
    assert len(mine) == len(DEFAULT_EXPENSE_CATEGORIES) + len(DEFAULT_INCOME_CATEGORIES)
    assert {c.id for c in mine}.isdisjoint(
        {c.id for c in db.session.execute(select(Category).filter_by(user_id=seeded_other.id)).scalars()})


def test_categories_page_lists_defaults(alice_client):
    html = alice_client.get("/categories/").get_data(as_text=True)
    assert "Groceries" in html and "Salary" in html and "Default" in html


def test_create_custom_category(alice_client, seeded_user):
    r = alice_client.post("/categories/new", data={"name": "Pets", "type": "expense"})
    assert r.status_code == 302
    c = category_of(seeded_user, "Pets")
    assert (c.type, c.is_default) == (FlowType.EXPENSE, False)


@pytest.mark.parametrize("name, kind", [("groceries", "expense"), ("GROCERIES", "expense"), ("", "expense"),
                                        ("x" * 81, "expense"), ("Pets", "bogus")])
def test_invalid_or_duplicate_category_rejected(alice_client, seeded_user, name, kind):
    before = db.session.query(Category).count()
    assert alice_client.post("/categories/new", data={"name": name, "type": kind}).status_code == 200
    assert db.session.query(Category).count() == before


def test_same_name_allowed_across_types(alice_client, seeded_user):
    r = alice_client.post("/categories/new", data={"name": "Groceries", "type": "income"})
    assert r.status_code == 302
    kinds = db.session.execute(
        select(Category.type).filter_by(user_id=seeded_user.id, name="Groceries")
    ).scalars().all()
    assert sorted(k.value for k in kinds) == ["expense", "income"]


def test_default_categories_cannot_be_edited_or_deleted(alice_client, seeded_user):
    groceries = category_of(seeded_user, "Groceries")
    assert alice_client.get(f"/categories/{groceries.id}/edit").status_code == 302
    alice_client.post(f"/categories/{groceries.id}/edit", data={"name": "Hacked", "type": "expense"})
    alice_client.post(f"/categories/{groceries.id}/delete")
    db.session.expire_all()
    assert db.session.get(Category, groceries.id).name == "Groceries"


def test_rename_and_delete_unused_custom_category(alice_client, seeded_user):
    alice_client.post("/categories/new", data={"name": "Pets", "type": "expense"})
    pets_id = category_of(seeded_user, "Pets").id
    alice_client.post(f"/categories/{pets_id}/edit", data={"name": "Pet care", "type": "expense"})
    db.session.expire_all()
    assert db.session.get(Category, pets_id).name == "Pet care"
    alice_client.post(f"/categories/{pets_id}/delete")
    db.session.expire_all()
    assert db.session.get(Category, pets_id) is None


def test_category_in_use_cannot_be_deleted_or_retyped(alice_client, seeded_user):
    alice_client.post("/categories/new", data={"name": "Pets", "type": "expense"})
    pets_id = category_of(seeded_user, "Pets").id
    add_txn(seeded_user, add_account(seeded_user), "Pets", "9.00")

    r = alice_client.post(f"/categories/{pets_id}/delete", follow_redirects=True)
    assert b"used by 1 transaction" in r.data
    r = alice_client.post(f"/categories/{pets_id}/edit", data={"name": "Pets", "type": "income"})
    assert b"type can&#39;t be changed" in r.data  # apostrophe is HTML-escaped
    db.session.expire_all()
    pets = db.session.get(Category, pets_id)
    assert pets is not None and pets.type is FlowType.EXPENSE


def test_category_usage_count_shown(alice_client, seeded_user):
    add_txn(seeded_user, add_account(seeded_user), "Groceries", "1.00")
    assert "1 transaction" in alice_client.get("/categories/").get_data(as_text=True)
