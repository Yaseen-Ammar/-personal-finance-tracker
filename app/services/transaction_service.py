"""Transaction CRUD and search. Every query is scoped by user_id."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Category, FlowType, Transaction

from .account_service import get_active_account
from .common import ServiceError, commit, get_owned_or_404
from .validation import clean_text, validate_amount, validate_date

DESCRIPTION_MAX = 255
SEARCH_MAX = 100
MAX_PER_PAGE = 100

# Whitelist: user-supplied sort keys map to fixed ORDER BY clauses (never
# interpolated into SQL). `id` is a tiebreaker so paging is stable.
SORTS = {
    "date_desc": (Transaction.transaction_date.desc(), Transaction.id.desc()),
    "date_asc": (Transaction.transaction_date.asc(), Transaction.id.asc()),
    "amount_desc": (Transaction.amount.desc(), Transaction.id.desc()),
    "amount_asc": (Transaction.amount.asc(), Transaction.id.asc()),
}
DEFAULT_SORT = "date_desc"


@dataclass(frozen=True)
class TransactionInput:
    type: FlowType
    account_id: int
    category_id: int
    amount: Decimal
    transaction_date: date
    description: str = ""


@dataclass(frozen=True)
class TransactionFilters:
    q: str = ""
    type: FlowType | None = None
    category_id: int | None = None
    account_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort: str = DEFAULT_SORT


def _validated(user_id: int, data: TransactionInput) -> tuple[Decimal, date, str, Category]:
    amount = validate_amount(data.amount)
    when = validate_date(data.transaction_date, field="Date")
    description = clean_text(data.description, field="Description", max_len=DESCRIPTION_MAX)
    get_active_account(user_id, data.account_id)

    category = db.session.execute(
        select(Category).where(Category.id == data.category_id, Category.user_id == user_id)
    ).scalar_one_or_none()
    if category is None:
        raise ServiceError("Please choose a valid category.")
    if category.type != data.type:
        raise ServiceError(
            f"'{category.name}' is not an {data.type.value} category. "
            "Pick a category that matches the transaction type."
        )
    return amount, when, description, category


def create_transaction(user_id: int, data: TransactionInput) -> Transaction:
    amount, when, description, _ = _validated(user_id, data)
    txn = Transaction(
        user_id=user_id,
        account_id=data.account_id,
        category_id=data.category_id,
        type=data.type,
        amount=amount,
        transaction_date=when,
        description=description,
    )
    db.session.add(txn)
    commit("creating a transaction")
    return txn


def _require_editable(txn: Transaction) -> None:
    if txn.account.is_archived:
        raise ServiceError(
            f"'{txn.account.name}' is archived. Restore it before changing its transactions."
        )


def update_transaction(user_id: int, txn_id: int, data: TransactionInput) -> Transaction:
    txn = get_owned_or_404(Transaction, txn_id, user_id)
    _require_editable(txn)
    amount, when, description, _ = _validated(user_id, data)
    txn.account_id = data.account_id
    txn.category_id = data.category_id
    txn.type = data.type
    txn.amount = amount
    txn.transaction_date = when
    txn.description = description
    commit("updating a transaction")
    return txn


def delete_transaction(user_id: int, txn_id: int) -> None:
    txn = get_owned_or_404(Transaction, txn_id, user_id)
    _require_editable(txn)
    db.session.delete(txn)
    commit("deleting a transaction")


def _escape_like(value: str) -> str:
    """Make %, _ and \\ in user search text match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_transactions(
    user_id: int, filters: TransactionFilters, *, page: int = 1, per_page: int = 15
) -> Pagination:
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .options(joinedload(Transaction.account), joinedload(Transaction.category))
    )
    if filters.q:
        pattern = f"%{_escape_like(filters.q[:SEARCH_MAX])}%"
        stmt = stmt.where(Transaction.description.ilike(pattern, escape="\\"))
    if filters.type is not None:
        stmt = stmt.where(Transaction.type == filters.type)
    if filters.category_id:
        stmt = stmt.where(Transaction.category_id == filters.category_id)
    if filters.account_id:
        stmt = stmt.where(Transaction.account_id == filters.account_id)
    if filters.date_from:
        stmt = stmt.where(Transaction.transaction_date >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Transaction.transaction_date <= filters.date_to)

    stmt = stmt.order_by(*SORTS.get(filters.sort, SORTS[DEFAULT_SORT]))
    return db.paginate(
        stmt, page=max(page, 1), per_page=per_page, max_per_page=MAX_PER_PAGE, error_out=False
    )
