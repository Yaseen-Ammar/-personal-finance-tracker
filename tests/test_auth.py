import pytest
from sqlalchemy import select

from app.auth.utils import is_safe_redirect
from app.extensions import db
from app.models import User

from .conftest import PASSWORD, login, make_user

VALID = {
    "display_name": "Carol",
    "email": "carol@example.com",
    "password": "Passw0rd123",
    "confirm_password": "Passw0rd123",
}


def register(client, **overrides):
    return client.post("/auth/register", data={**VALID, **overrides})


# ---- Registration -----------------------------------------------------------
def test_register_page_renders(client):
    response = client.get("/auth/register")
    assert response.status_code == 200
    assert b"Create your account" in response.data


def test_register_creates_user_with_hashed_password(client):
    response = register(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    user = db.session.execute(select(User).filter_by(email="carol@example.com")).scalar_one()
    assert user.display_name == "Carol"
    assert user.password_hash != VALID["password"]
    assert user.check_password(VALID["password"])


def test_register_normalises_email(client):
    register(client, email="  Carol@Example.COM ")
    assert db.session.execute(select(User).filter_by(email="carol@example.com")).scalar_one()


def test_register_duplicate_email_rejected_case_insensitively(client, user):
    response = register(client, email="ALICE@example.com")
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert len(db.session.execute(select(User)).scalars().all()) == 1


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"email": "not-an-email"}, b"Invalid email"),
        ({"display_name": "A"}, b"between 2 and 80"),
        ({"password": "Short1", "confirm_password": "Short1"}, b"between 8 and 128"),
        ({"password": "onlyletters", "confirm_password": "onlyletters"}, b"letter and one number"),
        ({"password": "12345678", "confirm_password": "12345678"}, b"letter and one number"),
        ({"confirm_password": "Different123"}, b"Passwords must match"),
        ({"password": "x" * 129, "confirm_password": "x" * 129}, b"between 8 and 128"),
        ({"email": ""}, b"This field is required"),
    ],
)
def test_register_validation_errors(client, overrides, message):
    response = register(client, **overrides)
    assert response.status_code == 200
    assert message in response.data
    assert db.session.execute(select(User)).first() is None


def test_register_escapes_html_in_name(client, user):
    # Name echoed back in the form after a failed submit must be escaped.
    response = register(client, display_name="<script>alert(1)</script>", email="bad")
    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;" in response.data


# ---- Login -------------------------------------------------------------------
def test_login_success_redirects_to_dashboard(client, user):
    response = login(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_login_email_is_case_insensitive(client, user):
    assert login(client, email="ALICE@Example.com").status_code == 302


def test_login_wrong_password_and_unknown_email_give_same_message(client, user):
    wrong_pw = login(client, password="WrongPass1")
    unknown = login(client, email="nobody@example.com")
    for response in (wrong_pw, unknown):
        assert response.status_code == 200
        assert b"Invalid email or password." in response.data
    # No session created
    assert client.get("/dashboard").status_code == 302


def test_login_honours_safe_next(client, user):
    response = client.post(
        "/auth/login?next=/dashboard", data={"email": "alice@example.com", "password": PASSWORD}
    )
    assert response.headers["Location"].endswith("/dashboard")


@pytest.mark.parametrize(
    "evil", ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"]
)
def test_login_ignores_unsafe_next(client, user, evil):
    response = client.post(
        "/auth/login", query_string={"next": evil},
        data={"email": "alice@example.com", "password": PASSWORD},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


@pytest.mark.parametrize(
    "target, expected",
    [("/dashboard", True), ("/a/b?x=1", True), (None, False), ("", False),
     ("dashboard", False), ("//x.com", False), ("http://x.com", False), ("/\\x.com", False)],
)
def test_is_safe_redirect(target, expected):
    assert is_safe_redirect(target) is expected


def test_password_is_not_echoed_back_on_failed_login(client, user):
    response = login(client, password="WrongPass1")
    assert b"WrongPass1" not in response.data


# ---- Logout ------------------------------------------------------------------
def test_logout_ends_session(client, user):
    login(client)
    assert client.get("/dashboard").status_code == 200
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_logout_rejects_get(client, user):
    login(client)
    assert client.get("/auth/logout").status_code == 405
    assert client.get("/dashboard").status_code == 200  # still signed in


# ---- CSRF --------------------------------------------------------------------
def test_login_without_csrf_token_rejected(csrf_client, user):
    response = login(csrf_client)
    assert response.status_code == 400
    assert csrf_client.get("/dashboard").status_code == 302


def test_register_without_csrf_token_rejected(csrf_client):
    assert register(csrf_client).status_code == 400
    assert db.session.execute(select(User)).first() is None


def test_logout_without_csrf_token_rejected(csrf_client, user, app):
    app.config["WTF_CSRF_ENABLED"] = False
    login(csrf_client)
    app.config["WTF_CSRF_ENABLED"] = True
    assert csrf_client.post("/auth/logout").status_code == 400
    assert csrf_client.get("/dashboard").status_code == 200  # still signed in


def test_login_with_valid_csrf_token_succeeds(csrf_client, user):
    page = csrf_client.get("/auth/login").data.decode()
    token = page.split('name="csrf_token" type="hidden" value="')[1].split('"')[0]
    response = csrf_client.post(
        "/auth/login",
        data={"email": "alice@example.com", "password": PASSWORD, "csrf_token": token},
    )
    assert response.status_code == 302


def test_two_users_have_independent_sessions(app, user, other_user):
    alice, bob = app.test_client(), app.test_client()
    login(alice)
    assert alice.get("/dashboard").status_code == 200
    assert bob.get("/dashboard").status_code == 302
    assert make_user is not None  # helper imported for symmetry with other test modules
