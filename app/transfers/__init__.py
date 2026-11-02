from app.forms_common import protected_blueprint

bp = protected_blueprint("transfers", __name__, url_prefix="/transfers")

from . import routes  # noqa: E402,F401
