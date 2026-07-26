# Standup notes

## Day 1 — Foundation

**Yesterday / completed:** Defined the value proposition, information architecture, data model, and visual direction. Scaffolded the application and isolated the ranking logic.

**Today / next:** Implement authentication and assignment CRUD, then connect real assignment data to the dashboard.

**Blockers / risks:** Google and Notion app credentials are not yet configured. OAuth redirect URLs must match the deployment host. The ranking weights need validation with students.

**Demo story:** A student opens PlanGuard, sees one clearly recommended task, understands why it ranks first, and starts a protected focus block even if an external API is temporarily unavailable.

## Issue #13 - Focus Session Progress Update

**Completed / added:** Vetted and implemented the demo-safe foundation through Task 9. The dashboard now uses a swappable `get_assignments_for_dashboard()` helper, demo assignments have stable IDs, progress overrides can be stored in the Flask session, and `/api/focus-sessions/end` supports ending a linked focus session with or without a progress value. Added strict assignment progress service errors/helpers for invalid progress and missing assignments. The dashboard now passes the top recommendation into the focus card, includes assignment data hooks, and renders a post-focus progress dialog. The focus button flow is now `Begin focus` -> `Finish focus` -> progress dialog.

**Still needed to complete #13:** Task 10a syncs the progress slider and number input. Task 10 submits saved progress from the dialog. Task 11 supports finishing without changes from the dialog. Task 12 refreshes the priority queue/recommended focus card after the API response. Task 13 adds minimal styling for the progress dialog controls. Task 14 adds service tests. Task 15 adds route tests. Task 16 verifies the dashboard exposes the workflow. Task 17 runs the test suite and records any environment limits.

**Future notes:** Demo progress is intentionally stored in session for now so the app can later swap `get_assignments_for_dashboard()` to database-backed assignments without rewriting the frontend contract. Later assignment progress should support checklist/subtask-derived completion, and the dashboard should handle empty assignment states before reading the first recommendation.

