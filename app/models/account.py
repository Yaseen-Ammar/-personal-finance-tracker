from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .base import MONEY, AccountType, enum_column

if TYPE_CHECKING:
    from .transaction import Transaction
    from .user import User


class Account(db.Model):
    __tablename__ = "accounts"
    __table_args__ = (
        # An account name is unique per user, not globally.
        UniqueConstraint("user_id", "name", name="uq_accounts_user_id_name"),
        # Redundant with the PK, but required: child tables use
        # (user_id, id) as a composite FK target so MySQL itself can
        # guarantee a transaction and its account share the same owner.
        UniqueConstraint("user_id", "id", name="uq_accounts_user_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        enum_column(AccountType, "account_type"),
        nullable=False,
        default=AccountType.CHECKING,
    )
    # Balance is NOT stored: it is opening_balance + income - expenses
    # (+/- transfers), computed from transactions so it can never drift.
    opening_balance: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )
    # Archived accounts are hidden and read-only (no new/edited activity).
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account",
        primaryjoin="Account.id == Transaction.account_id",
        foreign_keys="Transaction.account_id",
    )
