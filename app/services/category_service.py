"""Category rules.

* Every user gets their own copy of the default categories (is_default=True).
  Defaults are immutable: they cannot be renamed, retyped or deleted.
* Custom categories can be renamed; their type can change only while unused.
* A category that still has transactions can never be deleted.
"""
from dataclasses import dataclass

from sqlalchemy import func, select

from app.extensions import db
from app.models import Category, FlowType, Transaction

from .common import ServiceError, commit, get_owned_or_404
from .validation import clean_text

NAME_MAX = 80

DEFAULT_EXPENSE_CATEGORIES = (
    "Groceries", "Rent & Housing", "Utilities", "Transport", "Dining Out",
    "Health", "Entertainment", "Shopping", "Education", "Other Expense",
)
DEFAULT_INCOME_CATEGORIES = (
    "Salary", "Freelance", "Investments", "Gifts", "Other Income",
)


@dataclass(frozen=True)
class CategoryRow:
    category: Category
    transaction_count: int


def seed_default_categories(user_id: int) -> None:
    """Add the default categories to the session (caller commits). Idempotent."""
    existing = set(
        db.session.execute(
            select(Category.type, func.lower(Category.name)).where(
                Category.user_id == user_id
            )
        ).all()
    )
    for flow, names in (
        (FlowType.EXPENSE, DEFAULT_EXPENSE_CATEGORIES),
        (FlowType.INCOME, DEFAULT_INCOME_CATEGORIES),
    ):
        for name in names:
            if (flow, name.lower()) not in existing:
                db.session.add(
                    Category(user_id=user_id, name=name, type=flow, is_default=True)
                )


def list_categories(user_id: int) -> list[CategoryRow]:
    counts = dict(
        db.session.execute(
            select(Transaction.category_id, func.count(Transaction.id))
            .where(Transaction.user_id == user_id)
            .group_by(Transaction.category_id)
        ).all()
    )
    categories = db.session.execute(
        select(Category)
        .where(Category.user_id == user_id)
        .order_by(Category.type, Category.is_default.desc(), func.lower(Category.name))
    ).scalars()
    return [CategoryRow(c, counts.get(c.id, 0)) for c in categories]


def _name_taken(user_id: int, flow: FlowType, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Category.id).where(
        Category.user_id == user_id,
        Category.type == flow,
        func.lower(Category.name) == name.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return db.session.execute(stmt).first() is not None


def create_category(user_id: int, name: str, flow: FlowType) -> Category:
    name = clean_text(name, field="Category name", max_len=NAME_MAX, required=True)
    if _name_taken(user_id, flow, name):
        raise ServiceError(f"You already have a {flow.value} category named '{name}'.")
    category = Category(user_id=user_id, name=name, type=flow, is_default=False)
    db.session.add(category)
    commit("creating a category")
    return category


def _transaction_count(category_id: int) -> int:
    return db.session.execute(
        select(func.count(Transaction.id)).where(Transaction.category_id == category_id)
    ).scalar_one()


def update_category(user_id: int, category_id: int, name: str, flow: FlowType) -> Category:
    category = get_owned_or_404(Category, category_id, user_id)
    if category.is_default:
        raise ServiceError("Default categories can't be edited.")
    name = clean_text(name, field="Category name", max_len=NAME_MAX, required=True)
    if flow != category.type:
        used = _transaction_count(category.id)
        if used:
            raise ServiceError(
                f"This category has {used} transaction(s), so its type can't be changed."
            )
    if _name_taken(user_id, flow, name, exclude_id=category.id):
        raise ServiceError(f"You already have a {flow.value} category named '{name}'.")
    category.name = name
    category.type = flow
    commit("updating a category")
    return category


def delete_category(user_id: int, category_id: int) -> None:
    category = get_owned_or_404(Category, category_id, user_id)
    if category.is_default:
        raise ServiceError("Default categories can't be deleted.")
    used = _transaction_count(category.id)
    if used:
        raise ServiceError(
            f"'{category.name}' is used by {used} transaction(s). Edit or delete "
            "those transactions first, then delete the category."
        )
    # Any budgets for the category are removed by the database (ON DELETE CASCADE).
    db.session.delete(category)
    commit("deleting a category")
