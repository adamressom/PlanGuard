from datetime import timedelta

from planguard import create_app, db
from planguard.models import User


def make_app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'signin.db'}",
    })
    with app.app_context():
        user = User(email="student@example.com", display_name="Avery")
        user.set_password("strong-pass-123")
        db.session.add(user)
        db.session.commit()
    return app


def test_sign_in_page_renders(tmp_path):
    response = make_app(tmp_path).test_client().get("/login")
    assert response.status_code == 200
    assert b"Sign in" in response.data


def test_valid_credentials_create_authenticated_session(tmp_path):
    client = make_app(tmp_path).test_client()
    response = client.post("/login", data={"email": "STUDENT@example.com", "password": "strong-pass-123"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as session:
        assert session["user_id"]
        assert session.permanent


def test_valid_sign_in_can_access_dashboard(tmp_path):
    client = make_app(tmp_path).test_client()
    client.post("/login", data={"email": "student@example.com", "password": "strong-pass-123"})
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"PRIORITY QUEUE" in response.data


def test_wrong_password_uses_generic_error(tmp_path):
    client = make_app(tmp_path).test_client()
    response = client.post("/login", data={"email": "student@example.com", "password": "wrong-password"})
    assert response.status_code == 200
    assert b"Email or password is incorrect." in response.data


def test_unknown_email_uses_same_generic_error(tmp_path):
    client = make_app(tmp_path).test_client()
    response = client.post("/login", data={"email": "unknown@example.com", "password": "wrong-password"})
    assert b"Email or password is incorrect." in response.data


def test_anonymous_user_is_redirected_to_login_then_back(tmp_path):
    client = make_app(tmp_path).test_client()
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?next=/dashboard")
    response = client.post("/login", data={"email": "student@example.com", "password": "strong-pass-123", "next": "/dashboard"})
    assert response.headers["Location"].endswith("/dashboard")


def test_external_next_url_is_rejected(tmp_path):
    client = make_app(tmp_path).test_client()
    response = client.post("/login", data={"email": "student@example.com", "password": "strong-pass-123", "next": "https://evil.example"})
    assert response.headers["Location"].endswith("/dashboard")


def test_login_clears_old_session_values(tmp_path):
    client = make_app(tmp_path).test_client()
    with client.session_transaction() as session:
        session["untrusted"] = "old-value"
    client.post("/login", data={"email": "student@example.com", "password": "strong-pass-123"})
    with client.session_transaction() as session:
        assert "untrusted" not in session


def test_logout_clears_session_and_blocks_dashboard(tmp_path):
    client = make_app(tmp_path).test_client()
    client.post("/login", data={"email": "student@example.com", "password": "strong-pass-123"})
    response = client.post("/logout")
    assert response.status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_session_cookie_defaults_are_secure(tmp_path):
    app = make_app(tmp_path)
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)


def test_production_enables_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-test-secret")
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'production.db'}"})
    assert app.config["SESSION_COOKIE_SECURE"] is True
