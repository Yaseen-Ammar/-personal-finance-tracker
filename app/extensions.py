"""Extension instances, created unbound and attached in create_app().

Keeping them here (not in app/__init__.py) avoids circular imports when
models and blueprints need `db`.
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData

# Deterministic constraint names. Without these MySQL/SQLAlchemy generate
# random names, which makes later Alembic migrations (drop/alter) fragile.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
