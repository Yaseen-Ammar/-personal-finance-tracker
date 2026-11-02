import json
import re
from datetime import date

import pytest

from .conftest import add_account, add_transfer, add_txn
from .test_dashboard import chart_data


def get(client, query=""):
    response = client.get("/analytics/" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.fixture
def year_2026(seeded_user):
    acct = add_account(seeded_user, "Main", opening="0.00")
    add_txn(seeded_user, acct, "Groceries", "100.00", on=date(2025, 12, 20))
    add_txn(seeded_user, acct, "Salary", "2000.00", on=date(2026, 1, 5))
    add_txn(seeded_user, acct, "Groceries", "150.00", on=date(2026, 1, 9))
    add_txn(seeded_user, acct, "Dining Out", "50.00", on=date(2026, 1, 10))
    add_txn(seeded_user, acct, "Groceries", "300.00", on=date(2026, 2, 3))
    add_txn(seeded_user, acct, "Salary", "2000.00", on=date(2026, 2, 5))
    return acct


def test_year_summary_cards(alice_client, year_2026):
    html = get(alice_client, "?year=2026")
    assert "Trends for 2026" in html
    assert "$4,000.00" in html and "$500.00" in html and "$3,500.00" in html
    assert "87.5%" in html                                   # 3500 / 4000
    assert "Highest: February 2026 ($300.00)" in html.replace("\n", " ") or "February 2026" in html


def test_month_by_month_table_has_twelve_rows_with_comparisons(alice_client, year_2026):
    html = get(alice_client, "?year=2026")
    table = html.split('id="a-table"')[1].split("</section>")[0]
    assert table.count('<th scope="row"') == 12
    assert "January 2026" in table and "December 2026" in table
    # January expenses are 200.00 (150 + 50) against December 2025's 100.00: +100.0%, which is bad news.
    assert re.search(r"delta-bad\">\s*<span aria-hidden=\"true\">▲</span>\s*100\.0%", table)


def test_running_net_and_chart_payload(alice_client, year_2026):
    data = chart_data(get(alice_client, "?year=2026"))
    ie = data["incomeExpense"]
    assert len(ie["labels"]) == 12 and ie["labels"][0] == "Jan 2026"
    assert ie["income"][:2] == ["2000.00", "2000.00"] and ie["expenses"][:2] == ["200.00", "300.00"]
    assert ie["net"][:2] == ["1800.00", "1700.00"]
    assert ie["cumulative"][:3] == ["1800.00", "3500.00", "3500.00"]
    assert data["category"]["labels"][0] == "Groceries" and data["category"]["values"][0] == "450.00"
    assert "topCategories" not in data  # the ranked list is HTML, not a chart


def test_future_months_are_gaps_not_a_drop_to_zero(alice_client, seeded_user):
    """Found in the browser: December plotted as a collapse to 0 and "-100% vs last month"."""
    next_year = date.today().year + 1
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Salary", "1000.00", on=date(next_year, 1, 10))
    add_txn(seeded_user, acct, "Groceries", "400.00", on=date(next_year, 1, 11))
    html = get(alice_client, f"?year={next_year}")
    ie = chart_data(html)["incomeExpense"]
    assert ie["net"][0] == "600.00" and ie["cumulative"][0] == "600.00"
    assert ie["net"][1:] == [None] * 11 and ie["cumulative"][1:] == [None] * 11   # JSON null -> line gap
    assert ie["income"][1:] == ["0.00"] * 11                                       # bars stay honest zeros
    table = html.split('id="a-table"')[1].split("</section>")[0]
    assert table.count("Not started yet") == 11 and "100.0% vs" not in table.split("February")[1]


def test_past_months_with_no_activity_are_still_real_zeros(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Salary", "10.00", on=date(2024, 6, 1))
    ie = chart_data(get(alice_client, "?year=2024"))["incomeExpense"]
    assert None not in ie["net"] and ie["net"][0] == "0.00" and ie["net"][5] == "10.00"


def test_highest_spending_categories_ranked(alice_client, year_2026):
    html = get(alice_client, "?year=2026")
    ranked = html.split('id="a-top"')[1].split("</section>")[0]
    assert ranked.index("Groceries") < ranked.index("Dining Out")
    assert "90.0% of 2026 spending" in ranked and "10.0% of 2026 spending" in ranked


def test_transfers_are_ignored_by_analytics(alice_client, seeded_user, year_2026):
    other = add_account(seeded_user, "Other")
    add_transfer(seeded_user, year_2026, other, "1234.00", on=date(2026, 1, 15))
    html = get(alice_client, "?year=2026")
    assert "1,234.00" not in html and "$4,000.00" in html and "$500.00" in html


def test_year_with_no_activity_shows_an_empty_state(alice_client, year_2026):
    html = get(alice_client, "?year=2024")
    assert "No activity in 2024" in html and "<canvas" not in html and "chart.umd" not in html


def test_new_user_analytics_page_is_a_friendly_empty_state(alice_client):
    html = get(alice_client)
    assert f"No activity in {date.today().year}" in html and "$0.00" in html


@pytest.mark.parametrize("query", ["?year=abc", "?year=1900", "?year=2999", "?year=%C2%B2", "?year=", "?year=-5", "?year=" + "9" * 300])
def test_bad_year_falls_back_safely(alice_client, query):
    html = get(alice_client, query)
    assert f"Trends for {date.today().year}" in html
    if query not in ("?year=",):
        assert "isn&#39;t valid, so the current year is shown" in html


def test_year_picker_links(alice_client, year_2026):
    html = get(alice_client, "?year=2026")
    assert "year=2025" in html and "year=2027" in html
    assert re.search(r'<option value="2026" selected>2026</option>', html)


def test_other_users_activity_is_invisible(bob_client, seeded_user, seeded_other, year_2026):
    add_txn(seeded_other, add_account(seeded_other, "BobAcct"), "Groceries", "7.00", on=date(2026, 3, 3))
    html = get(bob_client, "?year=2026")
    assert "$7.00" in html and "$4,000.00" not in html and "2,000.00" not in html
    assert json.dumps(chart_data(html)).count("2000.00") == 0


def test_analytics_requires_login(client):
    assert client.get("/analytics/").status_code == 302
