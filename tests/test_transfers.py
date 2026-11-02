import logging
import re
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.extensions import db
from app.models import Transaction, Transfer
from app.services.account_service import archive_account
from app.services.common import ServiceError
from app.services.transfer_service import TransferInput, create_transfer, delete_transfer

from .conftest import JUNE, add_account, add_transfer, balance_of

D = Decimal


@pytest.fixture
def two(seeded_user):
    return (
        add_account(seeded_user, "Checking", opening="500.00"),
        add_account(seeded_user, "Savings", opening="0.00"),
    )


def count_transfers():
    db.session.expire_all()
    return db.session.query(Transfer).count()


def post(client, a, b, **overrides):
    data = {"from_account_id": a.id, "to_account_id": b.id, "amount": "100.00",
            "transfer_date": "2026-06-15", "description": "move"}
    data.update(overrides)
    return client.post("/transfers/new", data=data)


# ---- Happy path ---------------------------------------------------------------------
def test_transfer_updates_both_balances_consistently(alice_client, seeded_user, two):
    a, b = two
    assert post(alice_client, a, b).status_code == 302
    assert (balance_of(seeded_user, a), balance_of(seeded_user, b)) == (D("400.00"), D("100.00"))
    assert balance_of(seeded_user, a) + balance_of(seeded_user, b) == D("500.00")
    assert db.session.query(Transaction).count() == 0  # never income/expense


def test_transfer_pages_render(alice_client, seeded_user, two):
    a, b = two
    add_transfer(seeded_user, a, b, "12.34", desc="rainy day")
    assert alice_client.get("/transfers/new").status_code == 200
    html = alice_client.get("/transfers/").get_data(as_text=True)
    assert "rainy day" in html and "12.34" in html and "Checking" in html and "Savings" in html


def test_delete_transfer_restores_balances(alice_client, seeded_user, two):
    a, b = two
    t = add_transfer(seeded_user, a, b, "100.00")
    assert alice_client.get(f"/transfers/{t.id}/delete").status_code == 405
    assert alice_client.post(f"/transfers/{t.id}/delete").status_code == 302
    assert count_transfers() == 0
    assert (balance_of(seeded_user, a), balance_of(seeded_user, b)) == (D("500.00"), D("0.00"))


def test_form_preselects_two_different_accounts(alice_client, seeded_user, two):
    html = alice_client.get("/transfers/new").get_data(as_text=True)
    selected = re.findall(r'<select[^>]*name="(from_account_id|to_account_id)"[^>]*>(.*?)</select>', html, re.S)
    chosen = {name: re.search(r'<option[^>]*selected[^>]*>([^<]+)</option>', body).group(1) for name, body in selected}
    assert chosen == {"from_account_id": "Checking", "to_account_id": "Savings"}


def test_needs_two_accounts(alice_client, seeded_user):
    add_account(seeded_user, "Only")
    r = alice_client.get("/transfers/new")
    assert r.status_code == 302 and "/accounts" in r.headers["Location"]


# ---- Rejections ------------------------------------------------------------------------
def test_same_account_rejected_by_http_and_service(alice_client, seeded_user, two):
    a, _ = two
    r = post(alice_client, a, a)
    assert r.status_code == 200 and b"two different accounts" in r.data
    with pytest.raises(ServiceError, match="different accounts"):
        create_transfer(seeded_user.id, TransferInput(a.id, a.id, D("1"), JUNE))
    assert count_transfers() == 0


@pytest.mark.parametrize("amount", ["0", "0.00", "-10", "abc", "NaN", "1.005", "", "1000000000000"])
def test_bad_amounts_rejected(alice_client, seeded_user, two, amount):
    assert post(alice_client, *two, amount=amount).status_code == 200
    assert count_transfers() == 0


@pytest.mark.parametrize("amount", ["0", "-1", "0.001"])
def test_service_rejects_bad_amounts(seeded_user, two, amount):
    with pytest.raises(ServiceError):
        create_transfer(seeded_user.id, TransferInput(two[0].id, two[1].id, D(amount), JUNE))
    assert count_transfers() == 0


def test_bad_date_rejected(alice_client, two):
    assert post(alice_client, *two, transfer_date="1980-01-01").status_code == 200
    assert post(alice_client, *two, transfer_date="").status_code == 200
    assert count_transfers() == 0


