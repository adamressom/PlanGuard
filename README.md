# PlanGuard

PlanGuard is a decision-first study planner. Instead of sorting work only by deadline, it considers urgency, difficulty, estimated effort, course impact, current progress, and available study time.

This repository is an intentionally lean hackathon scaffold: it runs, demonstrates the core idea, and leaves the OAuth and CRUD implementation as clear next steps.

## What is included

- Flask application factory and modular service layout
- SQLAlchemy models for users, assignments, progress, integration state, cache, and retries
- Explainable priority-scoring engine
- Landing page and interactive dashboard prototype
- Google Calendar and Notion integration boundaries with cached fallback behavior
- 10 unit/route tests
- Architecture diagram, Kanban board, and standup notes

## Quick start

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py run.py
```

Open `http://127.0.0.1:5000`. Run tests with `pytest`.

## Next build slice

1. Add authentication and assignment CRUD.
2. Configure Google Calendar and Notion OAuth using `.env.example`.
3. Persist provider responses in `IntegrationState.cached_payload` and add exponential retry jobs.
4. Turn scored assignments into calendar-sized focus blocks.

See [docs/architecture.md](docs/architecture.md) and [docs/project-board.md](docs/project-board.md).

