from datetime import datetime, timedelta, timezone

import pytest

from planguard import create_app, db
from planguard.models import Assignment, IntegrationState, User


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "shared-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "GOOGLE_CALENDAR_MODE": "demo",
        "NOTION_MODE": "demo",
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user_factory(app):
    created = []

    def create_user(
        email=None,
        display_name="Test Student",
        password="password123",
        **values,
    ):
        with app.app_context():
            sequence = len(created) + 1
            user = User(
                email=email or f"student{sequence}@example.com",
                display_name=display_name,
                **values,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            created.append(user.id)
            return user.id

    return create_user


@pytest.fixture
def assignment_factory(app):
    created = []

    def create_assignment(user_id, **values):
        with app.app_context():
            sequence = len(created) + 1
            assignment = Assignment(
                user_id=user_id,
                title=values.pop("title", f"Test assignment {sequence}"),
                course=values.pop("course", "TEST 101"),
                deadline=values.pop(
                    "deadline",
                    datetime.now(timezone.utc) + timedelta(days=3),
                ),
                difficulty=values.pop("difficulty", 3),
                estimated_minutes=values.pop("estimated_minutes", 60),
                course_weight=values.pop("course_weight", 20),
                progress=values.pop("progress", 0),
                completed=values.pop("completed", False),
                **values,
            )
            db.session.add(assignment)
            db.session.commit()
            created.append(assignment.id)
            return assignment.id

    return create_assignment


@pytest.fixture
def integration_factory(app):
    created = []

    def create_integration(user_id, provider="google_calendar", **values):
        with app.app_context():
            integration = IntegrationState(
                user_id=user_id,
                provider=provider,
                mode=values.pop("mode", "demo"),
                status=values.pop("status", "connected"),
                sync_status=values.pop("sync_status", "never"),
                **values,
            )
            db.session.add(integration)
            db.session.commit()
            created.append(integration.id)
            return integration.id

    return create_integration


@pytest.fixture
def sign_in(client):
    def authenticate(user_id):
        with client.session_transaction() as session:
            session["user_id"] = user_id
        return client

    return authenticate
