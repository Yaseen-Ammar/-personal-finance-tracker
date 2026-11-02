import re
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import FlowType, Transaction
from app.services.transaction_service import TransactionFilters, search_transactions

from .conftest import add_account, add_txn, balance_of, category_of

D = Decimal


@pytest.fixture
def acct(seeded_user):
    return add_account(seeded_user, "Checking", opening="1000.00")


def form(user, acct, cat_name, **overrides):
    data = {
        "type": category_of(user, cat_name).type.value,
        "account_id": acct.id,
        "category_id": category_of(user, cat_name).id,
        "amount": "25.00",
        "transaction_date": "2026-06-15",
        "description": "lunch",
    }
    data.update(overrides)
    return data


def all_txns():
    db.session.expire_all()
    return db.session.execute(select(Transaction)).scalars().all()


# ---- Create ------------------------------------------------------------------
def test_add_expense(alice_client, seeded_user, acct):
    r = alice_client.post("/transactions/new", data=form(seeded_user, acct, "Groceries"))
    assert r.status_code == 302 and r.headers["Location"].endswith("/transactions/")
    (t,) = all_txns()
    assert (t.type, t.amount, t.user_id, t.description) == (
        FlowType.EXPENSE, D("25.00"), seeded_user.id, "lunch")
    assert balance_of(seeded_user, acct) == D("975.00")


def test_add_income(alice_client, seeded_user, acct):
    alice_client.post("/transactions/new", data=form(seeded_user, acct, "Salary", amount="1500"))
    assert all_txns()[0].type is FlowType.INCOME
    assert balance_of(seeded_user, acct) == D("2500.00")


def test_new_page_renders_with_requested_type_and_category_types(alice_client, acct):
    html = alice_client.get("/transactions/new?type=income").get_data(as_text=True)
    assert re.search(r'<option[^>]*\bselected\b[^>]*value="income"|<option[^>]*value="income"[^>]*\bselected\b', html)
    assert not re.search(r'<option[^>]*\bselected\b[^>]*value="expense"', html)
    assert 'data-type="income"' in html and 'data-type="expense"' in html


def test_new_without_account_redirects_to_create_one(alice_client):
    r = alice_client.get("/transactions/new")
    assert r.status_code == 302 and "/accounts/new" in r.headers["Location"]


# ---- Invalid input -------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "abc"}, {"amount": "0"}, {"amount": "-5"}, {"amount": "1.234"},
        {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": ""},
        {"amount": "1000000000000"},
        {"transaction_date": ""}, {"transaction_date": "not-a-date"},
        {"transaction_date": "1999-01-01"}, {"transaction_date": "2999-01-01"},
        {"description": "x" * 256},
        {"type": "transfer"},
        {"category_id": "999999"}, {"category_id": "abc"}, {"account_id": "999999"},
    ],
)
def test_invalid_input_creates_nothing(alice_client, seeded_user, acct, overrides):
    r = alice_client.post("/transactions/new", data=form(seeded_user, acct, "Groceries", **overrides))
    assert r.status_code == 200  # form re-rendered with errors, not a 500
    assert all_txns() == []


def test_category_of_wrong_type_rejected(alice_client, seeded_user, acct):
    r = alice_client.post(
        "/transactions/new", data=form(seeded_user, acct, "Salary", type="expense")
    )
    assert r.status_code == 200
    assert b"not an expense category" in r.data
    assert all_txns() == []


def test_html_in_description_is_escaped(alice_client, seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "5.00", desc="<script>alert(1)</script>")
    body = alice_client.get("/transactions/").data
    assert b"<script>alert(1)</script>" not in body and b"&lt;script&gt;" in body


# ---- Edit / delete ---------------------------------------------------------------
def test_edit_transaction(alice_client, seeded_user, acct):
    t = add_txn(seeded_user, acct, "Groceries", "10.00", desc="old")
    assert alice_client.get(f"/transactions/{t.id}/edit").status_code == 200
    r = alice_client.post(
        f"/transactions/{t.id}/edit",
        data=form(seeded_user, acct, "Salary", amount="99.99", description="new"),
    )
    assert r.status_code == 302
    db.session.expire_all()
    t = db.session.get(Transaction, t.id)
    assert (t.type, t.amount, t.description) == (FlowType.INCOME, D("99.99"), "new")
    assert balance_of(seeded_user, acct) == D("1099.99")


