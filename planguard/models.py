from datetime import datetime, timezone

from . import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    assignments = db.relationship("Assignment", backref="owner", lazy=True)


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    difficulty = db.Column(db.Integer, nullable=False, default=3)
    estimated_minutes = db.Column(db.Integer, nullable=False, default=60)
    course_weight = db.Column(db.Float, nullable=False, default=10)
    progress = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class IntegrationState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    provider = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="disconnected")
    last_synced_at = db.Column(db.DateTime)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    cached_payload = db.Column(db.JSON)

