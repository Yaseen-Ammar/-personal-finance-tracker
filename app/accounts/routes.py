from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.models import Account, AccountType
from app.services.account_service import (
    archive_account,
    create_account,
    restore_account,
    summarize_accounts,
    update_account,
)
from app.services.common import ServiceError, get_owned_or_404

from . import bp
from .forms import AccountForm


@bp.route("/")
def index():
    show_archived = request.args.get("archived") == "1"
    summaries, total = summarize_accounts(current_user.id, include_archived=show_archived)
    return render_template(
        "accounts/index.html", summaries=summaries, total=total, show_archived=show_archived
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    form = AccountForm()
    if form.validate_on_submit():
        try:
            create_account(
                current_user.id,
                form.name.data,
                AccountType(form.account_type.data),
                form.opening_balance.data,
            )
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Account created.", "success")
            return redirect(url_for("accounts.index"))
    return render_template("accounts/form.html", form=form, account=None)


@bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
def edit(account_id: int):
    account = get_owned_or_404(Account, account_id, current_user.id)
    if account.is_archived:
        flash("Restore this account before editing it.", "warning")
        return redirect(url_for("accounts.index", archived=1))

    form = AccountForm(
        data={
            "name": account.name,
            "account_type": account.account_type.value,
            "opening_balance": account.opening_balance,
        }
    )
    if form.validate_on_submit():
        try:
            update_account(
                current_user.id,
                account.id,
                form.name.data,
                AccountType(form.account_type.data),
                form.opening_balance.data,
            )
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Account updated.", "success")
            return redirect(url_for("accounts.index"))
    return render_template("accounts/form.html", form=form, account=account)


@bp.route("/<int:account_id>/archive", methods=["POST"])
def archive(account_id: int):
    try:
        archive_account(current_user.id, account_id)
    except ServiceError as exc:
        flash(str(exc), "danger")
    else:
        flash("Account archived.", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/restore", methods=["POST"])
def restore(account_id: int):
    restore_account(current_user.id, account_id)
    flash("Account restored.", "success")
    return redirect(url_for("accounts.index"))