def test_edit_with_invalid_amount_leaves_row_unchanged(alice_client, seeded_user, acct):
    t = add_txn(seeded_user, acct, "Groceries", "10.00")
    alice_client.post(
        f"/transactions/{t.id}/edit", data=form(seeded_user, acct, "Groceries", amount="-1")
    )
    db.session.expire_all()
    assert db.session.get(Transaction, t.id).amount == D("10.00")


def test_delete_requires_post_then_removes_and_restores_balance(alice_client, seeded_user, acct):
    t = add_txn(seeded_user, acct, "Groceries", "40.00")
    assert alice_client.get(f"/transactions/{t.id}/delete").status_code == 405
    r = alice_client.post(f"/transactions/{t.id}/delete")
    assert r.status_code == 302
    assert all_txns() == []
    assert balance_of(seeded_user, acct) == D("1000.00")


def test_delete_redirects_back_only_to_safe_next(alice_client, seeded_user, acct):
    t1 = add_txn(seeded_user, acct, "Groceries", "1.00")
    t2 = add_txn(seeded_user, acct, "Groceries", "2.00")
    ok = alice_client.post(f"/transactions/{t1.id}/delete", data={"next": "/transactions/?type=expense"})
    assert ok.headers["Location"].endswith("/transactions/?type=expense")
    evil = alice_client.post(f"/transactions/{t2.id}/delete", data={"next": "https://evil.example"})
    assert evil.headers["Location"].endswith("/transactions/")


def test_delete_confirmation_dialog_is_rendered(alice_client, seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "40.00", desc="weekly shop")
    html = alice_client.get("/transactions/").get_data(as_text=True)
    assert 'id="confirmModal"' in html and "data-confirm-action" in html
    assert "weekly shop" in html


# ---- Filtering, search, sorting ------------------------------------------------------
@pytest.fixture
def mixed(seeded_user):
    a = add_account(seeded_user, "Checking", opening="0.00")
    b = add_account(seeded_user, "Savings", opening="0.00")
    add_txn(seeded_user, a, "Salary", "3000.00", on=date(2026, 5, 1), desc="May salary")
    add_txn(seeded_user, a, "Groceries", "50.00", on=date(2026, 5, 10), desc="Tesco shop")
    add_txn(seeded_user, a, "Dining Out", "30.00", on=date(2026, 6, 2), desc="Pizza night")
    add_txn(seeded_user, b, "Groceries", "75.00", on=date(2026, 6, 20), desc="100% organic_box")
    add_txn(seeded_user, b, "Gifts", "10.00", on=date(2026, 6, 25), desc="Birthday")
    return a, b


def found(user, **kw):
    return [t.description for t in search_transactions(user.id, TransactionFilters(**kw)).items]


def test_filter_by_type(seeded_user, mixed):
    assert sorted(found(seeded_user, type=FlowType.INCOME)) == ["Birthday", "May salary"]
    assert len(found(seeded_user, type=FlowType.EXPENSE)) == 3


def test_filter_by_category_and_account(seeded_user, mixed):
    groceries = category_of(seeded_user, "Groceries")
    assert sorted(found(seeded_user, category_id=groceries.id)) == ["100% organic_box", "Tesco shop"]
    assert sorted(found(seeded_user, account_id=mixed[1].id)) == ["100% organic_box", "Birthday"]


def test_filter_by_date_range_inclusive(seeded_user, mixed):
    got = found(seeded_user, date_from=date(2026, 5, 10), date_to=date(2026, 6, 2))
    assert sorted(got) == ["Pizza night", "Tesco shop"]


def test_search_is_case_insensitive_substring(seeded_user, mixed):
    assert found(seeded_user, q="PIZZA") == ["Pizza night"]


