from app.forms_common import protected_blueprint

bp = protected_blueprint("accounts", __name__, url_prefix="/accounts")

from . import routes  # noqa: E402,F401
