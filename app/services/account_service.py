"""Account rules and balance calculation.

Balance is never stored. For each account:

    opening_balance + income - expenses + transfers_in - transfers_out

is computed from the rows, so it cannot drift out of sync.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from app.currency import format_money
from app.extensions import db
from app.models import Account, AccountType, FlowType, Transaction, Transfer

from .common import ServiceError, commit, get_owned_or_404
from .validation import CENT, clean_text, validate_amount

NAME_MAX = 100
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class AccountSummary:
    account: Account
    balance: Decimal


def account_balances(user_id: int) -> dict[int, Decimal]:
    """Balance for every account the user owns (archived included)."""
    balances: dict[int, Decimal] = {
        acc_id: Decimal(opening)
        for acc_id, opening in db.session.execute(
            select(Account.id, Account.opening_balance).where(Account.user_id == user_id)
        )
    }

    for acc_id, flow, total in db.session.execute(
        select(Transaction.account_id, Transaction.type, func.sum(Transaction.amount))
        .where(Transaction.user_id == user_id)
        .group_by(Transaction.account_id, Transaction.type)
    ):
        signed = Decimal(total) if flow is FlowType.INCOME else -Decimal(total)
        balances[acc_id] += signed

    for acc_id, total in db.session.execute(
        select(Transfer.from_account_id, func.sum(Transfer.amount))
        .where(Transfer.user_id == user_id)
        .group_by(Transfer.from_account_id)
    ):
        balances[acc_id] -= Decimal(total)

    for acc_id, total in db.session.execute(
        select(Transfer.to_account_id, func.sum(Transfer.amount))
        .where(Transfer.user_id == user_id)
        .group_by(Transfer.to_account_id)
    ):
        balances[acc_id] += Decimal(total)

    return {acc_id: bal.quantize(CENT) for acc_id, bal in balances.items()}


def list_accounts(user_id: int, *, include_archived: bool = False) -> list[Account]:
    stmt = select(Account).where(Account.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Account.is_archived.is_(False))
    return list(db.session.execute(stmt.order_by(func.lower(Account.name))).scalars())


def summarize_accounts(
    user_id: int, *, include_archived: bool = False
) -> tuple[list[AccountSummary], Decimal]:
    """Per-account balances plus the total across ACTIVE accounts."""
    balances = account_balances(user_id)
    summaries = [
        AccountSummary(a, balances.get(a.id, ZERO))
        for a in list_accounts(user_id, include_archived=include_archived)
    ]
    total = sum((s.balance for s in summaries if not s.account.is_archived), ZERO)
    return summaries, total.quantize(CENT)


def get_active_account(user_id: int, account_id: int) -> Account:
    """Owned, non-archived account for new activity, or ServiceError."""
    account = db.session.execute(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    ).scalar_one_or_none()
    if account is None:
        raise ServiceError("Please choose a valid account.")
    if account.is_archived:
        raise ServiceError(f"'{account.name}' is archived. Restore it first.")
    return account


def _name_taken(user_id: int, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Account.id).where(
        Account.user_id == user_id, func.lower(Account.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Account.id != exclude_id)
    return db.session.execute(stmt).first() is not None


def create_account(
    user_id: int, name: str, account_type: AccountType, opening_balance
) -> Account:
    name = clean_text(name, field="Account name", max_len=NAME_MAX, required=True)
    opening = validate_amount(opening_balance, field="Opening balance", allow_negative=True)
    if _name_taken(user_id, name):
        raise ServiceError(f"You already have an account named '{name}'.")
    account = Account(
        user_id=user_id, name=name, account_type=account_type, opening_balance=opening
    )
    db.session.add(account)
    commit("creating an account")
    return account


def update_account(
    user_id: int, account_id: int, name: str, account_type: AccountType, opening_balance
) -> Account:
    account = get_owned_or_404(Account, account_id, user_id)
    if account.is_archived:
        raise ServiceError("Restore this account before editing it.")
    name = clean_text(name, field="Account name", max_len=NAME_MAX, required=True)
    opening = validate_amount(opening_balance, field="Opening balance", allow_negative=True)
    if _name_taken(user_id, name, exclude_id=account.id):
        raise ServiceError(f"You already have an account named '{name}'.")
    account.name = name
    account.account_type = account_type
    account.opening_balance = opening
    commit("updating an account")
    return account


def archive_account(user_id: int, account_id: int) -> Account:
    """Archive only when the balance is zero, so the total never silently shrinks."""
    account = get_owned_or_404(Account, account_id, user_id)
    if account.is_archived:
        return account
    balance = account_balances(user_id).get(account.id, ZERO)
    if balance != ZERO:
        raise ServiceError(
            f"'{account.name}' still holds {format_money(balance)}. Transfer or spend the "
            "balance down to zero before archiving."
        )
    account.is_archived = True
    commit("archiving an account")
    return account


def restore_account(user_id: int, account_id: int) -> Account:
    account = get_owned_or_404(Account, account_id, user_id)
    account.is_archived = False
    commit("restoring an account")
    return account
