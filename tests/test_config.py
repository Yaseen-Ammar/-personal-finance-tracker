import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from config import ConfigError, build_database_url

DB_ENV = {
    "MYSQL_USER": "u",
    "MYSQL_PASSWORD": "p@ss:/word#1",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_DATABASE": "d",
}


@pytest.fixture
def db_env(monkeypatch):
    for key, value in DB_ENV.items():
        monkeypatch.setenv(key, value)


def test_database_url_escapes_special_characters(db_env):
    url = build_database_url()
    rendered = url.render_as_string(hide_password=False)
    assert "p%40ss%3A%2Fword%231" in rendered
    assert url.drivername == "mysql+pymysql"


def test_database_url_repr_masks_password(db_env):
    assert "p@ss" not in repr(build_database_url())
    assert "***" in repr(build_database_url())


def test_missing_password_raises_config_error(db_env, monkeypatch):
    monkeypatch.delenv("MYSQL_PASSWORD")
    with pytest.raises(ConfigError, match="MYSQL_PASSWORD"):
        build_database_url()


def test_unknown_config_name_rejected():
    with pytest.raises(ValueError):
        create_app("nonsense")


def test_testing_app_uses_in_memory_db_and_cookie_flags():
    app = create_app("testing")
    assert app.config["TESTING"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    with app.app_context():
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_production_requires_secure_cookies():
    from config import ProductionConfig

    assert ProductionConfig.SESSION_COOKIE_SECURE is True
    assert ProductionConfig.DEBUG is False
