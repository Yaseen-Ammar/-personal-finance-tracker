from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

if TYPE_CHECKING:
    from .account import Account
    from .budget import Budget
    from .category import Category
    from .transaction import Transaction
    from .transfer import Transfer


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # NOTE: deleting a user that owns transactions fails on MySQL (error 1451):
    # transactions -> accounts/categories is ON DELETE RESTRICT on purpose, and
    # InnoDB checks it before the user-level cascade reaches the transactions.
    # Account/user deletion must go through a service that deletes children in
    # order (transactions, budgets, categories, accounts, then the user).
    # passive_deletes leaves child cleanup to the database instead of loading
    # every child row into memory.
    accounts: Mapped[list[Account]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    budgets: Mapped[list[Budget]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    transfers: Mapped[list[Transfer]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return value.strip().lower()

    def set_password(self, password: str) -> None:
        # Salted per-password; method comes from config (scrypt by default).
        method = current_app.config.get("PASSWORD_HASH_METHOD", "scrypt")
        self.password_hash = generate_password_hash(password, method=method)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:  # never include the hash
        return f"<User id={self.id} email={self.email!r}>"
