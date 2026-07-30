# UI terminology and text encoding

PlanGuard user-facing source files are UTF-8 without a byte-order mark. HTML
templates declare UTF-8 in the shared `<head>`. Use real Unicode punctuation and
symbols—such as `—`, `–`, `…`, `→`, `✓`, and `·`—instead of corrupted text or
numeric lookalikes.

Use these terms consistently:

- **Assignment:** coursework PlanGuard ranks and tracks. Do not switch between
  “assignment” and “task” in the same workflow.
- **Focus block:** a recommended or scheduled period of study time.
- **Focus session:** the active or historical timer created when a student starts
  studying.
- **Google Calendar:** the integration name. Use “Google Calendar data” when
  describing sync freshness or failures.
- **Notion:** the integration name. A selected database is an “assignment source.”
- **Connect:** begins an integration connection.
- **Sync calendar:** manually refreshes Google Calendar data.
- **Syncing, Synced, Using cached data, Error, Disconnected:** the canonical
  integration status labels.
- **Demo:** identifies simulated provider data; it is not a sync status.

Page titles use an em dash before `PlanGuard`. Time ranges use an en dash, and
supporting metadata uses a middle dot. Avoid hard-coded weekday or freshness
claims; copy must reflect actual application state.
