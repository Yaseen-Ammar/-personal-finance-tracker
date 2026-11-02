"""Turn analytics results into JSON-safe chart payloads.

Amounts are sent as 2-dp *strings* (exact Decimal text); the browser converts
them to numbers only to draw the chart. All real arithmetic happened earlier,
in Decimal, on the server.
"""
from flask import current_app

from .analytics_service import CategorySpend, Dashboard, MonthTotals, YearAnalytics, group_small_categories


def _money(value) -> str:
    return format(value, "f")


def currency_info() -> dict:
    return {
        "code": current_app.config["CURRENCY_CODE"],
        "locale": current_app.config["CURRENCY_LOCALE"].replace("_", "-"),
    }


def _income_expense(months: list[MonthTotals], label_format: str = "short") -> dict:
    labels = [m.month.short_label if label_format == "short" else m.month.label for m in months]
    return {
        "labels": labels,
        "income": [_money(m.income) for m in months],
        "expenses": [_money(m.expenses) for m in months],
        "net": [_money(m.net) for m in months],
    }


def _categories(items: list[CategorySpend]) -> dict:
    return {
        "labels": [c.name for c in items],
        "values": [_money(c.total) for c in items],
        "shares": [_money(c.share) for c in items],
    }


def dashboard_charts(data: Dashboard) -> dict:
    return {
        "currency": currency_info(),
        "incomeExpense": _income_expense(data.trend),
        "category": _categories(group_small_categories(data.spending)),
    }


def analytics_charts(analytics: YearAnalytics) -> dict:
    months = [row.totals for row in analytics.rows]
    payload = {
        "currency": currency_info(),
        "incomeExpense": _income_expense(months),
        "category": _categories(group_small_categories(analytics.spending)),
    }
    flow = payload["incomeExpense"]
    # Months that haven't happened yet become null, which the line chart draws
    # as a gap instead of a misleading drop to zero.
    flow["net"] = [None if row.pending else _money(row.totals.net) for row in analytics.rows]
    flow["cumulative"] = [None if row.pending else _money(row.cumulative_net) for row in analytics.rows]
    return payload
