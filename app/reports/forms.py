from flask_wtf import FlaskForm
from wtforms import DateField, SelectField
from wtforms.validators import Optional, ValidationError

from app.forms_common import choices, date_validator
from app.services.account_service import list_accounts
from app.services.category_service import list_categories
from app.services.report_service import ReportFilters, default_filters


class ReportFilterForm(FlaskForm):
    """GET filter form: no CSRF (it changes nothing), validated like any input."""

    class Meta:
        csrf = False

    date_from = DateField("From", validators=[Optional(), date_validator("'From' date")])
    date_to = DateField("To", validators=[Optional(), date_validator("'To' date")])
    account = SelectField("Account", coerce=int, default=0, validators=[Optional()])
    category = SelectField("Category", coerce=int, default=0, validators=[Optional()])

    @classmethod
    def for_user(cls, user_id: int, formdata) -> "ReportFilterForm":
        form = cls(formdata=formdata)
        # Archived accounts stay selectable: their history is part of the reports.
        form.account.choices = choices(
            [(0, "All accounts")]
            + [
                (a.id, a.name + (" (archived)" if a.is_archived else ""))
                for a in list_accounts(user_id, include_archived=True)
            ]
        )
        form.category.choices = choices(
            [(0, "All categories")]
            + [(r.category.id, r.category.name) for r in list_categories(user_id)]
        )
        return form

    def validate_date_to(self, field):
        if field.data and self.date_from.data and field.data < self.date_from.data:
            raise ValidationError("'To' date must not be before 'From' date.")

    def show_effective(self, filters: ReportFilters) -> None:
        """Fill blank date boxes with the range actually applied (the default).

        Otherwise the page reports on, say, "year to date" while both date
        inputs look empty. Boxes the user typed into (even wrongly) are left alone.
        """
        for field, value in ((self.date_from, filters.date_from), (self.date_to, filters.date_to)):
            if not field.errors and not (field.raw_data and field.raw_data[0]):
                field.raw_data = None  # make the widget render `data`, not the blank submission
                field.data = value

    def to_filters(self) -> ReportFilters:
        """Blank or invalid fields fall back to the defaults (year to date)."""
        fallback = default_filters()

        def ok(field):
            return None if field.errors else field.data

        return ReportFilters(
            date_from=ok(self.date_from) or fallback.date_from,
            date_to=ok(self.date_to) or fallback.date_to,
            account_id=ok(self.account) or None,
            category_id=ok(self.category) or None,
        )