@pytest.mark.parametrize("q, expected", [("%", ["100% organic_box"]), ("_", ["100% organic_box"]),
                                          ("100%", ["100% organic_box"])])
def test_search_wildcards_are_literal(seeded_user, mixed, q, expected):
    assert found(seeded_user, q=q) == expected


def test_search_is_not_injectable(seeded_user, mixed):
    assert found(seeded_user, q="' OR '1'='1") == []
    assert found(seeded_user, q="'; DROP TABLE transactions; --") == []
    assert len(found(seeded_user)) == 5


def test_combined_filters(seeded_user, mixed):
    got = found(seeded_user, type=FlowType.EXPENSE, account_id=mixed[0].id, q="shop")
    assert got == ["Tesco shop"]


def test_sorting(seeded_user, mixed):
    assert found(seeded_user, sort="date_desc")[0] == "Birthday"
    assert found(seeded_user, sort="date_asc")[0] == "May salary"
    assert found(seeded_user, sort="amount_desc")[0] == "May salary"
    assert found(seeded_user, sort="amount_asc")[0] == "Birthday"


def test_unknown_sort_falls_back_safely(seeded_user, mixed):
    assert found(seeded_user, sort="id; DROP TABLE users")[0] == "Birthday"


def test_filters_through_http(alice_client, mixed):
    html = alice_client.get("/transactions/?type=income&q=salary").get_data(as_text=True)
    assert "May salary" in html and "Tesco shop" not in html


@pytest.mark.parametrize("qs", ["date_from=garbage", "category=abc", "sort=zzz", "type=bogus",
                                "date_from=2026-06-01&date_to=2026-01-01", "page=abc", "page=-3",
                                "page=99999", "q=" + "a" * 500])
def test_bad_query_params_never_500(alice_client, mixed, qs):
    assert alice_client.get(f"/transactions/?{qs}").status_code == 200


# ---- Pagination -------------------------------------------------------------------------
@pytest.fixture
def many(seeded_user):
    acct = add_account(seeded_user, "Big")
    for i in range(35):
        add_txn(seeded_user, acct, "Groceries", f"{i + 1}.00", on=date(2026, 6, 1 + i % 28), desc=f"item{i:02d}")
    return acct


def test_pagination_splits_results(seeded_user, many):
    p1 = search_transactions(seeded_user.id, TransactionFilters(), page=1, per_page=15)
    p3 = search_transactions(seeded_user.id, TransactionFilters(), page=3, per_page=15)
    assert (p1.total, p1.pages, len(p1.items), len(p3.items)) == (35, 3, 15, 5)
    p2_ids = {t.id for t in search_transactions(seeded_user.id, TransactionFilters(), page=2, per_page=15).items}
    assert p2_ids.isdisjoint({t.id for t in p1.items}) and p2_ids.isdisjoint({t.id for t in p3.items})


def test_page_beyond_end_is_empty_not_error(seeded_user, many):
    assert search_transactions(seeded_user.id, TransactionFilters(), page=99).items == []


def test_pagination_links_keep_filters(alice_client, many):
    html = alice_client.get("/transactions/?type=expense&sort=amount_desc").get_data(as_text=True)
    assert "page=2" in html and "type=expense" in html and "sort=amount_desc" in html


def test_page_two_shows_different_rows(alice_client, many):
    one = alice_client.get("/transactions/?sort=amount_asc").get_data(as_text=True)
    two = alice_client.get("/transactions/?sort=amount_asc&page=2").get_data(as_text=True)
    assert "item00" in one and "item00" not in two
    assert "item15" in two


# ---- Isolation ------------------------------------------------------------------------
def test_search_only_returns_own_transactions(seeded_user, seeded_other):
    mine, theirs = add_account(seeded_user, "A"), add_account(seeded_other, "A")
    add_txn(seeded_user, mine, "Groceries", "1.00", desc="mine")
    add_txn(seeded_other, theirs, "Groceries", "2.00", desc="theirs")
    assert found(seeded_user) == ["mine"]
    assert found(seeded_other) == ["theirs"]
