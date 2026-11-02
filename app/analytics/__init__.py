from app.forms_common import protected_blueprint

bp = protected_blueprint("analytics", __name__, url_prefix="/analytics")

from . import routes  # noqa: E402,F401
