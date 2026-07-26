from planguard import create_app


def client(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}"})
    return app.test_client()


def test_landing_page(tmp_path):
    response = client(tmp_path).get("/")
    assert response.status_code == 200
    assert b"Study what matters" in response.data


def test_dashboard_page(tmp_path):
    response = client(tmp_path).get("/dashboard")
    assert response.status_code == 302
    assert "/login?next=/dashboard" in response.headers["Location"]


def test_health_endpoint(tmp_path):
    response = client(tmp_path).get("/api/health")
    assert response.json == {"app": "PlanGuard", "status": "ok"}
