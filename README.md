# PlanGuard

AI-powered planning and scheduling application.

PlanGuard is a decision-first study planner. Instead of sorting work only by deadline, it considers urgency, difficulty, estimated effort, course impact, current progress, and available study time.

This repository is an intentionally lean hackathon scaffold: it runs, demonstrates the core idea, and leaves the OAuth and CRUD implementation as clear next steps.

## What is included

- Flask application factory and modular service layout
- SQLAlchemy models for users, assignments, progress, integration state, cache, and retries
- Explainable priority-scoring engine
- Landing page and interactive dashboard prototype
- Google Calendar and Notion integration boundaries with cached fallback beha
vior
- User registration with validation, secure password hashing, and session sign-in
- Sign-in, sign-out, protected routes, and environment-aware session security
- User-scoped assignment and integration queries with non-revealing authorization errors
- Database-backed assignment form with ranking inputs and validation
- Assignment editing with shared validation and immediate priority recalculation
- Confirmed assignment deletion from the dashboard and detail view
- Inline progress updates, completion controls, and active/completed queues
- Deterministic database priority queue with top-pick and overdue states
- Account-level study availability with presets and time-fit explanations
- Per-assignment score breakdowns with deterministic plain-language explanations
- Persistent focus-session timer with pause, resume, completion, refresh recovery, and accessible controls
- User-scoped recent focus history with frozen completed durations
- 200+ unit, authentication, authorization, assignment, progress, ranking, availability, explanation, focus-session, integration, migration, security, and route tests
- Architecture diagram, Kanban board, and standup notes

## Quick start

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m flask --app run.py db upgrade
py run.py
```

See [database migrations](docs/migrations.md) for schema changes, production
deployment, existing databases, and optional demo data.

See [security and privacy](docs/security.md) for secret, CSRF, cookie, token
encryption, and authentication rate-limit configuration.

See [automated testing](docs/testing.md) for fixtures, coverage reports, and the
CI-equivalent test command.

See [accessibility and responsive checks](docs/accessibility.md) for automated
coverage and the keyboard, zoom, and viewport release checklist.

See [UI terminology and text encoding](docs/ui-terminology.md) for canonical
interface terms, status labels, punctuation, and the UTF-8 source policy.

See [dashboard state rules](docs/dashboard-states.md) for onboarding, loading,
cached fallback, errors, overdue work, completed work, and calm-plan behavior.

See [Google Calendar integration](docs/google-calendar.md) for the demo and
future live OAuth configuration.

See [Notion assignment imports](docs/notion.md) for demo and live source
mapping configuration.

See the [versioned JSON API](docs/api.md) for endpoint and response
conventions.
