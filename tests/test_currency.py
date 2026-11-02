"""Configurable currency formatting, plus accessibility details of the shared UI."""
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app import create_app
from app.currency import format_money, validate_currency_settings
from config import ConfigError, TestingConfig

from .conftest import add_account, add_transfer, add_txn

D = Decimal
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def fmt(app, value, code="USD", locale="en_US"):
    app.config.update(CURRENCY_CODE=code, CURRENCY_LOCALE=locale)
    with app.test_request_context():
        return format_money(value).replace("\xa0", " ")


# ---- Formatting ------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [("1234.5", "$1,234.50"), ("0", "$0.00"), ("-5", "-$5.00"), ("0.10", "$0.10"),
     ("999999999999.99", "$999,999,999,999.99"), (D("1000000"), "$1,000,000.00")],
)
def test_default_usd_formatting(app, value, expected):
    assert fmt(app, D(value)) == expected


@pytest.mark.parametrize(
    "code, locale, expected",
    [("GBP", "en_GB", "£1,234.50"), ("EUR", "de_DE", "1.234,50 €"),
     ("EUR", "en_IE", "€1,234.50"), ("JPY", "en_US", "¥1,234.50"), ("gbp", "en_GB", "£1,234.50")],
)
def test_currency_and_locale_are_configurable(app, code, locale, expected):
    app.config["CURRENCY_CODE"] = validate_currency_settings(code, locale)[0]
    assert fmt(app, D("1234.50"), app.config["CURRENCY_CODE"], locale) == expected


def test_formatting_never_loses_cents_to_float_rounding(app):
    assert fmt(app, D("0.1") + D("0.2")) == "$0.30"


def test_jpy_keeps_two_decimals_matching_stored_precision(app):
    # Storage is DECIMAL(14,2): showing 0 decimals would hide real cents.
    assert fmt(app, D("10.55"), "JPY") == "¥10.55"


# ---- Validation ---------------------------------------------------------------------
@pytest.mark.parametrize("code", ["", "XXXX", "usd1", "DOLLAR", "ZZZ", "12"])
def test_invalid_currency_code_rejected(code):
    with pytest.raises(ConfigError, match="CURRENCY_CODE"):
        validate_currency_settings(code, "en_US")


@pytest.mark.parametrize("locale", ["", "not_a_locale", "xx_YY", "123"])
def test_invalid_locale_rejected(locale):
    with pytest.raises(ConfigError, match="CURRENCY_LOCALE"):
        validate_currency_settings("USD", locale)


def test_app_refuses_to_start_with_bad_currency(monkeypatch):
    monkeypatch.setattr(TestingConfig, "CURRENCY_CODE", "NOPE")
    with pytest.raises(ConfigError):
        create_app("testing")


def test_app_normalises_lowercase_currency_code(monkeypatch):
    monkeypatch.setattr(TestingConfig, "CURRENCY_CODE", "eur")
    assert create_app("testing").config["CURRENCY_CODE"] == "EUR"


# ---- Rendered consistently across pages ------------------------------------------------------
def test_all_money_pages_use_the_configured_currency(app, alice_client, seeded_user):
    a = add_account(seeded_user, "Wallet", opening="100.00")
    b = add_account(seeded_user, "Bank")
    add_txn(seeded_user, a, "Groceries", "12.34", desc="shop")
    add_txn(seeded_user, a, "Salary", "2000.00", desc="pay")
    add_transfer(seeded_user, a, b, "50.00")

    app.config.update(CURRENCY_CODE="GBP", CURRENCY_LOCALE="en_GB")
    pages = {p: alice_client.get(p).get_data(as_text=True)
             for p in ("/accounts/", "/transactions/", "/transfers/")}
    assert "£2,037.66" in pages["/accounts/"]          # total balance
    assert "£50.00" in pages["/accounts/"] and "£100.00" in pages["/accounts/"]
    assert "+£2,000.00" in pages["/transactions/"] and "&minus;£12.34" in pages["/transactions/"]
    assert "£50.00" in pages["/transfers/"]
    for body in pages.values():
        assert "$" not in re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)


def test_negative_balance_is_formatted_and_marked(alice_client, seeded_user):
    add_account(seeded_user, "Card", opening="-200.00")
    body = alice_client.get("/accounts/").get_data(as_text=True)
    assert "-$200.00" in body and "amt-out" in body


@pytest.mark.parametrize("path", ["/accounts/new", "/transactions/new", "/transfers/new"])
def test_money_inputs_show_the_currency_symbol(app, alice_client, seeded_user, path):
    add_account(seeded_user, "One")
    add_account(seeded_user, "Two")
    app.config.update(CURRENCY_CODE="EUR", CURRENCY_LOCALE="en_IE")
    assert 'input-group-text" aria-hidden="true">€' in alice_client.get(path).get_data(as_text=True)


