from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .base import FlowType, enum_column

if TYPE_CHECKING:
    from .budget import Budget
    from .transaction import Transaction
    from .user import User


class Category(db.Model):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "name", name="uq_categories_user_id_type_name"),
        UniqueConstraint("user_id", "id", name="uq_categories_user_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[FlowType] = mapped_column(
        enum_column(FlowType, "category_type"), nullable=False
    )
    # Default categories are seeded per user at sign-up; they can't be
    # renamed, retyped or deleted so reports stay consistent.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="categories")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="category",
        primaryjoin="Category.id == Transaction.category_id",
        foreign_keys="Transaction.category_id",
    )
    budgets: Mapped[list[Budget]] = relationship(
        back_populates="category",
        primaryjoin="Category.id == Budget.category_id",
        foreign_keys="Budget.category_id",
    )
