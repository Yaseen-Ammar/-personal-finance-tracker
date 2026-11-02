from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, SelectField, StringField, SubmitField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, InputRequired, Length, Optional, ValidationError

from app.forms_common import amount_validator, choices, date_validator, strip_text
from app.models import FlowType
from app.services.account_service import list_accounts
from app.services.category_service import list_categories
from app.services.transaction_service import (
    DEFAULT_SORT,
    SEARCH_MAX,
    SORTS,
    TransactionFilters,
    TransactionInput,
)

TYPE_CHOICES = choices([("expense", "Expense"), ("income", "Income")])
SORT_LABELS = {
    "date_desc": "Newest first",
    "date_asc": "Oldest first",
    "amount_desc": "Amount: high to low",
    "amount_asc": "Amount: low to high",
}


class TransactionForm(FlaskForm):
    type = SelectField("Type", choices=TYPE_CHOICES, validators=[DataRequired()])
    account_id = SelectField("Account", coerce=int, validators=[DataRequired()])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    amount = DecimalField(
        "Amount",
        places=2,
        validators=[InputRequired(), amount_validator()],
        render_kw={"inputmode": "decimal"},
    )
    transaction_date = DateField("Date", validators=[DataRequired(), date_validator()])
    description = StringField(
        "Description", filters=[strip_text], validators=[Optional(), Length(max=255)]
    )
    submit = SubmitField("Save transaction")

    @classmethod
    def for_user(cls, user_id: int, **kwargs) -> "TransactionForm":
        """Build the form with choices limited to the user's OWN records.

        A submitted id outside these choices fails WTForms' "Not a valid
        choice" check, so another user's account/category is rejected before
        the service layer even runs (which then re-checks ownership itself).
        """
        form = cls(**kwargs)
        form.account_id.choices = choices((a.id, a.name) for a in list_accounts(user_id))
        # data-type lets the page script show only categories matching the type.
        form.category_id.choices = [
            SelectChoice(
                value=str(r.category.id),
                label=r.category.name,
                render_kw={"data-type": r.category.type.value},
            )
            for r in list_categories(user_id)
        ]
        return form

    def to_input(self) -> TransactionInput:
        return TransactionInput(
            type=FlowType(self.type.data),
            account_id=self.account_id.data,
            category_id=self.category_id.data,
            amount=self.amount.data,
            transaction_date=self.transaction_date.data,
            description=self.description.data or "",
        )


class TransactionFilterForm(FlaskForm):
    """GET-based filter bar: no CSRF (it changes nothing), validated anyway."""

    class Meta:
        csrf = False

    q = StringField(
        "Search", filters=[strip_text], validators=[Optional(), Length(max=SEARCH_MAX)]
    )
    type = SelectField(
        "Type",
        default="",
        choices=choices([("", "All types"), ("income", "Income"), ("expense", "Expense")]),
        validators=[Optional()],
    )
    category = SelectField("Category", coerce=int, default=0, validators=[Optional()])
    account = SelectField("Account", coerce=int, default=0, validators=[Optional()])
    date_from = DateField("From", validators=[Optional()])
    date_to = DateField("To", validators=[Optional()])
    sort = SelectField(
        "Sort",
        default=DEFAULT_SORT,
        choices=choices((key, SORT_LABELS[key]) for key in SORTS),
    )

    @classmethod
    def for_user(cls, user_id: int, formdata) -> "TransactionFilterForm":
        form = cls(formdata=formdata)
        form.account.choices = choices(
            [(0, "All accounts")]
            + [(a.id, a.name) for a in list_accounts(user_id, include_archived=True)]
        )
        form.category.choices = choices(
            [(0, "All categories")]
            + [(r.category.id, r.category.name) for r in list_categories(user_id)]
        )
        return form

    def validate_date_to(self, field):
        if field.data and self.date_from.data and field.data < self.date_from.data:
            raise ValidationError("'To' date must not be before 'From' date.")

    def to_filters(self) -> TransactionFilters:
        """Only fields that validated are applied; bad ones are ignored."""

        def ok(field):
            return None if field.errors else field.data

        return TransactionFilters(
            q=ok(self.q) or "",
            type=FlowType(ok(self.type)) if ok(self.type) else None,
            category_id=ok(self.category) or None,
            account_id=ok(self.account) or None,
            date_from=ok(self.date_from),
            date_to=ok(self.date_to),
            sort=ok(self.sort) or DEFAULT_SORT,
        )
