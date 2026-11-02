"""Transfers between a user's own accounts."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Account, Transfer

from .common import ServiceError, commit, get_owned_or_404
from .validation import clean_text, validate_amount, validate_date

DESCRIPTION_MAX = 255


@dataclass(frozen=True)
class TransferInput:
    from_account_id: int
    to_account_id: int
    amount: Decimal
    transfer_date: date
    description: str = ""


def create_transfer(user_id: int, data: TransferInput) -> Transfer:
    """Create a transfer atomically.

    A transfer is ONE row (see the Transfer model), so both balances change
    together or not at all. The two account rows are locked first (in id
    order, which avoids deadlocks) so neither can be archived by a concurrent
    request between the checks below and the commit.
    """
    if data.from_account_id == data.to_account_id:
        raise ServiceError("Choose two different accounts for a transfer.")
    amount = validate_amount(data.amount, field="Transfer amount")
    when = validate_date(data.transfer_date, field="Date")
    description = clean_text(data.description, field="Description", max_len=DESCRIPTION_MAX)

    ids = sorted({data.from_account_id, data.to_account_id})
    locked = {
        a.id: a
        for a in db.session.execute(
            select(Account)
            .where(Account.id.in_(ids), Account.user_id == user_id)
            .order_by(Account.id)
            .with_for_update()
        ).scalars()
    }
    if len(locked) != 2:  # a missing id means "not yours" or "doesn't exist"
        db.session.rollback()
        raise ServiceError("Please choose valid accounts.")
    for account in locked.values():
        if account.is_archived:
            db.session.rollback()
            raise ServiceError(f"'{account.name}' is archived. Restore it first.")

    transfer = Transfer(
        user_id=user_id,
        from_account_id=data.from_account_id,
        to_account_id=data.to_account_id,
        amount=amount,
        transfer_date=when,
        description=description,
    )
    db.session.add(transfer)
    commit("creating a transfer")
    return transfer


def delete_transfer(user_id: int, transfer_id: int) -> None:
    transfer = get_owned_or_404(Transfer, transfer_id, user_id)
    if transfer.from_account.is_archived or transfer.to_account.is_archived:
        raise ServiceError("Restore the archived account before deleting this transfer.")
    db.session.delete(transfer)
    commit("deleting a transfer")


def list_transfers(user_id: int, *, page: int = 1, per_page: int = 15) -> Pagination:
    stmt = (
        select(Transfer)
        .where(Transfer.user_id == user_id)
        .options(joinedload(Transfer.from_account), joinedload(Transfer.to_account))
        .order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
    )
    return db.paginate(stmt, page=max(page, 1), per_page=per_page, max_per_page=100, error_out=False)
