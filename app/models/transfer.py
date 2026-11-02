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

from .base import MONEY

if TYPE_CHECKING:
    from .account import Account
    from .user import User


class Transfer(db.Model):
    """Money moved between two of a user's own accounts.

    ONE row represents both legs: it subtracts from `from_account` and adds to
    `to_account` when balances are computed. Because there is a single row,
    a transfer can never be half-applied, and it is never counted as income
    or expense (it lives outside the `transactions` table entirely).
    """

    __tablename__ = "transfers"
    __table_args__ = (
        # Both accounts must belong to the same user as the transfer, so a
        # cross-user transfer is impossible at the database level.
        ForeignKeyConstraint(
            ["user_id", "from_account_id"],
            ["accounts.user_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_transfers_from_account_owner",
        ),
        ForeignKeyConstraint(
            ["user_id", "to_account_id"],
            ["accounts.user_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_transfers_to_account_owner",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("from_account_id <> to_account_id", name="different_accounts"),
        Index("ix_transfers_user_id_transfer_date", "user_id", "transfer_date"),
        Index("ix_transfers_user_id_from_account_id", "user_id", "from_account_id"),
        Index("ix_transfers_user_id_to_account_id", "user_id", "to_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    from_account_id: Mapped[int] = mapped_column(nullable=False)
    to_account_id: Mapped[int] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="transfers")
    from_account: Mapped[Account] = relationship(
        primaryjoin="Transfer.from_account_id == Account.id",
        foreign_keys=[from_account_id],
    )
    to_account: Mapped[Account] = relationship(
        primaryjoin="Transfer.to_account_id == Account.id",
        foreign_keys=[to_account_id],
    )
