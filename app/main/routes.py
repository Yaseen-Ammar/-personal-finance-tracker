from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from . import bp


@bp.route("/")
def index():
    target = "main.dashboard" if current_user.is_authenticated else "auth.login"
    return redirect(url_for(target))


@bp.route("/dashboard")
@login_required
def dashboard():
    # Placeholder landing page; the real dashboard is built in Phase 4.
    return render_template("main/dashboard.html")
