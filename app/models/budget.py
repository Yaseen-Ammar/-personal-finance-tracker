from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

from .base import MONEY

if TYPE_CHECKING:
    from .category import Category
    from .user import User


class Budget(db.Model):
    """A spending limit for one category in one calendar month."""

    __tablename__ = "budgets"
    __table_args__ = (
        # One budget per user/category/month. Its leading (user_id, category_id)
        # columns also serve as the index MySQL needs for the composite FK below.
        UniqueConstraint(
            "user_id", "category_id", "month", name="uq_budgets_user_id_category_id_month"
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="CASCADE",  # a budget is meaningless without its category
            name="fk_budgets_category_owner",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)  # always the 1st
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="budgets")
    category: Mapped[Category] = relationship(
        back_populates="budgets",
        primaryjoin="Budget.category_id == Category.id",
        foreign_keys=[category_id],
    )

    @validates("month")
    def _normalise_month(self, _key: str, value: date) -> date:
        """Collapse any date to the first of its month so 'June' is one key."""
        return value.replace(day=1)
