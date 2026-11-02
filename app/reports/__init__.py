from app.forms_common import protected_blueprint

bp = protected_blueprint("reports", __name__, url_prefix="/reports")

from . import routes  # noqa: E402,F401
