# Standup notes

## Adam R.

## Day 1 - Foundation

**Yesterday / completed:** Defined the value proposition, information architecture, data model, and visual direction. Scaffolded the application and isolated the ranking logic.

**Today / next:** Implement authentication and assignment CRUD, then connect real assignment data to the dashboard.

**Blockers / risks:** Google and Notion app credentials are not yet configured. OAuth redirect URLs must match the deployment host. The ranking weights need validation with students.

**Demo story:** A student opens PlanGuard, sees one clearly recommended task, understands why it ranks first, and starts a protected focus block even if an external API is temporarily unavailable.

# Stand Up 25/7/2026

## Josh P.

**Yesterday / completed:** Vetted and implemented Issue #13 Tasks 10a through 16 against the current database-backed focus workflow. Active focus sessions now open a progress dialog before ending. The dialog uses synced range/number controls with `step="10"`, clamps browser-entered values from 0 to 100, and supports saving assignment progress without ending the focus session. `End focus only` confirms before ending without a progress update. Assignment progress saves and focus-session end responses now include refreshed ranked assignments for in-place queue updates. Added minimal dialog styling and focused service, route, and dashboard-contract tests.

**Today / next:** Continue with the next vetted task after the focus-session progress workflow. Consider replacing browser `confirm()` prompts with styled modal confirmations and adding fuller client-side coverage for in-place DOM refresh behavior.

**Blockers / risks:** None for Issue #13 after local setup. A local `.venv` is required for tests because the global Python environment did not have Flask/SQLAlchemy installed.

**Demo story:** A student starts a focus block, chooses to update assignment progress in 10% increments, can keep working after saving progress, or can intentionally end the session without changing assignment progress.

**Verification:** Created a local `.venv`, installed pinned `requirements.txt` dependencies, and ran `.venv\Scripts\python -m pytest`. Full suite passed: 136 passed.
