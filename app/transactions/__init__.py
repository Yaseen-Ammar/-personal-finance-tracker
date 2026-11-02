from app.forms_common import protected_blueprint

bp = protected_blueprint("transactions", __name__, url_prefix="/transactions")

from . import routes  # noqa: E402,F401
