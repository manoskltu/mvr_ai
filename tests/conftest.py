"""Pytest fixtures for the MVR Offer Tool test suite."""

import pytest

from app import create_app
from db_models import db


@pytest.fixture()
def app():
    """Create a Flask application instance for testing with in-memory SQLite."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    # Re-initialize the database with the test config
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Provide a Flask test client."""
    return app.test_client()
