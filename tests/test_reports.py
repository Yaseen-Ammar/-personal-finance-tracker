import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from app.models import FlowType
from app.services.account_service import archive_account
from app.services.category_service import create_category
from app.services.report_service import (
    MAX_RANGE_DAYS,
    ReportFilters,
    build_report,
    csv_stream,
    plain_amount,
    safe_cell,
)

from .conftest import add_account, add_transfer, add_txn, category_of

D = Decimal


def rows_of(response):
    """Decode a CSV response and return its rows as lists."""
    assert response.mimetype == "text/csv"
    raw = response.get_data()
    assert raw.startswith(b"\xef\xbb\xbf"), "missing UTF-8 BOM (Excel would garble accents)"
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


@pytest.fixture
def data(seeded_user):
    main = add_account(seeded_user, "Main", opening="0.00")
    card = add_account(seeded_user, "Card", opening="0.00")
    add_txn(seeded_user, main, "Salary", "3000.00", on=date(2026, 1, 5), desc="Jan pay")
    add_txn(seeded_user, main, "Groceries", "100.00", on=date(2026, 1, 20), desc="Jan shop")
    add_txn(seeded_user, card, "Dining Out", "40.00", on=date(2026, 2, 14), desc="Valentine, dinner")
    add_txn(seeded_user, main, "Groceries", "60.00", on=date(2026, 3, 1), desc="Mar shop")
    add_txn(seeded_user, main, "Freelance", "500.00", on=date(2026, 3, 31), desc="Mar gig")
    add_txn(seeded_user, main, "Groceries", "999.00", on=date(2026, 4, 1), desc="April, outside")
    return main, card


Q = "date_from=2026-01-01&date_to=2026-03-31"


# ---- Report page --------------------------------------------------------------------------------------------
def test_report_totals_for_the_range(alice_client, data):
    html = alice_client.get(f"/reports/?{Q}").get_data(as_text=True)
    assert "01 Jan 2026 to 31 Mar 2026" in html
    assert "$3,500.00" in html and "$200.00" in html and "$3,300.00" in html
    assert "94.3% of income saved" in html                 # 3300 / 3500
    assert "999.00" not in html


def test_date_range_is_inclusive_on_both_ends(seeded_user, data):
    r = build_report(seeded_user.id, ReportFilters(date(2026, 1, 5), date(2026, 3, 1)))
    assert (r.totals.income, r.totals.expenses, r.totals.count) == (D("3000.00"), D("200.00"), 4)
    one_day = build_report(seeded_user.id, ReportFilters(date(2026, 3, 31), date(2026, 3, 31)))
    assert one_day.totals.income == D("500.00") and one_day.totals.count == 1


def test_account_filter(alice_client, seeded_user, data):
    html = alice_client.get(f"/reports/?{Q}&account={data[1].id}").get_data(as_text=True)
    assert "$40.00" in html and "$3,500.00" not in html
    # (The filter dropdown always lists every category, so check the results section.)
    expenses = html.split('id="r-cat-1"')[1].split("</section>")[0]
    assert "Dining Out" in expenses and "Groceries" not in expenses


def test_category_filter(alice_client, seeded_user, data):
    html = alice_client.get(f"/reports/?{Q}&category={category_of(seeded_user, 'Groceries').id}").get_data(as_text=True)
    assert "$160.00" in html and "$3,000.00" not in html


def test_combined_account_and_category_filter(seeded_user, data):
    scope = ReportFilters(date(2026, 1, 1), date(2026, 12, 31), data[0].id, category_of(seeded_user, "Groceries").id)
    assert build_report(seeded_user.id, scope).totals.expenses == D("1159.00")


def test_monthly_summary_has_a_row_per_month_even_when_empty(seeded_user, data):
    months = build_report(seeded_user.id, ReportFilters(date(2026, 1, 1), date(2026, 5, 31))).months
    assert [m.month.param for m in months] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
    assert [(m.income, m.expenses) for m in months][1] == (D("0.00"), D("40.00"))
    assert (months[4].income, months[4].expenses) == (D("0.00"), D("0.00"))


