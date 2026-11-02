from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.services.auth_service import (
    EmailAlreadyRegistered,
    authenticate,
    register_user,
)

from . import bp
from .forms import LoginForm, RegistrationForm
from .utils import is_safe_redirect

# One generic message for every login failure: never reveal whether the
# email exists.
INVALID_LOGIN_MESSAGE = "Invalid email or password."


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            register_user(form.email.data, form.display_name.data, form.password.data)
        except EmailAlreadyRegistered:
            form.email.errors.append("An account with this email already exists.")
        else:
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = authenticate(form.email.data, form.password.data)
        if user is None:
            flash(INVALID_LOGIN_MESSAGE, "danger")
        else:
            login_user(user)
            next_url = request.args.get("next")
            return redirect(next_url if is_safe_redirect(next_url) else url_for("main.dashboard"))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])  # POST + CSRF so a stray link/image can't log you out
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
