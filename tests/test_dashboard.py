import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.models import FlowType
from app.services.account_service import archive_account
from app.services.category_service import create_category

from .conftest import add_account, add_transfer, add_txn

D = Decimal
CHART_JSON = re.compile(r'<script type="application/json" id="chart-data">(.*?)</script>', re.S)


def chart_data(html):
    match = CHART_JSON.search(html)
    assert match, "chart-data block missing"
    return json.loads(match.group(1))


def page(client, query=""):
    response = client.get("/dashboard" + query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.fixture
def acct(seeded_user):
    return add_account(seeded_user, "Checking", opening="1000.00")


# ---- Empty states ------------------------------------------------------------------------------------
def test_new_user_sees_onboarding_and_no_charts(alice_client):
    html = page(alice_client)
    assert "Let's set you up" in html and "Create your first account" in html
    assert "<canvas" not in html and "chart.umd" not in html and 'id="chart-data"' not in html
    assert 'class="stat-card' not in html


def test_account_but_no_transactions_prompts_for_first_transaction(alice_client, acct):
    html = page(alice_client)
    assert "Record your first transaction" in html
    assert "$1,000.00" in html                        # balance card still works
    assert "<canvas" not in html and "chart.umd" not in html


def test_quiet_month_shows_zeroes_and_an_empty_category_message(alice_client, seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "10.00", on=date(2026, 3, 5))
    html = page(alice_client, "?year=2026&month=8")
    assert "No expenses recorded in August 2026" in html
    assert html.count("$0.00") >= 3                   # income, expenses, net
    assert "<canvas" in html                          # trend chart still has history to show


# ---- Calculations ---------------------------------------------------------------------------------------
@pytest.fixture
def june(seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "3000.00", on=date(2026, 6, 1), desc="June pay")
    add_txn(seeded_user, acct, "Groceries", "250.50", on=date(2026, 6, 8), desc="june shop")
    add_txn(seeded_user, acct, "Rent & Housing", "1000.00", on=date(2026, 6, 15))
    add_txn(seeded_user, acct, "Salary", "2000.00", on=date(2026, 5, 1))
    add_txn(seeded_user, acct, "Groceries", "500.00", on=date(2026, 5, 9))
    add_txn(seeded_user, acct, "Groceries", "7777.00", on=date(2026, 7, 2), desc="july splurge")
    return acct


def test_summary_cards_for_the_selected_month(alice_client, june):
    html = page(alice_client, "?year=2026&month=6")
    assert "Overview for June 2026" in html
    assert "$3,000.00" in html                         # income
    assert "$1,250.50" in html                         # expenses
    assert "$1,749.50" in html                         # net
    assert "58.3% of income saved" in html             # 1749.50 / 3000
    cards = html.split('class="stat-grid"')[1].split("</section>")[0].split('id="ie-title"')[0]
    assert "7,777.00" not in cards                     # July's expense is not in June's cards


def test_total_balance_is_all_time_not_month_scoped(alice_client, june):
    # 1000 opening + 5000 income - (250.50 + 1000 + 500 + 7777) expenses = -3527.50
    html = page(alice_client, "?year=2026&month=6")
    assert "-$3,527.50" in html and "Across 1 active account" in html


def test_changes_versus_previous_month_and_their_good_or_bad_styling(alice_client, june):
    html = page(alice_client, "?year=2026&month=6")
    # Income 2000 -> 3000 is +50.0% (good); expenses 500 -> 1250.50 is +150.1% (bad).
    assert re.search(r'delta-good">\s*<span aria-hidden="true">▲</span>\s*50\.0%', html)
    assert re.search(r'delta-bad">\s*<span aria-hidden="true">▲</span>\s*150\.1%', html)
    assert "vs</span> May 2026" in html
    assert "▼" not in html


def test_falling_expenses_are_shown_as_good_news(alice_client, seeded_user, acct):
    add_txn(seeded_user, acct, "Groceries", "400.00", on=date(2026, 5, 9))
    add_txn(seeded_user, acct, "Groceries", "100.00", on=date(2026, 6, 9))
    html = page(alice_client, "?year=2026&month=6")
    assert re.search(r'delta-good">\s*<span aria-hidden="true">▼</span>\s*75\.0%', html)


def test_no_comparison_when_previous_month_is_empty(alice_client, seeded_user, acct):
    add_txn(seeded_user, acct, "Salary", "10.00", on=date(2026, 6, 9))
    assert "Nothing in May 2026 to compare" in page(alice_client, "?year=2026&month=6")


def test_default_month_is_the_current_month(alice_client, seeded_user, acct):
    today = date.today()
    add_txn(seeded_user, acct, "Salary", "123.00", on=today, desc="today pay")
    html = page(alice_client)
    assert f"Overview for {today.strftime('%B %Y')}" in html and "$123.00" in html


def test_month_picker_state_and_navigation_links(alice_client, june):
    html = page(alice_client, "?year=2026&month=6")
    assert re.search(r'<option value="6" selected>June</option>', html)
    assert re.search(r'<option value="2026" selected>2026</option>', html)
    assert "year=2026&amp;month=5" in html and "year=2026&amp;month=7" in html
    assert 'aria-label="Previous month, May 2026"' in html and 'aria-label="Next month, July 2026"' in html
    assert page(alice_client, "?year=2026&month=1").count("year=2025&amp;month=12") >= 1  # wraps the year


@pytest.mark.parametrize("query", ["?year=2026&month=13", "?year=abc&month=5", "?month=5", "?year=1900&month=1",
                                   "?year=%C2%B2&month=5", "?year=2026&month=%0A", "?year=2026&month=" + "9" * 400])
def test_invalid_month_falls_back_with_a_warning_never_an_error(alice_client, seeded_user, acct, query):
    add_txn(seeded_user, acct, "Salary", "1.00", on=date.today())
    html = page(alice_client, query)
    assert "isn&#39;t valid, so the current month is shown" in html
    assert f"Overview for {date.today().strftime('%B %Y')}" in html


# ---- Transfers & archived accounts ---------------------------------------------------------------------------------
def test_transfers_do_not_inflate_income_or_expenses(alice_client, seeded_user, june):
    savings = add_account(seeded_user, "Savings")
    before = page(alice_client, "?year=2026&month=6")
    add_transfer(seeded_user, june, savings, "800.00", on=date(2026, 6, 20))
    after = page(alice_client, "?year=2026&month=6")
    for figure in ("$3,000.00", "$1,250.50", "$1,749.50"):
        assert figure in before and figure in after
    assert "$800.00" in after                            # shown only as Savings' balance
    assert "never counted as income or expenses" in after


def test_archived_account_is_left_out_of_balances_but_not_history(alice_client, seeded_user, june):
    old = add_account(seeded_user, "OldCard")
    add_txn(seeded_user, old, "Salary", "40.00", on=date(2026, 6, 3))
    add_txn(seeded_user, old, "Groceries", "40.00", on=date(2026, 6, 4))
    archive_account(seeded_user.id, old.id)
    html = page(alice_client, "?year=2026&month=6")
    section = html.split('id="acct-title"')[1].split("</section>")[0]
    assert "OldCard" not in section and "Checking" in section
    assert "$3,040.00" in html                           # June income still includes the archived card's 40


# ---- Recent transactions, charts, safety ------------------------------------------------------------------------------
def test_recent_transactions_are_the_latest_eight(alice_client, seeded_user, acct):
    for day in range(1, 13):
        add_txn(seeded_user, acct, "Groceries", f"{day}.00", on=date(2026, 6, day), desc=f"item{day:02d}")
    html = page(alice_client, "?year=2026&month=6")
    recent = html.split('id="recent-title"')[1].split("</section>")[0]
    assert all(f"item{d:02d}" in recent for d in range(5, 13)) and "item04" not in recent
    assert recent.index("item12") < recent.index("item05")


def test_chart_payload_is_exact_decimal_strings(alice_client, june):
    data = chart_data(page(alice_client, "?year=2026&month=6"))
    ie = data["incomeExpense"]
    assert ie["labels"] == ["Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026"]
    assert ie["income"][-2:] == ["2000.00", "3000.00"] and ie["expenses"][-2:] == ["500.00", "1250.50"]
    assert all(isinstance(v, str) for v in ie["income"] + ie["expenses"] + ie["net"])
    assert data["category"]["labels"] == ["Rent & Housing", "Groceries"]
    assert data["category"]["values"] == ["1000.00", "250.50"]
    assert data["currency"] == {"code": "USD", "locale": "en-US"}


def test_chart_library_is_pinned_with_integrity_hash(alice_client, june):
    html = page(alice_client, "?year=2026&month=6")
    tag = re.search(r'<script src="https://cdn\.jsdelivr\.net/npm/chart\.js@4\.4\.3/[^"]+"[^>]*>', html).group(0)
    assert 'integrity="sha384-' in tag and 'crossorigin="anonymous"' in tag


def test_chart_data_cannot_break_out_of_its_script_tag(alice_client, seeded_user, acct):
    evil = "</script><script>alert(1)</script>"
    create_category(seeded_user.id, evil[:80], FlowType.EXPENSE)
    add_txn(seeded_user, acct, evil[:80], "5.00", on=date(2026, 6, 2))
    html = page(alice_client, "?year=2026&month=6")
    block = CHART_JSON.search(html)
    assert block and "<script>alert(1)" not in block.group(1) and "</script>" not in block.group(1)
    assert "<script>alert(1)" not in html
    assert any("script" in label for label in json.loads(block.group(1))["category"]["labels"])


def test_charts_have_text_alternatives(alice_client, june):
    html = page(alice_client, "?year=2026&month=6")
    assert html.count('role="img"') == 2 and html.count('aria-label="Bar chart') == 1
    assert "View as a table" in html and '<caption class="visually-hidden">Income and expenses by month' in html


def test_dashboard_never_shows_another_users_figures(bob_client, seeded_user, seeded_other):
    mine = add_account(seeded_user, "AliceOnlyAccount", opening="1000.00")
    add_txn(seeded_user, mine, "Salary", "8888.00", on=date(2026, 6, 2), desc="alice-secret-pay")
    bobs = add_account(seeded_other, "BobMain", opening="5.00")
    add_txn(seeded_other, bobs, "Groceries", "1.00", on=date(2026, 6, 3))
    html = page(bob_client, "?year=2026&month=6")
    for secret in ("alice-secret-pay", "8,888.00", "AliceOnlyAccount", "1,000.00", "9,888.00"):
        assert secret not in html
    assert "BobMain" in html and "$4.00" in html


def test_dashboard_requires_login(client):
    r = client.get("/dashboard?year=2026&month=6")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
