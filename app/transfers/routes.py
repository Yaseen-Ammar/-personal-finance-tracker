from datetime import date

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.services.account_service import list_accounts
from app.services.common import ServiceError
from app.services.transfer_service import create_transfer, delete_transfer, list_transfers

from . import bp
from .forms import TransferForm

PER_PAGE = 15


@bp.route("/")
def index():
    page = request.args.get("page", 1, type=int) or 1
    pagination = list_transfers(current_user.id, page=page, per_page=PER_PAGE)
    return render_template("transfers/index.html", pagination=pagination)


@bp.route("/new", methods=["GET", "POST"])
def new():
    accounts = list_accounts(current_user.id)
    if len(accounts) < 2:
        flash("You need at least two active accounts to make a transfer.", "info")
        return redirect(url_for("accounts.index"))

    # Preselect two DIFFERENT accounts so the default form is already valid.
    form = TransferForm.for_user(
        current_user.id,
        data={
            "transfer_date": date.today(),
            "from_account_id": accounts[0].id,
            "to_account_id": accounts[1].id,
        },
    )
    if form.validate_on_submit():
        try:
            create_transfer(current_user.id, form.to_input())
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Transfer recorded.", "success")
            return redirect(url_for("transfers.index"))
    return render_template("transfers/form.html", form=form)


@bp.route("/<int:transfer_id>/delete", methods=["POST"])
def delete(transfer_id: int):
    try:
        delete_transfer(current_user.id, transfer_id)
    except ServiceError as exc:
        flash(str(exc), "danger")
    else:
        flash("Transfer deleted.", "success")
    return redirect(url_for("transfers.index"))
