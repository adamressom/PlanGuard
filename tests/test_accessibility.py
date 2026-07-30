from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def relative_luminance(hex_color):
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first, second):
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_shared_layout_has_navigation_landmarks_and_skip_link(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'class="skip-link" href="#main-content"' in response.data
    assert b'<nav aria-label="Primary navigation">' in response.data
    assert b'<main id="main-content" tabindex="-1">' in response.data


def test_dashboard_dialogs_have_accessible_names_and_descriptions(
    user_factory,
    assignment_factory,
    sign_in,
    app,
):
    user_id = user_factory()
    assignment_factory(user_id, title="Accessible assignment")
    client = sign_in(user_id)
    response = client.get("/dashboard")

    assert b'aria-labelledby="delete-dialog-title"' in response.data
    assert b'aria-describedby="delete-dialog-description"' in response.data
    assert b'aria-label="Delete Accessible assignment"' in response.data


def test_dialog_scripts_set_initial_focus_and_restore_trigger_focus():
    delete_script = (
        PROJECT_ROOT / "planguard" / "static" / "js" / "delete.js"
    ).read_text(encoding="utf-8")
    focus_script = (
        PROJECT_ROOT / "planguard" / "static" / "js" / "focus-timer.js"
    ).read_text(encoding="utf-8")

    assert "deleteDialog.querySelector('.cancel-button').focus()" in delete_script
    assert "deleteTrigger?.focus()" in delete_script
    assert "progressNumber?.focus()" in focus_script
    assert "progressDialog?.addEventListener('close'" in focus_script
    assert "endButton?.focus()" in focus_script


def test_accessibility_styles_cover_focus_motion_overflow_and_mobile_layout():
    styles = (
        PROJECT_ROOT / "planguard" / "static" / "css" / "accessibility.css"
    ).read_text(encoding="utf-8")

    assert ":focus-visible" in styles
    assert "outline: 3px solid var(--lime)" in styles
    assert "prefers-reduced-motion: reduce" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "@media (max-width: 700px)" in styles
    assert "min-height: 44px" in styles
    assert "grid-template-columns: 34px minmax(0, 1fr)" in styles


def test_primary_text_palette_meets_wcag_aa_contrast():
    background = "#090b13"

    assert contrast_ratio("#f5f5f0", background) >= 4.5
    assert contrast_ratio("#9ca3af", background) >= 4.5
    assert contrast_ratio("#c7ff4a", background) >= 4.5
