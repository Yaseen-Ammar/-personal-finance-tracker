"""Shared service helpers: error types, ownership lookups, safe commits."""
import logging
from typing import TypeVar

from flask import abort
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

logger = logging.getLogger(__name__)

M = TypeVar("M")


class ServiceError(Exception):
    """A business-rule failure whose message is safe to show to the user."""


def get_owned_or_404(model: type[M], record_id: int, user_id: int) -> M:
    """Fetch a row only if it belongs to `user_id`; otherwise 404.

    404 (not 403) so the response never reveals that another user's record
    with that id exists.
    """
    obj = db.session.execute(
        select(model).where(model.id == record_id, model.user_id == user_id)
    ).scalar_one_or_none()
    if obj is None:
        abort(404)
    return obj


def commit(action: str) -> None:
    """Commit, or roll back and raise a user-safe ServiceError.

    Only the exception *class* is logged. SQLAlchemy's message embeds the SQL
    and bound parameters (descriptions, amounts), which must not reach logs.
    """
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error("Database error while %s (%s)", action, type(exc).__name__)
        raise ServiceError(
            "Something went wrong while saving your changes. Please try again."
        ) from exc
