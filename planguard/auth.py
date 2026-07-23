import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from . import db
from .models import User

auth = Blueprint("auth", __name__)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@auth.before_app_request
def load_signed_in_user():
    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id is not None else None
    if user_id is not None and g.user is None:
        session.clear()


def validate_registration(email, display_name, password):
    errors = {}
    if not EMAIL_PATTERN.fullmatch(email):
        errors["email"] = "Enter a valid email address."
    if not display_name:
        errors["display_name"] = "Display name is required."
    elif len(display_name) > 120:
        errors["display_name"] = "Display name must be 120 characters or fewer."
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    return errors


@auth.route("/register", methods=("GET", "POST"))
def register():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    errors = {}
    form_data = {"email": "", "display_name": ""}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        form_data = {"email": email, "display_name": display_name}
        errors = validate_registration(email, display_name, password)

        if not errors and db.session.scalar(db.select(User).where(User.email == email)):
            errors["email"] = "An account with that email already exists."

        if not errors:
            user = User(email=email, display_name=display_name)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors["email"] = "An account with that email already exists."
            else:
                session.clear()
                session["user_id"] = user.id
                flash(f"Welcome to PlanGuard, {user.display_name}!", "success")
                return redirect(url_for("main.dashboard"))

    return render_template("register.html", errors=errors, form_data=form_data)


@auth.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.landing"))
