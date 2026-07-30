from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    available_study_minutes = db.Column(db.Integer, nullable=False, default=120)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    assignments = db.relationship("Assignment", backref="owner", lazy=True)
    focus_sessions = db.relationship("FocusSession", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        words = self.display_name.split()
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return f"{words[0][0]}{words[1][0]}".upper()


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
    notes = db.Column(db.Text, nullable=False, default="")
    provider = db.Column(db.String(40), nullable=False, default="manual")
    provider_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def course_impact(self):
        return self.course_weight

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "provider",
            "provider_id",
            name="uq_assignment_user_provider_id",
        ),
    )


class WeeklyAvailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)
    starts_at_time = db.Column(db.Time, nullable=False)
    ends_at_time = db.Column(db.Time, nullable=False)
    label = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AvailabilityOverride(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    starts_at_time = db.Column(db.Time, nullable=False)
    ends_at_time = db.Column(db.Time, nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="available")
    label = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ScheduledFocusBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignment.id"), nullable=False, index=True)
    starts_at = db.Column(db.DateTime, nullable=True, index=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    planned_minutes = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="scheduled", index=True)
    source = db.Column(db.String(40), nullable=False, default="recommended")
    note = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    assignment = db.relationship("Assignment")


class IntegrationState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    provider = db.Column(db.String(40), nullable=False)
    mode = db.Column(db.String(20))
    status = db.Column(db.String(30), nullable=False, default="disconnected")
    provider_account_id = db.Column(db.String(255))
    provider_account_email = db.Column(db.String(255))
    granted_scopes = db.Column(db.JSON)
    last_error_code = db.Column(db.String(80))
    connected_at = db.Column(db.DateTime)
    last_synced_at = db.Column(db.DateTime)
    last_sync_attempt_at = db.Column(db.DateTime)
    sync_status = db.Column(db.String(20), nullable=False, default="never")
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    cached_payload = db.Column(db.JSON)
    credential = db.relationship(
        "OAuthCredential",
        backref="integration",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "provider", name="uq_integration_user_provider"),
    )


class OAuthCredential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_state.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    encrypted_access_token = db.Column(db.Text)
    encrypted_refresh_token = db.Column(db.Text)
    access_token_expires_at = db.Column(db.DateTime)
    token_type = db.Column(db.String(30), nullable=False, default="Bearer")
    encryption_key_version = db.Column(db.String(30), nullable=False, default="v1")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class NotionImportSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("integration_state.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    data_source_id = db.Column(db.String(255), nullable=False)
    source_name = db.Column(db.String(255), nullable=False)
    property_schema = db.Column(db.JSON, nullable=False, default=dict)
    property_mapping = db.Column(db.JSON, nullable=False, default=dict)
    last_imported_at = db.Column(db.DateTime)
    last_summary = db.Column(db.JSON)
    selected_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    integration = db.relationship(
        "IntegrationState",
        backref=db.backref("notion_source", uselist=False, cascade="all, delete-orphan"),
    )


class FocusSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignment.id"), nullable=True, index=True)
    assignment_title = db.Column(db.String(180), nullable=False)
    planned_minutes = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="running", index=True)
    accumulated_seconds = db.Column(db.Integer, nullable=False, default=0)
    completed_seconds = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_resumed_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
