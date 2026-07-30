from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
UI_ROOTS = (
    PROJECT_ROOT / "planguard" / "templates",
    PROJECT_ROOT / "planguard" / "static",
)
TEXT_EXTENSIONS = {".html", ".css", ".js"}
MOJIBAKE_MARKERS = (
    "\u00c3",
    "\u00c2",
    "\u00e2",
    "\ufffd",
)


def ui_files():
    return [
        path
        for root in UI_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix in TEXT_EXTENSIONS
    ]


def test_ui_source_files_are_utf8_without_bom_or_mojibake():
    for path in ui_files():
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path} contains a UTF-8 BOM"
        text = raw.decode("utf-8")
        assert not any(marker in text for marker in MOJIBAKE_MARKERS), (
            f"{path} contains a common mojibake marker"
        )


def test_page_titles_use_the_preferred_separator():
    for path in (PROJECT_ROOT / "planguard" / "templates").glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert " - PlanGuard" not in text


def test_landing_and_dashboard_use_canonical_copy(client, user_factory, sign_in):
    landing = client.get("/")
    assert "Resilient sync".encode() in landing.data
    assert "focus session".encode() in landing.data

    user_id = user_factory()
    dashboard = sign_in(user_id).get("/dashboard")
    assert b"Your command center" in dashboard.data
    assert b"Ranked now" in dashboard.data
    assert b"Tuesday" not in dashboard.data
    assert b"Start focus session" in dashboard.data


def test_google_calendar_copy_uses_canonical_data_and_action_terms(
    user_factory,
    integration_factory,
    sign_in,
):
    user_id = user_factory()
    integration_factory(
        user_id,
        sync_status="error",
        last_error_code="provider_unavailable",
    )
    response = sign_in(user_id).get("/dashboard")

    assert b"Google Calendar data could not be updated" in response.data
    assert b"Sync calendar" in response.data
