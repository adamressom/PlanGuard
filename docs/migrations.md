# Database migrations

PlanGuard uses Flask-Migrate and Alembic to version its database schema. Application
startup does not create or alter production tables.

## Local setup

Set `DATABASE_URL` if you do not want the default instance-local SQLite database,
then apply every migration:

```powershell
$env:DATABASE_URL = "sqlite:///planguard.db"
py -m flask --app run.py db upgrade
```

Start the app only after the upgrade succeeds:

```powershell
py run.py
```

SQLite is convenient locally. Production can use another SQLAlchemy connection URL,
for example `postgresql+psycopg://user:password@host/database`, with its database
driver installed in the deployment environment.

## Schema changes

After changing SQLAlchemy models, generate and review a revision before applying it:

```powershell
py -m flask --app run.py db migrate -m "Describe the schema change"
py -m flask --app run.py db upgrade
```

Useful inspection and rollback commands are:

```powershell
py -m flask --app run.py db current
py -m flask --app run.py db history
py -m flask --app run.py db downgrade -1
```

Commit the reviewed file under `migrations/` with the model change. Deployments
should run `db upgrade` as a release step before starting the new application
version.

## Existing unversioned databases

Back up the database first. If an existing database already matches the initial
revision exactly, mark it as current without recreating tables:

```powershell
py -m flask --app run.py db stamp e55592f151e2
```

Do not stamp a partially matching schema. Compare it with the initial migration or
migrate a copy first.

## Optional demo data

After upgrading a local database, create an idempotent demo account and sample
assignments:

```powershell
py -m flask --app run.py seed-demo
```

The defaults are `demo@planguard.local` and `demo-password`. Override them with
`--email` and `--password`. Seeding is refused when the configured environment is
production unless `--force` is explicitly supplied.