def test_archive_error_message_uses_configured_currency(app, alice_client, seeded_user):
    acct = add_account(seeded_user, "Rich", opening="5.00")
    app.config.update(CURRENCY_CODE="GBP", CURRENCY_LOCALE="en_GB")
    body = alice_client.post(f"/accounts/{acct.id}/archive", follow_redirects=True).get_data(as_text=True)
    assert "£5.00" in body


def test_no_currency_symbol_is_hardcoded_in_templates_or_python():
    """Guard: symbols may only come from configuration, never from source."""
    offenders = []
    for path in list(APP_DIR.rglob("*.html")) + list(APP_DIR.rglob("*.py")):
        if path.name == "currency.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"[£€¥₹]|\$\s?\{|[\"'>]\$\d", line):
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}")
    assert offenders == []


# ---- Issues found during the real-browser review (regression guards) -----------------------------
def test_brand_panel_copy_does_not_hardcode_a_currency(client):
    body = client.get("/auth/login").get_data(as_text=True).lower()
    assert "pound" not in body and "dollar" not in body and "euro" not in body


def test_sidebar_background_override_for_bootstrap_offcanvas_lg_is_present():
    """Bootstrap forces .offcanvas-lg transparent (!important) on desktop, which made
    the sidebar text invisible on the pale page. The override must stay."""
    css = (APP_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".sidebar.offcanvas-lg" in css
    assert re.search(r"\.sidebar\.offcanvas-lg\s*\{\s*background-color:\s*var\(--ink\)\s*!important", css)


def test_filters_collapse_on_phones_and_open_when_a_filter_is_active(alice_client, seeded_user):
    add_account(seeded_user, "A")
    plain = alice_client.get("/transactions/").get_data(as_text=True)
    assert 'data-bs-target="#filterFields"' in plain and 'aria-expanded="false"' in plain
    assert 'class="collapse d-md-block "' in plain  # closed on phones, always open on md+
    active = alice_client.get("/transactions/?type=expense&q=x").get_data(as_text=True)
    assert 'aria-expanded="true"' in active and "collapse d-md-block show" in active
    assert "(2 active)" in active
    assert "(1 active)" in alice_client.get("/transactions/?sort=amount_asc&type=income").get_data(as_text=True)


def test_invalid_filter_keeps_the_filter_panel_open(alice_client):
    body = alice_client.get("/transactions/?date_from=2026-12-01&date_to=2026-01-01").get_data(as_text=True)
    assert "collapse d-md-block show" in body and "must not be before" in body


def test_no_empty_pagination_footer_when_everything_fits_on_one_page(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    add_txn(seeded_user, acct, "Groceries", "1.00")
    assert "surface-foot" not in alice_client.get("/transactions/").get_data(as_text=True)
    assert "surface-foot" not in alice_client.get("/transfers/").get_data(as_text=True)


def test_pagination_footer_appears_when_there_are_multiple_pages(alice_client, seeded_user):
    acct = add_account(seeded_user, "A")
    for i in range(16):
        add_txn(seeded_user, acct, "Groceries", "1.00", desc=f"n{i}")
    assert "surface-foot" in alice_client.get("/transactions/").get_data(as_text=True)


# ---- Accessibility details -----------------------------------------------------------------------
def test_invalid_field_is_linked_to_its_error_message(alice_client, seeded_user):
    body = alice_client.post("/accounts/new", data={"name": "", "account_type": "cash", "opening_balance": "x"}).get_data(as_text=True)
    assert re.search(r'id="name"[^>]*aria-invalid="true"|aria-invalid="true"[^>]*id="name"', body)
    assert 'aria-describedby="name-error"' in body and 'id="name-error"' in body
    # This field has both an error and a hint, so it points at both.
    assert 'aria-describedby="opening_balance-error opening_balance-hint"' in body
    assert 'id="opening_balance-error"' in body and 'id="opening_balance-hint"' in body


def test_hint_is_linked_to_its_input(alice_client):
    body = alice_client.get("/accounts/new").get_data(as_text=True)
    assert 'aria-describedby="opening_balance-hint"' in body and 'id="opening_balance-hint"' in body


def test_valid_field_has_no_error_attributes(alice_client):
    body = alice_client.get("/accounts/new").get_data(as_text=True)
    assert "aria-invalid" not in body and "is-invalid" not in body


def test_layout_has_skip_link_landmarks_and_scoped_table_headers(alice_client, seeded_user):
    add_account(seeded_user, "A")
    body = alice_client.get("/accounts/").get_data(as_text=True)
    assert 'href="#main"' in body and 'id="main"' in body
    assert '<nav class="sidebar' in body and 'aria-label="Main navigation"' in body
    assert 'aria-current="page"' in body
    assert "<th>" not in body and 'scope="col"' in body


def test_page_has_lang_and_single_h1(alice_client):
    body = alice_client.get("/accounts/").get_data(as_text=True)
    assert '<html lang="en">' in body and body.count("<h1") == 1


def test_delete_confirmation_modal_is_labelled(alice_client):
    body = alice_client.get("/accounts/").get_data(as_text=True)
    assert 'aria-labelledby="confirmModalTitle"' in body and 'id="confirmModalTitle"' in body
