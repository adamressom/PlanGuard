# Automated tests

Install the pinned development dependencies and run the complete suite:

```powershell
py -m pip install -r requirements.txt
py -m pytest
```

Run the same branch-coverage gate used by CI:

```powershell
py -m pytest --cov=planguard --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=80
```

The terminal report identifies missing lines, `htmlcov/index.html` provides a
browsable local report, and `coverage.xml` is suitable for CI tooling.

Shared fixtures in `tests/conftest.py` provide an isolated SQLite application,
test client, authentication helper, and factories for users, assignments, and
integration states. Every test receives a new temporary database, so local and
CI runs do not depend on execution order or external services.

Google Calendar and Notion behavior is tested with demo clients or mocks. The
suite never needs live provider credentials or network access.
