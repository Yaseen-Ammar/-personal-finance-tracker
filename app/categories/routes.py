from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.models import Category, FlowType
from app.services.category_service import (
    create_category,
    delete_category,
    list_categories,
    update_category,
)
from app.services.common import ServiceError, get_owned_or_404

from . import bp
from .forms import CategoryForm


@bp.route("/")
def index():
    rows = list_categories(current_user.id)
    return render_template(
        "categories/index.html",
        income=[r for r in rows if r.category.type is FlowType.INCOME],
        expense=[r for r in rows if r.category.type is FlowType.EXPENSE],
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    form = CategoryForm()
    if request.method == "GET" and request.args.get("type") in ("income", "expense"):
        form.type.data = request.args["type"]
    if form.validate_on_submit():
        try:
            create_category(current_user.id, form.name.data, FlowType(form.type.data))
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Category created.", "success")
            return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, category=None)


@bp.route("/<int:category_id>/edit", methods=["GET", "POST"])
def edit(category_id: int):
    category = get_owned_or_404(Category, category_id, current_user.id)
    if category.is_default:
        flash("Default categories can't be edited.", "warning")
        return redirect(url_for("categories.index"))

    form = CategoryForm(data={"name": category.name, "type": category.type.value})
    if form.validate_on_submit():
        try:
            update_category(
                current_user.id, category.id, form.name.data, FlowType(form.type.data)
            )
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Category updated.", "success")
            return redirect(url_for("categories.index"))
    return render_template("categories/form.html", form=form, category=category)


@bp.route("/<int:category_id>/delete", methods=["POST"])
def delete(category_id: int):
    try:
        delete_category(current_user.id, category_id)
    except ServiceError as exc:
        flash(str(exc), "danger")
    else:
        flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))