def test_cross_user_transfer_rejected(app, seeded_user, seeded_other, alice_client):
    mine = add_account(seeded_user, "Mine", opening="50.00")
    mine2 = add_account(seeded_user, "Mine2")
    theirs = add_account(seeded_other, "Theirs")

    # Through the form: the foreign account isn't one of the allowed choices.
    assert post(alice_client, mine, theirs).status_code == 200
    assert post(alice_client, theirs, mine).status_code == 200
    # Through the service directly (defence in depth).
    for src, dst in ((mine, theirs), (theirs, mine)):
        with pytest.raises(ServiceError, match="valid accounts"):
            create_transfer(seeded_user.id, TransferInput(src.id, dst.id, D("1"), JUNE))
    assert count_transfers() == 0
    assert balance_of(seeded_other, theirs) == D("0.00")
    assert mine2 is not None


def test_cannot_transfer_to_or_from_archived_account(seeded_user, two):
    a, b = two
    add_transfer(seeded_user, a, b, "500.00")
    archive_account(seeded_user.id, a.id)  # now zero
    with pytest.raises(ServiceError, match="archived"):
        create_transfer(seeded_user.id, TransferInput(b.id, a.id, D("1"), JUNE))
    with pytest.raises(ServiceError, match="archived"):
        create_transfer(seeded_user.id, TransferInput(a.id, b.id, D("1"), JUNE))
    assert count_transfers() == 1


# ---- Atomicity & DB-level guarantees ---------------------------------------------------------
def test_failed_commit_leaves_no_partial_transfer(seeded_user, two, monkeypatch):
    a, b = two
    def boom():
        raise OperationalError("INSERT ...", {}, Exception("connection lost"))
    monkeypatch.setattr(db.session, "commit", boom)
    with pytest.raises(ServiceError, match="Something went wrong"):
        create_transfer(seeded_user.id, TransferInput(a.id, b.id, D("100"), JUNE))
    monkeypatch.undo()
    assert count_transfers() == 0
    assert (balance_of(seeded_user, a), balance_of(seeded_user, b)) == (D("500.00"), D("0.00"))


def test_database_errors_are_logged_without_sensitive_data(seeded_user, two, monkeypatch, caplog):
    a, b = two
    def boom():
        raise IntegrityError("INSERT ... VALUES ('super-secret-note')", {"d": "super-secret-note"}, Exception("x"))
    monkeypatch.setattr(db.session, "commit", boom)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ServiceError) as err:
            create_transfer(seeded_user.id, TransferInput(a.id, b.id, D("1"), JUNE, "super-secret-note"))
    assert "IntegrityError" in caplog.text
    assert "super-secret-note" not in caplog.text
    assert "super-secret-note" not in str(err.value)


def test_database_rejects_same_account_even_if_app_logic_is_bypassed(seeded_user, two):
    db.session.add(Transfer(user_id=seeded_user.id, from_account_id=two[0].id,
                            to_account_id=two[0].id, amount=D("1"), transfer_date=JUNE))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_database_rejects_cross_user_transfer_even_if_app_logic_is_bypassed(seeded_user, seeded_other, two):
    theirs = add_account(seeded_other, "Theirs")
    db.session.add(Transfer(user_id=seeded_user.id, from_account_id=two[0].id,
                            to_account_id=theirs.id, amount=D("1"), transfer_date=JUNE))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---- Listing -----------------------------------------------------------------------------
def test_transfer_list_paginates_newest_first(alice_client, seeded_user, two):
    a, b = two
    for i in range(20):
        add_transfer(seeded_user, a, b, "1.00", on=date(2026, 6, 1 + i), desc=f"t{i:02d}")
    one = alice_client.get("/transfers/").get_data(as_text=True)
    two_ = alice_client.get("/transfers/?page=2").get_data(as_text=True)
    assert "t19" in one and "t00" not in one
    assert "t00" in two_ and "page=2" in one


def test_delete_transfer_service_requires_ownership(seeded_user, seeded_other, two):
    t = add_transfer(seeded_user, *two, "1.00")
    from werkzeug.exceptions import NotFound
    with pytest.raises(NotFound):
        delete_transfer(seeded_other.id, t.id)
    assert db.session.execute(select(Transfer)).first() is not None
