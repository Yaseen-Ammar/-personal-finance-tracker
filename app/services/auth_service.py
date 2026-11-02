"""Authentication business logic. Route handlers stay thin and call these."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User

from .category_service import seed_default_categories


class EmailAlreadyRegistered(Exception):
    """Raised when registering an email that already has an account."""


# Verified against when the email is unknown, so "no such user" costs the
# same time as "wrong password" and response timing doesn't reveal which
# emails are registered.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def normalise_email(email: str) -> str:
    return email.strip().lower()


def email_exists(email: str) -> bool:
    stmt = select(User.id).where(User.email == normalise_email(email))
    return db.session.execute(stmt).first() is not None


def register_user(email: str, display_name: str, password: str) -> User:
    if email_exists(email):
        raise EmailAlreadyRegistered(email)

    user = User(email=email, display_name=display_name.strip())
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.flush()  # assigns user.id
        seed_default_categories(user.id)  # same transaction: all-or-nothing sign-up
        db.session.commit()
    except IntegrityError as exc:
        # Two simultaneous sign-ups can both pass the check above; the
        # UNIQUE index is the real guarantee.
        db.session.rollback()
        raise EmailAlreadyRegistered(email) from exc
    return user


def authenticate(email: str, password: str) -> User | None:
    """Return the user if credentials are valid, otherwise None."""
    user = db.session.execute(
        select(User).where(User.email == normalise_email(email))
    ).scalar_one_or_none()
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return None
    return user if user.check_password(password) else None
