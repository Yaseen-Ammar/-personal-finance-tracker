import re

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    ValidationError,
)

from app.services.auth_service import email_exists

PASSWORD_MIN = 8
PASSWORD_MAX = 128  # cap input so huge passwords can't be used to burn CPU in scrypt


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _strip_lower(value):
    return value.strip().lower() if isinstance(value, str) else value


def password_strength(_form, field):
    password = field.data or ""
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValidationError("Password must contain at least one letter and one number.")


class RegistrationForm(FlaskForm):
    display_name = StringField(
        "Your name",
        filters=[_strip],
        validators=[DataRequired(), Length(min=2, max=80)],
    )
    email = StringField(
        "Email",
        filters=[_strip_lower],
        validators=[DataRequired(), Email(check_deliverability=False), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=PASSWORD_MIN, max=PASSWORD_MAX),
            password_strength,
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_email(self, field):
        if email_exists(field.data):
            raise ValidationError("An account with this email already exists.")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        filters=[_strip_lower],
        validators=[DataRequired(), Length(max=255)],
    )
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(max=PASSWORD_MAX)]
    )
    submit = SubmitField("Sign in")
