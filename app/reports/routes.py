from flask import Response, flash, redirect, render_template, request, stream_with_context, url_for
from flask_login import current_user

from app.services.common import ServiceError
from app.services.report_service import (
    ReportFilters,
    build_report,
    csv_stream,
    default_filters,
    export_filename,
    summary_rows,
    transaction_rows,
    validate_filters,
)

from . import bp
from .forms import ReportFilterForm

FILTER_KEYS = ("date_from", "date_to", "account", "category")


def _filters_from_request() -> tuple[ReportFilterForm, ReportFilters, str | None]:
    """Parse and validate the filters; on any problem fall back to year-to-date.

    Returns (form, filters, error_message). Ownership of the chosen account /
    category is checked again here, in the service, not just by the form.
    """
    form = ReportFilterForm.for_user(current_user.id, request.args)
    form.validate()
    filters = form.to_filters()
    try:
        validate_filters(current_user.id, filters)
    except ServiceError as exc:
        return form, default_filters(), str(exc)
    return form, filters, None


def _query(filters: ReportFilters) -> dict:
    """Canonical query string for links, built from VALIDATED values only."""
    query = {"date_from": filters.date_from.isoformat(), "date_to": filters.date_to.isoformat()}
    if filters.account_id:
        query["account"] = filters.account_id
    if filters.category_id:
        query["category"] = filters.category_id
    return query


@bp.route("/")
def index():
    form, filters, error = _filters_from_request()
    if error:
        flash(error + " Showing year to date instead.", "warning")
    report = build_report(current_user.id, filters)
    form.show_effective(filters)
    return render_template(
        "reports/index.html", form=form, report=report, query=_query(filters)
    )


def _csv_response(kind: str, rows_factory) -> Response:
    form, filters, error = _filters_from_request()
    if error or form.errors:
        flash((error or "Please fix the report filters before exporting."), "warning")
        # Only the four known filter keys are passed on: url_for gives special
        # meaning to names like _external/_anchor, so never splat raw request.args.
        known = {k: request.args[k] for k in FILTER_KEYS if k in request.args}
        return redirect(url_for("reports.index", **known))
    rows = rows_factory(current_user.id, filters)
    response = Response(
        stream_with_context(csv_stream(rows)),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(kind, filters)}"'
        },
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@bp.route("/export/transactions.csv")
def export_transactions():
    return _csv_response("transactions", transaction_rows)


@bp.route("/export/summary.csv")
def export_summary():
    return _csv_response("monthly-summary", summary_rows)
