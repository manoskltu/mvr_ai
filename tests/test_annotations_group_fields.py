"""Tests for Task 2.3: Modified annotations GET and POST endpoints.

Tests:
- GET annotations returns group_id and group_color for grouped annotations
- GET annotations returns null for ungrouped annotations
- POST with group_id creates annotation assigned to group
- POST without group_id still works (backward compatibility)
- POST with non-existent group_id returns appropriate error
- POST with group_id from different attachment returns 400
"""

import uuid

import pytest

from app import create_app
from db_models import AnnotationGroupModel, AnnotationModel, AttachmentModel, EmailRecordModel, db


@pytest.fixture()
def app():
    """Create a Flask application instance for testing with in-memory SQLite."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    """Provide a Flask test client."""
    return app.test_client()


def _create_email_and_attachment(app):
    """Helper: create an email record with a PDF attachment, return attachment id."""
    with app.app_context():
        email = EmailRecordModel(
            id=str(uuid.uuid4()),
            sender="test@example.com",
            recipient="recv@example.com",
            subject="Test email",
            body_text="Body",
            source_file="test.eml",
        )
        db.session.add(email)
        db.session.flush()

        att = AttachmentModel(
            email_record_id=email.id,
            filename="drawing.pdf",
            content_type="application/pdf",
            file_path="/fake/path/drawing.pdf",
        )
        db.session.add(att)
        db.session.commit()
        return att.id


class TestGetAnnotationsGroupFields:
    """Test that GET /data/api/annotations/<att_id>/<page> includes group fields."""

    def test_get_annotations_returns_group_id_and_color_for_grouped(self, app, client):
        """Grouped annotations include group_id and group_color in response."""
        att_id = _create_email_and_attachment(app)

        # Create a group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Balkar",
            "color": "#e74c3c",
        })
        group_id = resp.get_json()["id"]

        # Create annotation assigned to group
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "group_id": group_id,
        })
        assert resp.status_code == 201

        # GET annotations for that page
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        assert resp.status_code == 200
        annotations = resp.get_json()
        assert len(annotations) == 1
        ann = annotations[0]
        assert ann["group_id"] == group_id
        assert ann["group_color"] == "#e74c3c"

    def test_get_annotations_returns_null_for_ungrouped(self, app, client):
        """Ungrouped annotations return null for group_id and group_color."""
        att_id = _create_email_and_attachment(app)

        # Create annotation without group
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.5,
            "y": 0.5,
            "width": 0.1,
            "height": 0.1,
        })
        assert resp.status_code == 201

        # GET annotations for that page
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        assert resp.status_code == 200
        annotations = resp.get_json()
        assert len(annotations) == 1
        ann = annotations[0]
        assert ann["group_id"] is None
        assert ann["group_color"] is None

    def test_get_annotations_mixed_grouped_and_ungrouped(self, app, client):
        """Page with both grouped and ungrouped annotations returns correct fields."""
        att_id = _create_email_and_attachment(app)

        # Create a group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Pelare",
            "color": "#27ae60",
        })
        group_id = resp.get_json()["id"]

        # Create grouped annotation
        client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 2,
            "x": 0.1,
            "y": 0.1,
            "width": 0.2,
            "height": 0.2,
            "group_id": group_id,
        })

        # Create ungrouped annotation
        client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 2,
            "x": 0.5,
            "y": 0.5,
            "width": 0.1,
            "height": 0.1,
        })

        # GET annotations for page 2
        resp = client.get(f"/data/api/annotations/{att_id}/2")
        assert resp.status_code == 200
        annotations = resp.get_json()
        assert len(annotations) == 2

        grouped = [a for a in annotations if a["group_id"] is not None]
        ungrouped = [a for a in annotations if a["group_id"] is None]

        assert len(grouped) == 1
        assert grouped[0]["group_color"] == "#27ae60"

        assert len(ungrouped) == 1
        assert ungrouped[0]["group_color"] is None


class TestCreateAnnotationWithGroupId:
    """Test that POST /data/api/annotations accepts optional group_id."""

    def test_create_with_group_id_assigns_annotation(self, app, client):
        """POST with valid group_id creates annotation assigned to that group."""
        att_id = _create_email_and_attachment(app)

        # Create group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Räcken",
            "color": "#9b59b6",
        })
        group_id = resp.get_json()["id"]

        # Create annotation with group_id
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.2,
            "y": 0.3,
            "width": 0.4,
            "height": 0.2,
            "group_id": group_id,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["group_id"] == group_id
        assert data["group_color"] == "#9b59b6"

    def test_create_without_group_id_backward_compatible(self, app, client):
        """POST without group_id still works (backward compatibility)."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["group_id"] is None
        assert data["group_color"] is None

    def test_create_with_null_group_id_backward_compatible(self, app, client):
        """POST with explicit group_id=null works (backward compatible)."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "group_id": None,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["group_id"] is None
        assert data["group_color"] is None

    def test_create_with_nonexistent_group_id_returns_404(self, app, client):
        """POST with non-existent group_id returns 404."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "group_id": 99999,
        })
        assert resp.status_code == 404
        data = resp.get_json()
        assert "not found" in data["error"].lower()

    def test_create_with_group_from_different_attachment_returns_400(self, app, client):
        """POST with group_id from a different attachment returns 400."""
        att_id_1 = _create_email_and_attachment(app)
        att_id_2 = _create_email_and_attachment(app)

        # Create group on attachment 1
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id_1,
            "name": "Group on Att 1",
        })
        group_id = resp.get_json()["id"]

        # Try to create annotation on attachment 2 with group from attachment 1
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id_2,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "group_id": group_id,
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "attachment" in data["error"].lower()
