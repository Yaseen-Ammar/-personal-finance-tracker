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
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .base import MONEY, FlowType, enum_column

if TYPE_CHECKING:
    from .account import Account
    from .category import Category
    from .user import User


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        # Composite FKs: the referenced account/category must belong to the
        # SAME user as the transaction. This is database-level data isolation.
        # RESTRICT: an account/category that still has transactions can't be deleted.
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_transactions_account_owner",
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_transactions_category_owner",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        # Stored amount is always positive; `type` carries the direction.
        Index("ix_transactions_user_id_transaction_date", "user_id", "transaction_date"),
        Index("ix_transactions_user_id_account_id", "user_id", "account_id"),
        Index("ix_transactions_user_id_category_id", "user_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(nullable=False)
    category_id: Mapped[int] = mapped_column(nullable=False)
    type: Mapped[FlowType] = mapped_column(
        enum_column(FlowType, "transaction_type"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="transactions")
    account: Mapped[Account] = relationship(
        back_populates="transactions",
        primaryjoin="Transaction.account_id == Account.id",
        foreign_keys=[account_id],
    )
    category: Mapped[Category] = relationship(
        back_populates="transactions",
        primaryjoin="Transaction.category_id == Category.id",
        foreign_keys=[category_id],
    )
