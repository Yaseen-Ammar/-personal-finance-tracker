from datetime import date

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth.utils import is_safe_redirect
from app.models import Transaction
from app.services.account_service import list_accounts
from app.services.common import ServiceError, get_owned_or_404
from app.services.transaction_service import (
    create_transaction,
    delete_transaction,
    search_transactions,
    update_transaction,
)

from . import bp
from .forms import TransactionFilterForm, TransactionForm

PER_PAGE = 15


@bp.route("/")
def index():
    form = TransactionFilterForm.for_user(current_user.id, request.args)
    form.validate()  # surfaces bad filter input; invalid fields are ignored
    page = request.args.get("page", 1, type=int) or 1
    pagination = search_transactions(
        current_user.id, form.to_filters(), page=page, per_page=PER_PAGE
    )
    return render_template("transactions/index.html", form=form, pagination=pagination)


def _require_account_or_redirect():
    if not list_accounts(current_user.id):
        flash("Create an account first, then you can record transactions.", "info")
        return redirect(url_for("accounts.new"))
    return None


@bp.route("/new", methods=["GET", "POST"])
def new():
    if (redirect_response := _require_account_or_redirect()) is not None:
        return redirect_response

    initial_type = request.args.get("type")
    form = TransactionForm.for_user(
        current_user.id,
        data={
            "type": initial_type if initial_type in ("income", "expense") else "expense",
            "transaction_date": date.today(),
        },
    )
    if form.validate_on_submit():
        try:
            create_transaction(current_user.id, form.to_input())
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Transaction added.", "success")
            return redirect(url_for("transactions.index"))
    return render_template("transactions/form.html", form=form, transaction=None)


@bp.route("/<int:txn_id>/edit", methods=["GET", "POST"])
def edit(txn_id: int):
    txn = get_owned_or_404(Transaction, txn_id, current_user.id)
    if txn.account.is_archived:
        flash(f"'{txn.account.name}' is archived. Restore it to change its transactions.", "warning")
        return redirect(url_for("transactions.index"))

    form = TransactionForm.for_user(
        current_user.id,
        data={
            "type": txn.type.value,
            "account_id": txn.account_id,
            "category_id": txn.category_id,
            "amount": txn.amount,
            "transaction_date": txn.transaction_date,
            "description": txn.description,
        },
    )
    if form.validate_on_submit():
        try:
            update_transaction(current_user.id, txn.id, form.to_input())
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Transaction updated.", "success")
            return redirect(url_for("transactions.index"))
    return render_template("transactions/form.html", form=form, transaction=txn)


@bp.route("/<int:txn_id>/delete", methods=["POST"])
def delete(txn_id: int):
    try:
        delete_transaction(current_user.id, txn_id)
    except ServiceError as exc:
        flash(str(exc), "danger")
    else:
        flash("Transaction deleted.", "success")
    # Return to the same filtered/paged list, but only to a same-site path.
    back = request.form.get("next")
    return redirect(back if is_safe_redirect(back) else url_for("transactions.index"))
