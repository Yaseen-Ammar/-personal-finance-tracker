from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, InputRequired, Length, Optional, ValidationError

from app.forms_common import amount_validator, choices, date_validator, strip_text
from app.services.account_service import list_accounts
from app.services.transfer_service import TransferInput


class TransferForm(FlaskForm):
    from_account_id = SelectField("From account", coerce=int, validators=[DataRequired()])
    to_account_id = SelectField("To account", coerce=int, validators=[DataRequired()])
    amount = DecimalField(
        "Amount",
        places=2,
        validators=[InputRequired(), amount_validator(label="Transfer amount")],
        render_kw={"inputmode": "decimal"},
    )
    transfer_date = DateField("Date", validators=[DataRequired(), date_validator()])
    description = StringField(
        "Note", filters=[strip_text], validators=[Optional(), Length(max=255)]
    )
    submit = SubmitField("Transfer")

    @classmethod
    def for_user(cls, user_id: int, **kwargs) -> "TransferForm":
        form = cls(**kwargs)
        options = choices((a.id, a.name) for a in list_accounts(user_id))
        form.from_account_id.choices = options
        form.to_account_id.choices = options
        return form

    def validate_to_account_id(self, field):
        if field.data == self.from_account_id.data:
            raise ValidationError("Choose two different accounts.")

    def to_input(self) -> TransferInput:
        return TransferInput(
            from_account_id=self.from_account_id.data,
            to_account_id=self.to_account_id.data,
            amount=self.amount.data,
            transfer_date=self.transfer_date.data,
            description=self.description.data or "",
        )
