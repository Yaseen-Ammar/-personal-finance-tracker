"""Form helpers shared by the feature blueprints."""
from flask import Blueprint
from flask_login import login_required
from wtforms.fields import SelectChoice
from wtforms.validators import ValidationError

from app.services.common import ServiceError
from app.services.validation import validate_amount, validate_date


def protected_blueprint(name: str, import_name: str, **kwargs) -> Blueprint:
    """A blueprint whose every route requires login.

    Enforced once in before_request, so a new route can't be added to the
    blueprint without authentication by forgetting a decorator.
    """
    bp = Blueprint(name, import_name, **kwargs)

    @bp.before_request
    @login_required
    def _require_login():
        return None

    return bp


def choices(pairs) -> list[SelectChoice]:
    """[(value, label), ...] -> SelectChoice list (tuples are deprecated in WTForms 3.3)."""
    return [SelectChoice(value=str(value), label=label) for value, label in pairs]


def strip_text(value):
    return value.strip() if isinstance(value, str) else value


def amount_validator(*, allow_negative: bool = False, label: str = "Amount"):
    def _validate(_form, field):
        if field.data is None:  # unparseable input already has its own error
            return
        try:
            validate_amount(field.data, field=label, allow_negative=allow_negative)
        except ServiceError as exc:
            raise ValidationError(str(exc)) from None

    return _validate


def date_validator(label: str = "Date"):
    def _validate(_form, field):
        if field.data is None:
            return
        try:
            validate_date(field.data, field=label)
        except ServiceError as exc:
            raise ValidationError(str(exc)) from None

    return _validate
