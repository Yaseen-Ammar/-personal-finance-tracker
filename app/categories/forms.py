from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

from app.forms_common import choices, strip_text


class CategoryForm(FlaskForm):
    name = StringField(
        "Category name",
        filters=[strip_text],
        validators=[DataRequired(), Length(max=80)],
    )
    type = SelectField(
        "Type", choices=choices([("expense", "Expense"), ("income", "Income")])
    )
    submit = SubmitField("Save category")
