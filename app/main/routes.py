from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services.account_service import summarize_accounts
from app.services.analytics_service import build_dashboard, year_choices
from app.services.chart_data import dashboard_charts
from app.services.periods import parse_month

from . import bp


@bp.route("/")
def index():
    target = "main.dashboard" if current_user.is_authenticated else "auth.login"
    return redirect(url_for(target))


@bp.route("/dashboard")
@login_required
def dashboard():
    month, valid = parse_month(request.args.get("year"), request.args.get("month"))
    if not valid:
        flash("That month isn't valid, so the current month is shown.", "warning")

    accounts, total_balance = summarize_accounts(current_user.id)  # active accounts only
    data = build_dashboard(current_user.id, month)
    return render_template(
        "main/dashboard.html",
        data=data,
        accounts=accounts,
        total_balance=total_balance,
        years=year_choices(current_user.id),
        charts=dashboard_charts(data),
    )
