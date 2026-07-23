from flask import g

from .. import db


def owned_records(model):
    """Build a query that can only return the signed-in user's records."""
    return db.select(model).where(model.user_id == g.user.id)


def get_owned_record(model, record_id):
    """Return a record only when it belongs to the signed-in user."""
    return db.session.scalar(
        owned_records(model).where(model.id == record_id)
    )
