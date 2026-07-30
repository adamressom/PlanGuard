from datetime import datetime, time, timedelta, timezone

import click
from flask import current_app

from . import db
from .models import Assignment, User, WeeklyAvailability


def register_commands(app):
    @app.cli.command("seed-demo")
    @click.option("--email", default="demo@planguard.local", show_default=True)
    @click.option("--password", default="demo-password", show_default=True)
    @click.option("--force", is_flag=True, help="Allow seeding in the production environment.")
    def seed_demo(email, password, force):
        """Create an idempotent local demo account and sample workload."""
        if current_app.config.get("ENVIRONMENT") == "production" and not force:
            raise click.ClickException("Refusing to seed production without --force.")
        normalized_email = email.strip().lower()
        user = db.session.scalar(db.select(User).where(User.email == normalized_email))
        if user is None:
            user = User(
                email=normalized_email,
                display_name="Demo Student",
                available_study_minutes=120,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
        else:
            click.echo(f"Demo user {normalized_email} already exists; preserving it.")

        if not db.session.scalar(
            db.select(WeeklyAvailability).where(WeeklyAvailability.user_id == user.id)
        ):
            for weekday in range(5):
                db.session.add(WeeklyAvailability(
                    user_id=user.id,
                    weekday=weekday,
                    starts_at_time=time(9),
                    ends_at_time=time(17),
                    label="Demo study availability",
                ))

        if not db.session.scalar(
            db.select(Assignment).where(
                Assignment.user_id == user.id,
                Assignment.provider == "seed",
            )
        ):
            now = datetime.now(timezone.utc)
            db.session.add_all([
                Assignment(
                    user_id=user.id,
                    title="Calculus problem set",
                    course="MATH 201",
                    deadline=now + timedelta(days=2),
                    difficulty=4,
                    estimated_minutes=90,
                    course_weight=25,
                    progress=10,
                    provider="seed",
                    provider_id="demo-calculus",
                ),
                Assignment(
                    user_id=user.id,
                    title="History reading response",
                    course="HIST 110",
                    deadline=now + timedelta(days=4),
                    difficulty=2,
                    estimated_minutes=45,
                    course_weight=15,
                    progress=0,
                    provider="seed",
                    provider_id="demo-history",
                ),
            ])
        db.session.commit()
        click.echo(f"Demo data ready for {normalized_email}.")
