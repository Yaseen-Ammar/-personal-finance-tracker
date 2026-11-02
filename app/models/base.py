"""Shared column types and enums for the models."""
import enum

from sqlalchemy import Enum, Numeric

# Money is always DECIMAL(14, 2): up to 999,999,999,999.99, exact arithmetic.
# Never Float - binary floats cannot represent 0.10 exactly.
MONEY = Numeric(precision=14, scale=2)


class FlowType(str, enum.Enum):
    """Direction of money for categories and transactions."""

    INCOME = "income"
    EXPENSE = "expense"


class AccountType(str, enum.Enum):
    CASH = "cash"
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    OTHER = "other"


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Portable enum: stored as VARCHAR + CHECK constraint.

    Native MySQL ENUMs need an ALTER TABLE to add a value; VARCHAR+CHECK
    is easier to migrate and behaves the same in SQLite for tests.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )
