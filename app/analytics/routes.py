from flask import flash, render_template, request
from flask_login import current_user

from app.services.analytics_service import build_year_analytics, year_choices
from app.services.chart_data import analytics_charts
from app.services.periods import parse_year

from . import bp


@bp.route("/")
def index():
    year, valid = parse_year(request.args.get("year"))
    if not valid:
        flash("That year isn't valid, so the current year is shown.", "warning")
    analytics = build_year_analytics(current_user.id, year)
    return render_template(
        "analytics/index.html",
        analytics=analytics,
        years=year_choices(current_user.id),
        charts=analytics_charts(analytics),
    )
