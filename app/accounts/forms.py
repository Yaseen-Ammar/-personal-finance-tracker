from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, InputRequired, Length

from app.forms_common import amount_validator, choices, strip_text
from app.models import AccountType

ACCOUNT_TYPE_CHOICES = choices(
    (t.value, t.value.replace("_", " ").title()) for t in AccountType
)


class AccountForm(FlaskForm):
    name = StringField(
        "Account name",
        filters=[strip_text],
        validators=[DataRequired(), Length(max=100)],
    )
    account_type = SelectField("Type", choices=ACCOUNT_TYPE_CHOICES)
    opening_balance = DecimalField(
        "Opening balance",
        places=2,
        default=Decimal("0.00"),
        validators=[
            InputRequired(),
            amount_validator(allow_negative=True, label="Opening balance"),
        ],
        render_kw={"inputmode": "decimal"},
    )
    submit = SubmitField("Save account")
