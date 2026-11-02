from .conftest import login


def test_anonymous_dashboard_redirects_to_login_with_next(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    location = response.headers["Location"]
    assert "/auth/login" in location
    assert "next=%2Fdashboard" in location


def test_anonymous_root_redirects_to_login(client):
    assert "/auth/login" in client.get("/").headers["Location"]


def test_authenticated_root_redirects_to_dashboard(client, user):
    login(client)
    assert client.get("/").headers["Location"].endswith("/dashboard")


def test_authenticated_user_sees_own_name_only(client, user, other_user):
    login(client)
    body = client.get("/dashboard").data
    assert b"Alice" in body
    assert b"Bob" not in body


def test_authenticated_user_is_bounced_from_login_and_register(client, user):
    login(client)
    for path in ("/auth/login", "/auth/register"):
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")


def test_logout_requires_authentication(client):
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_pages_are_not_cacheable(client, user):
    login(client)
    assert client.get("/dashboard").headers["Cache-Control"] == "no-store"


def test_security_headers_present(client):
    headers = client.get("/auth/login").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in headers


def test_session_cookie_flags(client, user):
    response = login(client)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_tampered_session_cookie_is_not_authenticated(client, user):
    login(client)
    client.set_cookie("session", "forged.value.here")
    assert client.get("/dashboard").status_code == 302
