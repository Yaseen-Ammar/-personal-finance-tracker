from flask import Blueprint

from app.extensions import db, login_manager
from app.models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")

login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


from . import routes  # noqa: E402,F401  (register routes on the blueprint)
