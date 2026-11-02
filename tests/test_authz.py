"""Authentication and cross-user access control for every Phase 3 route."""
import pytest

from app.extensions import db
from app.models import Account, Category, Transaction, Transfer

from .conftest import add_account, add_transfer, add_txn, category_of

PROTECTED_BLUEPRINTS = {"transactions", "accounts", "categories", "transfers", "analytics", "reports"}


def protected_rules(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint.split(".")[0] in PROTECTED_BLUEPRINTS:
            yield rule


def test_every_phase3_route_requires_login(app):
    """Iterates the real URL map, so any route added later is covered automatically."""
    client = app.test_client()
    checked = 0
    for rule in protected_rules(app):
        url = rule.rule
        for arg in rule.arguments:
            url = url.replace(f"<int:{arg}>", "1")
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            response = client.open(url, method=method)
            assert response.status_code == 302, (method, url)
            assert "/auth/login" in response.headers["Location"], (method, url)
            checked += 1
    assert checked >= 16


@pytest.fixture
def world(seeded_user, seeded_other):
    """Alice owns one of everything; Bob is the attacker."""
    acct = add_account(seeded_user, "AliceChecking", opening="100.00")
    acct2 = add_account(seeded_user, "Savings")
    txn = add_txn(seeded_user, acct, "Groceries", "9.99", desc="alice-secret-purchase")
    xfer = add_transfer(seeded_user, acct, acct2, "5.00", desc="alice-secret-transfer")
    from app.services.category_service import create_category
    from app.models import FlowType
    custom = create_category(seeded_user.id, "AliceCustom", FlowType.EXPENSE)
    return {"acct": acct, "txn": txn, "xfer": xfer, "custom": custom}


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/transactions/{txn}/edit"), ("POST", "/transactions/{txn}/edit"),
        ("POST", "/transactions/{txn}/delete"),
        ("GET", "/accounts/{acct}/edit"), ("POST", "/accounts/{acct}/edit"),
        ("POST", "/accounts/{acct}/archive"), ("POST", "/accounts/{acct}/restore"),
        ("GET", "/categories/{custom}/edit"), ("POST", "/categories/{custom}/edit"),
        ("POST", "/categories/{custom}/delete"),
        ("POST", "/transfers/{xfer}/delete"),
    ],
)
def test_other_users_records_return_404(bob_client, world, method, path):
    url = path.format(**{k: v.id for k, v in world.items()})
    response = bob_client.open(url, method=method, data={"name": "x", "type": "expense",
                                                         "account_type": "cash", "opening_balance": "0"})
    assert response.status_code == 404


def test_attacker_actions_change_nothing(bob_client, world):
    for url in (f"/transactions/{world['txn'].id}/delete", f"/accounts/{world['acct'].id}/archive",
                f"/categories/{world['custom'].id}/delete", f"/transfers/{world['xfer'].id}/delete"):
        bob_client.post(url)
    db.session.expire_all()
    assert db.session.get(Transaction, world["txn"].id) is not None
    assert db.session.get(Transfer, world["xfer"].id) is not None
    assert db.session.get(Category, world["custom"].id) is not None
    assert not db.session.get(Account, world["acct"].id).is_archived


def test_other_users_data_never_appears_in_lists(bob_client, world):
    for path in ("/transactions/", "/accounts/", "/transfers/", "/categories/"):
        body = bob_client.get(path).get_data(as_text=True)
        for secret in ("alice-secret-purchase", "alice-secret-transfer", "AliceCustom", "AliceChecking", "9.99"):
            assert secret not in body, (path, secret)


def test_cannot_book_transaction_into_another_users_account_or_category(bob_client, seeded_other, world):
    bobs_acct = add_account(seeded_other, "Bobs")
    base = {"type": "expense", "amount": "1.00", "transaction_date": "2026-06-15",
            "account_id": bobs_acct.id, "category_id": category_of(seeded_other, "Groceries").id}
    # Alice's account id
    r = bob_client.post("/transactions/new", data={**base, "account_id": world["acct"].id})
    assert r.status_code == 200
    # Alice's custom category id
    r = bob_client.post("/transactions/new", data={**base, "category_id": world["custom"].id})
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.query(Transaction).filter(Transaction.user_id != world["txn"].user_id).count() == 0


def test_cannot_move_own_transaction_into_another_users_account(alice_client, seeded_other, world):
    theirs = add_account(seeded_other, "Theirs")
    txn = world["txn"]
    r = alice_client.post(f"/transactions/{txn.id}/edit", data={
        "type": "expense", "account_id": theirs.id, "category_id": txn.category_id,
        "amount": "1.00", "transaction_date": "2026-06-15"})
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.get(Transaction, txn.id).account_id == world["acct"].id


# ---- CSRF on the new state-changing routes --------------------------------------------------
@pytest.mark.parametrize(
    "path",
    ["/transactions/new", "/accounts/new", "/categories/new", "/transfers/new",
     "/transactions/{txn}/delete", "/accounts/{acct}/archive", "/categories/{custom}/delete",
     "/transfers/{xfer}/delete"],
)
def test_post_without_csrf_token_is_rejected(app, seeded_user, world, path):
    client = app.test_client()
    app.config["WTF_CSRF_ENABLED"] = False
    client.post("/auth/login", data={"email": "alice@example.com", "password": "Sup3rSecret!"})
    app.config["WTF_CSRF_ENABLED"] = True
    url = path.format(**{k: v.id for k, v in world.items()})
    assert client.post(url, data={}).status_code == 400
    db.session.expire_all()
    assert db.session.get(Transaction, world["txn"].id) is not None
    assert db.session.get(Transfer, world["xfer"].id) is not None


def test_unknown_page_renders_friendly_404(alice_client):
    r = alice_client.get("/no/such/page")
    assert r.status_code == 404 and b"couldn't find that page" in r.data