def test_category_breakdown_tables(alice_client, data):
    html = alice_client.get(f"/reports/?{Q}").get_data(as_text=True)
    expenses = html.split('id="r-cat-1"')[1].split("</section>")[0]
    income = html.split('id="r-cat-2"')[1].split("</section>")[0]
    assert expenses.index("Groceries") < expenses.index("Dining Out") and "80.0%" in expenses and "20.0%" in expenses
    assert "Salary" in income and "Freelance" in income


def test_default_range_is_year_to_date(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    today = date.today()
    add_txn(seeded_user, acct, "Salary", "10.00", on=today)
    html = alice_client.get("/reports/").get_data(as_text=True)
    assert f"01 Jan {today.year} to {today.strftime('%d %b %Y')}" in html and "$10.00" in html


def test_date_boxes_show_the_range_that_is_actually_applied(alice_client, seeded_user):
    """Found in the browser: the page said year-to-date while both date inputs looked empty."""
    html = alice_client.get("/reports/").get_data(as_text=True)
    today = date.today()
    assert f'value="{today.year}-01-01"' in html and f'value="{today.isoformat()}"' in html
    typed = alice_client.get("/reports/?date_from=2026-02-01&date_to=2026-02-28").get_data(as_text=True)
    assert 'value="2026-02-01"' in typed and 'value="2026-02-28"' in typed
    half = alice_client.get("/reports/?date_from=2026-02-01").get_data(as_text=True)
    assert 'value="2026-02-01"' in half and f'value="{today.isoformat()}"' in half
    bad = alice_client.get("/reports/?date_from=garbage").get_data(as_text=True)
    assert "Not a valid date value" in bad and "aria-invalid" in bad


def test_hostile_filter_values_are_escaped_when_echoed_back(alice_client):
    payload = '"><script>alert(1)</script>'
    html = alice_client.get("/reports/", query_string={"date_from": payload, "date_to": payload}).get_data(as_text=True)
    assert "<script>alert(1)" not in html and "&#34;&gt;&lt;script&gt;" in html


def test_empty_report_shows_a_helpful_state(alice_client, seeded_user):
    html = alice_client.get("/reports/?date_from=2020-01-01&date_to=2020-12-31").get_data(as_text=True)
    assert "Nothing matches these filters" in html and "$0.00" in html


def test_transfers_are_excluded_from_reports(seeded_user, data):
    add_transfer(seeded_user, data[0], data[1], "777.00", on=date(2026, 2, 2))
    r = build_report(seeded_user.id, ReportFilters(date(2026, 1, 1), date(2026, 3, 31)))
    assert (r.totals.income, r.totals.expenses, r.totals.count) == (D("3500.00"), D("200.00"), 5)


def test_archived_accounts_stay_in_reports_and_filter(alice_client, seeded_user):
    old = add_account(seeded_user, "OldAcct")
    add_txn(seeded_user, old, "Salary", "50.00", on=date(2026, 2, 1))
    add_txn(seeded_user, old, "Groceries", "50.00", on=date(2026, 2, 2))
    archive_account(seeded_user.id, old.id)
    html = alice_client.get(f"/reports/?{Q}&account={old.id}").get_data(as_text=True)
    assert "OldAcct (archived)" in html and "$50.00" in html


# ---- Invalid input ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    ["date_from=garbage", "date_to=2026-13-45", "category=abc", "account=-1", "account=99999", "category=99999",
     "date_from=2026-05-01&date_to=2026-01-01", "date_from=1900-01-01", "date_to=2999-01-01",
     "date_from=2000-01-01&date_to=2027-01-01", "account=" + "9" * 400, "date_from=%00", "category=1;DROP TABLE users"],
)
def test_bad_filters_never_cause_an_error(alice_client, data, query):
    assert alice_client.get("/reports/?" + query).status_code == 200


def test_reversed_dates_show_an_inline_error(alice_client, data):
    html = alice_client.get("/reports/?date_from=2026-05-01&date_to=2026-01-01").get_data(as_text=True)
    assert "must not be before" in html and "aria-invalid" in html


def test_range_over_ten_years_is_refused_with_a_message(alice_client, data):
    html = alice_client.get("/reports/?date_from=2000-01-01&date_to=2027-01-01").get_data(as_text=True)
    assert "10 years or less" in html and "year to date" in html.lower()
    assert (date(2027, 1, 1) - date(2000, 1, 1)).days > MAX_RANGE_DAYS


