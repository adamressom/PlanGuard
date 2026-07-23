from planguard import create_app, db
from planguard.models import User


def make_app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'auth.db'}",
    })


def registration_data(**overrides):
    return {"email": "student@example.com", "display_name": "Avery", "password": "strong-pass-123", **overrides}


def test_registration_page_renders(tmp_path):
    response = make_app(tmp_path).test_client().get("/register")
    assert response.status_code == 200
    assert b"Create your account" in response.data


def test_successful_registration_creates_user_and_signs_in(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    response = client.post("/register", data=registration_data(), follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "student@example.com"))
        assert user.display_name == "Avery"
        assert user.check_password("strong-pass-123")
        assert user.password_hash != "strong-pass-123"
    with client.session_transaction() as session:
        assert session["user_id"] == user.id


def test_email_is_normalized(tmp_path):
    app = make_app(tmp_path)
    app.test_client().post("/register", data=registration_data(email="  Student@Example.COM "))
    with app.app_context():
        assert db.session.scalar(db.select(User).where(User.email == "student@example.com"))


def test_duplicate_email_is_rejected_case_insensitively(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    client.post("/register", data=registration_data())
    signed_out_client = app.test_client()
    response = signed_out_client.post("/register", data=registration_data(email="STUDENT@example.com"))
    assert response.status_code == 200
    assert b"An account with that email already exists." in response.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 1


def test_invalid_email_shows_validation_message(tmp_path):
    response = make_app(tmp_path).test_client().post("/register", data=registration_data(email="not-an-email"))
    assert b"Enter a valid email address." in response.data


def test_short_password_shows_validation_message(tmp_path):
    response = make_app(tmp_path).test_client().post("/register", data=registration_data(password="short"))
    assert b"Password must be at least 8 characters." in response.data


def test_missing_display_name_shows_validation_message(tmp_path):
    response = make_app(tmp_path).test_client().post("/register", data=registration_data(display_name=" "))
    assert b"Display name is required." in response.data


def test_invalid_registration_does_not_create_user(tmp_path):
    app = make_app(tmp_path)
    app.test_client().post("/register", data=registration_data(password="bad"))
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_two_word_display_name_uses_word_initials(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    client.post("/register", data=registration_data(display_name="Adam Ressom"))
    response = client.get("/dashboard")
    assert b'aria-label="Open account menu for Adam Ressom"' in response.data
    assert b">AR</summary>" in response.data
    assert b"Create account</a>" not in response.data


def test_one_word_display_name_uses_first_two_letters(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    client.post("/register", data=registration_data(display_name="Adam"))
    response = client.get("/dashboard")
    assert b">AD</summary>" in response.data


def test_logout_clears_account_menu(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    client.post("/register", data=registration_data(display_name="Adam Ressom"))
    response = client.post("/logout", follow_redirects=True)
    assert b"Create account</a>" in response.data
    assert b"account-menu" not in response.data
