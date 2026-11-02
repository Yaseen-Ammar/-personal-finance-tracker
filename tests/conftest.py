from datetime import date
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.models import Account, AccountType, Category, FlowType, Transaction, User


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ignores FOREIGN KEYs unless asked; MySQL/InnoDB always enforces them."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class IsolatedClient(FlaskClient):
    """Run every request in its own app context.

    The `app` fixture keeps an app context open so tests can use db.session
    directly. Without this, requests would reuse that context, sharing `g`
    (Flask-Login caches the current user there) and the SQLAlchemy session
    across requests, which real traffic never does.
    """

    def open(self, *args, **kwargs):
        with self.application.app_context():
            return super().open(*args, **kwargs)


@pytest.fixture
def app():
    app = create_app("testing")
    app.test_client_class = IsolatedClient
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_client(app):
    """Client with CSRF protection ON (the testing config disables it)."""
    app.config["WTF_CSRF_ENABLED"] = True
    return app.test_client()


# ---- data helpers -------------------------------------------------------

PASSWORD = "Sup3rSecret!"


def make_user(email="alice@example.com", name="Alice", password=PASSWORD) -> User:
    user = User(email=email, display_name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def make_account(user: User, name="Checking") -> Account:
    account = Account(
        user_id=user.id,
        name=name,
        account_type=AccountType.CHECKING,
        opening_balance=Decimal("100.00"),
    )
    db.session.add(account)
    db.session.commit()
    return account


def make_category(user: User, name="Groceries", type_=FlowType.EXPENSE) -> Category:
    category = Category(user_id=user.id, name=name, type=type_)
    db.session.add(category)
    db.session.commit()
    return category


def make_transaction(user, account, category, amount="12.50") -> Transaction:
    txn = Transaction(
        user_id=user.id,
        account_id=account.id,
        category_id=category.id,
        type=category.type,
        amount=Decimal(amount),
        transaction_date=date(2026, 6, 15),
        description="test",
    )
    db.session.add(txn)
    db.session.commit()
    return txn


@pytest.fixture
def user(app):
    return make_user()


@pytest.fixture
def other_user(app):
    return make_user(email="bob@example.com", name="Bob")


def login(client, email="alice@example.com", password=PASSWORD, **kwargs):
    return client.post(
        "/auth/login", data={"email": email, "password": password}, **kwargs
    )


# ---- Phase 3 helpers ------------------------------------------------------
from sqlalchemy import select  # noqa: E402

from app.services.account_service import create_account  # noqa: E402
from app.services.category_service import seed_default_categories  # noqa: E402
from app.services.transaction_service import (  # noqa: E402
    TransactionInput,
    create_transaction,
)
from app.services.transfer_service import TransferInput, create_transfer  # noqa: E402

JUNE = date(2026, 6, 15)


def seed(user: User) -> User:
    seed_default_categories(user.id)
    db.session.commit()
    return user


def category_of(user: User, name: str) -> Category:
    return db.session.execute(
        select(Category).where(Category.user_id == user.id, Category.name == name)
    ).scalar_one()


def add_account(user: User, name="Checking", opening="0.00", kind=AccountType.CHECKING):
    return create_account(user.id, name, kind, Decimal(opening))


def add_txn(user, account, category_name, amount, *, on=JUNE, desc=""):
    category = category_of(user, category_name)
    return create_transaction(
        user.id,
        TransactionInput(
            type=category.type,
            account_id=account.id,
            category_id=category.id,
            amount=Decimal(amount),
            transaction_date=on,
            description=desc,
        ),
    )


def add_transfer(user, source, target, amount, *, on=JUNE, desc=""):
    return create_transfer(
        user.id, TransferInput(source.id, target.id, Decimal(amount), on, desc)
    )


def balance_of(user, account) -> Decimal:
    from app.services.account_service import account_balances

    db.session.expire_all()
    return account_balances(user.id)[account.id]


def client_for(app, email, password=PASSWORD):
    client = app.test_client()
    login(client, email=email, password=password)
    return client


@pytest.fixture
def seeded_user(user):
    return seed(user)


@pytest.fixture
def seeded_other(other_user):
    return seed(other_user)


@pytest.fixture
def alice_client(app, seeded_user):
    return client_for(app, "alice@example.com")


@pytest.fixture
def bob_client(app, seeded_other):
    return client_for(app, "bob@example.com")
