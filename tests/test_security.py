import logging
import re

from cryptography.fernet import Fernet

from planguard import create_app, db
from planguard.models import User
from planguard.services.calendar import decrypt_token, encrypt_token


def security_app(tmp_path, **config):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "security-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'security.db'}",
        **config,
    })


def csrf_token(response):
    match = re.search(
        rb'name="csrf_token"\s+value="([^"]+)"',
        response.data,
    )
    assert match is not None
    return match.group(1).decode()


def test_html_forms_reject_missing_csrf_and_accept_valid_token(tmp_path):
    app = security_app(tmp_path, WTF_CSRF_ENABLED=True)
    client = app.test_client()

    rejected = client.post("/register", data={
        "display_name": "Security Student",
        "email": "secure@example.com",
        "password": "strong-password",
    })
    token = csrf_token(client.get("/register"))
    accepted = client.post("/register", data={
        "csrf_token": token,
        "display_name": "Security Student",
        "email": "secure@example.com",
        "password": "strong-password",
    })

    assert rejected.status_code == 400
    assert accepted.status_code == 302


def test_json_mutations_require_csrf_when_enabled(tmp_path):
    app = security_app(tmp_path, WTF_CSRF_ENABLED=True)
    with app.app_context():
        user = User(email="api-security@example.com", display_name="API Security")
        user.set_password("strong-password")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id

    rejected = client.post(
        "/api/v1/assignments",
        json={"title": "Unsafe request"},
    )

    assert rejected.status_code == 400


def test_login_is_rate_limited(tmp_path):
    app = security_app(
        tmp_path,
        RATELIMIT_ENABLED=True,
        WTF_CSRF_ENABLED=False,
        AUTH_RATE_LIMIT="2 per minute",
    )
    client = app.test_client()
    request_data = {"email": "missing@example.com", "password": "wrong-password"}

    assert client.post("/login", data=request_data).status_code == 200
    assert client.post("/login", data=request_data).status_code == 200
    assert client.post("/login", data=request_data).status_code == 429


def test_password_and_oauth_token_are_not_stored_as_plaintext(tmp_path):
    key = Fernet.generate_key().decode()
    app = security_app(tmp_path, TOKEN_ENCRYPTION_KEY=key)
    with app.app_context():
        user = User(email="private@example.com", display_name="Private Student")
        user.set_password("plain-password")
        encrypted = encrypt_token("provider-secret-token")

        assert user.password_hash != "plain-password"
        assert user.check_password("plain-password")
        assert encrypted != "provider-secret-token"
        assert decrypt_token(encrypted) == "provider-secret-token"


def test_provider_error_description_is_not_logged(tmp_path, caplog):
    app = security_app(tmp_path, GOOGLE_CALENDAR_MODE="demo")
    with app.app_context():
        user = User(email="oauth-security@example.com", display_name="OAuth Security")
        user.set_password("strong-password")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["google_oauth_attempt"] = {
            "state": "expected-state",
            "issued_at": 0,
        }

    caplog.set_level(logging.DEBUG)
    response = client.get(
        "/integrations/google-calendar/callback"
        "?state=expected-state&error=access_denied"
        "&error_description=provider-secret-detail"
    )

    assert response.status_code == 400
    assert "provider-secret-detail" not in caplog.text