# ---- Cross-user isolation ---------------------------------------------------------------------------------------------------
def test_another_users_account_or_category_id_is_rejected(bob_client, seeded_user, seeded_other, data):
    their_cat = category_of(seeded_user, "Groceries").id
    bobs = add_account(seeded_other, "BobAcct")
    add_txn(seeded_other, bobs, "Groceries", "3.00", on=date(2026, 2, 2))
    for param in (f"account={data[0].id}", f"category={their_cat}"):
        html = bob_client.get(f"/reports/?{Q}&{param}").get_data(as_text=True)
        assert "Not a valid choice" in html
        assert "3,500.00" not in html and "Jan pay" not in html and "$3.00" in html


def test_service_rejects_foreign_ids_even_without_the_form(seeded_user, seeded_other, data):
    from app.services.common import ServiceError
    with pytest.raises(ServiceError):
        build_report(seeded_other.id, ReportFilters(date(2026, 1, 1), date(2026, 3, 31), account_id=data[0].id))


# ---- CSV: transactions ----------------------------------------------------------------------------------------------------------
def test_transaction_export_content_and_headers(alice_client, data):
    r = alice_client.get(f"/reports/export/transactions.csv?{Q}")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert r.headers["Content-Disposition"] == 'attachment; filename="transactions_2026-01-01_to_2026-03-31.csv"'
    assert r.headers["Cache-Control"] == "no-store"
    rows = rows_of(r)
    assert rows[0] == ["Date", "Type", "Account", "Category", "Description", "Amount", "Signed amount"]
    assert rows[1:] == [
        ["2026-01-05", "income", "Main", "Salary", "Jan pay", "3000.00", "3000.00"],
        ["2026-01-20", "expense", "Main", "Groceries", "Jan shop", "100.00", "-100.00"],
        ["2026-02-14", "expense", "Card", "Dining Out", "Valentine, dinner", "40.00", "-40.00"],
        ["2026-03-01", "expense", "Main", "Groceries", "Mar shop", "60.00", "-60.00"],
        ["2026-03-31", "income", "Main", "Freelance", "Mar gig", "500.00", "500.00"],
    ]


def test_export_applies_the_same_filters(alice_client, seeded_user, data):
    rows = rows_of(alice_client.get(f"/reports/export/transactions.csv?{Q}&account={data[1].id}"))
    assert [r[4] for r in rows[1:]] == ["Valentine, dinner"]
    rows = rows_of(alice_client.get(f"/reports/export/transactions.csv?{Q}&category={category_of(seeded_user, 'Freelance').id}"))
    assert [r[4] for r in rows[1:]] == ["Mar gig"]


def test_export_excludes_transfers_and_includes_archived_history(alice_client, seeded_user, data):
    add_transfer(seeded_user, data[0], data[1], "5.00", on=date(2026, 2, 2), desc="TRANSFER-NOTE")
    old = add_account(seeded_user, "OldAcct")
    add_txn(seeded_user, old, "Salary", "9.00", on=date(2026, 2, 3), desc="from-archived")
    add_txn(seeded_user, old, "Groceries", "9.00", on=date(2026, 2, 4), desc="from-archived-2")
    archive_account(seeded_user.id, old.id)
    descriptions = [r[4] for r in rows_of(alice_client.get(f"/reports/export/transactions.csv?{Q}"))[1:]]
    assert "TRANSFER-NOTE" not in descriptions and {"from-archived", "from-archived-2"} <= set(descriptions)


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "=HYPERLINK(\"http://evil\",\"x\")"])
def test_csv_formula_injection_is_neutralised(alice_client, seeded_user, text):
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2026, 1, 2), desc=text)
    row = rows_of(alice_client.get("/reports/export/transactions.csv?date_from=2026-01-01&date_to=2026-01-31"))[1]
    assert row[4] == "'" + text and not row[4].startswith(("=", "+", "-", "@"))


