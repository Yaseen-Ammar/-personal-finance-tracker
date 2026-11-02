"""Application factory."""
import os

from flask import Flask, Response, render_template, request, url_for
from flask_login import current_user

from config import CONFIGS, BaseConfig, build_database_url

from .currency import currency_code, currency_symbol, format_money, validate_currency_settings
from .extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure a Flask app instance.

    The factory pattern lets tests build isolated apps with different
    configuration, and keeps import-time side effects to a minimum.
    """
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    config_class = CONFIGS.get(config_name)
    if config_class is None:
        raise ValueError(f"Unknown config '{config_name}'. Options: {sorted(CONFIGS)}")

    app = Flask(__name__)
    app.config.from_object(config_class)

    # Real secrets/DB URL are resolved at runtime; testing supplies its own.
    if config_name != "testing":
        app.config["SECRET_KEY"] = BaseConfig.secret_key()
        app.config["SQLALCHEMY_DATABASE_URI"] = build_database_url()

    code, locale = validate_currency_settings(
        app.config["CURRENCY_CODE"], app.config["CURRENCY_LOCALE"]
    )
    app.config.update(CURRENCY_CODE=code, CURRENCY_LOCALE=locale)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Importing models registers every table on db.metadata, which both
    # Flask-Migrate (autogenerate) and the ORM need.
    from . import models  # noqa: F401

    migrate.init_app(app, db)

    from .accounts import bp as accounts_bp
    from .auth import bp as auth_bp
    from .categories import bp as categories_bp
    from .main import bp as main_bp
    from .transactions import bp as transactions_bp
    from .transfers import bp as transfers_bp

    for blueprint in (
        auth_bp, main_bp, accounts_bp, categories_bp, transactions_bp, transfers_bp
    ):
        app.register_blueprint(blueprint)

    app.jinja_env.filters["currency"] = format_money
    app.jinja_env.globals["currency_symbol"] = currency_symbol
    app.jinja_env.globals["currency_code"] = currency_code
    app.jinja_env.globals["page_url"] = page_url
    app.register_error_handler(404, _not_found)
    app.after_request(_set_security_headers)
    return app


def page_url(page: int) -> str:
    """URL for `page` of the current listing, keeping all active filters."""
    args = request.args.to_dict(flat=True)
    args["page"] = page
    return url_for(request.endpoint, **{**(request.view_args or {}), **args})


def _not_found(_error):
    return render_template("errors/404.html"), 404


def _set_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Don't let the browser cache logged-in pages: after logout, the Back
    # button must not reveal someone's financial data.
    if current_user.is_authenticated:
        response.headers["Cache-Control"] = "no-store"
    return response
