# Standup notes

## Day 1 — Foundation

**Yesterday / completed:** Defined the value proposition, information architecture, data model, and visual direction. Scaffolded the application and isolated the ranking logic.

**Today / next:** Implement authentication and assignment CRUD, then connect real assignment data to the dashboard.

**Blockers / risks:** Google and Notion app credentials are not yet configured. OAuth redirect URLs must match the deployment host. The ranking weights need validation with students.

**Demo story:** A student opens PlanGuard, sees one clearly recommended task, understands why it ranks first, and starts a protected focus block even if an external API is temporarily unavailable.

## Issue #13 - Focus Session Progress Update

**Completed / added:** Vetted and implemented Tasks 10a through 16 against the current database-backed focus workflow. Active focus sessions now open a progress dialog before ending. The dialog uses synced range/number controls with `step="10"`, clamps browser-entered values from 0 to 100, and supports saving assignment progress without ending the focus session. `End focus only` confirms before ending without a progress update. Assignment progress saves and focus-session end responses now include refreshed ranked assignments for in-place queue updates. Added minimal dialog styling and focused service, route, and dashboard-contract tests.

**Task 17 verification:** Created a local `.venv`, installed pinned `requirements.txt` dependencies, and ran `.venv\Scripts\python -m pytest`. Full suite passed: 136 passed.

**Future notes:** The progress-only save path uses the existing assignment PATCH API and leaves the active focus session running unless the user confirms they are finished. A later UI pass can replace browser `confirm()` prompts with styled modal confirmations and can add fuller client-side tests for the in-place DOM refresh.