def test_account_and_category_names_are_also_sanitised(alice_client, seeded_user):
    acct = add_account(seeded_user, "=cmd|' /C calc'!A0")
    create_category(seeded_user.id, "@evil", FlowType.EXPENSE)
    add_txn(seeded_user, acct, "@evil", "1.00", on=date(2026, 1, 2))
    row = rows_of(alice_client.get("/reports/export/transactions.csv?date_from=2026-01-01&date_to=2026-01-31"))[1]
    assert row[2].startswith("'=") and row[3] == "'@evil"


def test_quotes_commas_and_unicode_round_trip(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Groceries", "1.00", on=date(2026, 1, 2), desc='Café "Ünï", 100% ☕')
    row = rows_of(alice_client.get("/reports/export/transactions.csv?date_from=2026-01-01&date_to=2026-01-31"))[1]
    assert row[4] == 'Café "Ünï", 100% ☕'


def test_export_amounts_are_plain_decimals_no_symbols_or_separators(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Salary", "1234567.80", on=date(2026, 1, 2))
    row = rows_of(alice_client.get("/reports/export/transactions.csv?date_from=2026-01-01&date_to=2026-01-31"))[1]
    assert row[5:] == ["1234567.80", "1234567.80"]


def test_export_of_nothing_is_just_the_header(alice_client, seeded_user):
    rows = rows_of(alice_client.get("/reports/export/transactions.csv?date_from=2020-01-01&date_to=2020-01-31"))
    assert len(rows) == 1


def test_export_never_includes_another_users_rows(bob_client, seeded_user, seeded_other, data):
    add_txn(seeded_other, add_account(seeded_other, "B"), "Groceries", "2.00", on=date(2026, 2, 2), desc="bobs")
    rows = rows_of(bob_client.get(f"/reports/export/transactions.csv?{Q}"))
    assert [r[4] for r in rows[1:]] == ["bobs"]


@pytest.mark.parametrize("path", ["transactions", "summary"])
def test_export_with_foreign_or_bad_filters_redirects_instead_of_leaking(bob_client, seeded_user, seeded_other, data, path):
    r = bob_client.get(f"/reports/export/{path}.csv?{Q}&account={data[0].id}")
    assert r.status_code == 302 and "/reports/" in r.headers["Location"]
    r = bob_client.get(f"/reports/export/{path}.csv?date_from=2026-05-01&date_to=2026-01-01")
    assert r.status_code == 302


def test_export_redirect_cannot_be_hijacked_via_url_for_special_args(bob_client, data):
    r = bob_client.get("/reports/export/transactions.csv?date_from=bad&_external=1&_anchor=x&_scheme=http")
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/reports/") and "_external" not in r.headers["Location"]


# ---- CSV: monthly summary -----------------------------------------------------------------------------------------------------------
def test_monthly_summary_export(alice_client, data):
    r = alice_client.get(f"/reports/export/summary.csv?{Q}")
    assert r.headers["Content-Disposition"] == 'attachment; filename="monthly-summary_2026-01-01_to_2026-03-31.csv"'
    assert rows_of(r) == [
        ["Month", "Income", "Expenses", "Net", "Savings rate (%)"],
        ["2026-01", "3000.00", "100.00", "2900.00", "96.7"],
        ["2026-02", "0.00", "40.00", "-40.00", ""],
        ["2026-03", "500.00", "60.00", "440.00", "88.0"],
        ["Total", "3500.00", "200.00", "3300.00", "94.3"],
    ]


# ---- Unit helpers ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, safe", [("plain", "plain"), ("", ""), ("=x", "'=x"), ("+x", "'+x"), ("-x", "'-x"),
                                       ("@x", "'@x"), ("\tx", "'\tx"), ("a=b", "a=b"), (" =x", " =x")])
def test_safe_cell(raw, safe):
    assert safe_cell(raw) == safe


def test_plain_amount_and_stream_start_with_bom():
    assert plain_amount(D("5")) == "5.00" and plain_amount(D("-0.5")) == "-0.50"
    chunks = list(csv_stream([["a", "b,c"], ["d", 'e"f']]))
    assert chunks[0] == "﻿" and "".join(chunks[1:]) == 'a,"b,c"\r\nd,"e""f"\r\n'


def test_reports_require_login(client):
    for path in ("/reports/", "/reports/export/transactions.csv", "/reports/export/summary.csv"):
        r = client.get(path)
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
