"""Verify the Flask -> MySQL connection without printing credentials.

Run:  python -m scripts.check_db
"""
import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from app.extensions import db
from config import ConfigError


def main() -> int:
    try:
        app = create_app("development")
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    with app.app_context():
        try:
            row = db.session.execute(
                text("SELECT VERSION(), DATABASE(), @@character_set_database")
            ).one()
        except SQLAlchemyError as exc:
            # Print only the driver's short message, never the URL/password.
            reason = getattr(exc, "orig", exc)
            print(f"CONNECTION FAILED: {reason}")
            return 1

    version, database, charset = row
    print(f"OK  MySQL {version} | database={database} | charset={charset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
