# PlanGuard

AI-powered planning and scheduling application.

PlanGuard is a decision-first study planner. Instead of sorting work only by deadline, it considers urgency, difficulty, estimated effort, course impact, current progress, and available study time.

This repository is an intentionally lean hackathon scaffold: it runs, demonstrates the core idea, and leaves the OAuth and CRUD implementation as clear next steps.

## What is included

- Flask application factory and modular service layout
- SQLAlchemy models for users, assignments, progress, integration state, cache, and retries
- Explainable priority-scoring engine
- Landing page and interactive dashboard prototype
- Google Calendar and Notion integration boundaries with cached fallback behavior
- 10 unit and route tests
- Architecture diagram, Kanban board, and standup notes

## Quick start

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py run.py