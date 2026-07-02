"""Integration tests for the Plan annotation API.

Tests:
- Cascade delete: annotations removed when attachment deleted
- Full CRUD flow: create → get → update → delete
- Page isolation: annotations on page 1 don't appear on page 2
"""

import uuid

import pytest

from app import create_app
from db_models import AnnotationModel, AttachmentModel, EmailRecordModel, db


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
        return att.id, email.id


class TestCascadeDelete:
    """Task 11.1: Verify cascade delete removes annotations when attachment deleted."""

    def test_cascade_delete_removes_annotations(self, app, client):
        att_id, email_id = _create_email_and_attachment(app)

        # Create annotations for this attachment
        ann_data = {
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        }
        resp = client.post("/data/api/annotations", json=ann_data)
        assert resp.status_code == 201
        ann_id = resp.get_json()["id"]

        # Verify annotation exists
        with app.app_context():
            ann = db.session.get(AnnotationModel, ann_id)
            assert ann is not None

        # Delete the attachment using raw SQL to trigger DB-level cascade
        with app.app_context():
            from sqlalchemy import text
            db.session.execute(text("PRAGMA foreign_keys = ON"))
            db.session.execute(
                text("DELETE FROM attachments WHERE id = :id"),
                {"id": att_id},
            )
            db.session.commit()

            # Verify annotation is gone (cascade delete)
            ann = db.session.get(AnnotationModel, ann_id)
            assert ann is None


class TestAnnotationCRUD:
    """Task 11.2: End-to-end CRUD integration test."""

    def test_full_crud_flow(self, app, client):
        att_id, _ = _create_email_and_attachment(app)

        # POST - Create annotation
        ann_data = {
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        }
        resp = client.post("/data/api/annotations", json=ann_data)
        assert resp.status_code == 201
        created = resp.get_json()
        ann_id = created["id"]
        assert created["x"] == 0.1
        assert created["y"] == 0.2
        assert created["width"] == 0.3
        assert created["height"] == 0.4

        # GET - Retrieve annotations for page
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        assert resp.status_code == 200
        annotations = resp.get_json()
        assert len(annotations) == 1
        assert annotations[0]["id"] == ann_id

        # PUT - Update annotation
        update_data = {"x": 0.5, "y": 0.6, "width": 0.2, "height": 0.1}
        resp = client.put(f"/data/api/annotations/{ann_id}", json=update_data)
        assert resp.status_code == 200
        updated = resp.get_json()
        assert updated["x"] == 0.5
        assert updated["y"] == 0.6
        assert updated["width"] == 0.2
        assert updated["height"] == 0.1

        # Verify update via GET
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        annotations = resp.get_json()
        assert annotations[0]["x"] == 0.5

        # DELETE - Remove annotation
        resp = client.delete(f"/data/api/annotations/{ann_id}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        # Verify deletion via GET
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        assert resp.get_json() == []

    def test_page_isolation(self, app, client):
        """Annotations on page 1 don't appear when querying page 2."""
        att_id, _ = _create_email_and_attachment(app)

        # Create annotation on page 1
        ann_page1 = {
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        }
        resp = client.post("/data/api/annotations", json=ann_page1)
        assert resp.status_code == 201
        page1_id = resp.get_json()["id"]

        # Create annotation on page 2
        ann_page2 = {
            "attachment_id": att_id,
            "page_number": 2,
            "x": 0.5,
            "y": 0.6,
            "width": 0.2,
            "height": 0.1,
        }
        resp = client.post("/data/api/annotations", json=ann_page2)
        assert resp.status_code == 201
        page2_id = resp.get_json()["id"]

        # Query page 1 - should only see page 1 annotation
        resp = client.get(f"/data/api/annotations/{att_id}/1")
        page1_annotations = resp.get_json()
        assert len(page1_annotations) == 1
        assert page1_annotations[0]["id"] == page1_id

        # Query page 2 - should only see page 2 annotation
        resp = client.get(f"/data/api/annotations/{att_id}/2")
        page2_annotations = resp.get_json()
        assert len(page2_annotations) == 1
        assert page2_annotations[0]["id"] == page2_id

    def test_create_annotation_invalid_data_returns_400(self, app, client):
        """POST with invalid data returns 400."""
        att_id, _ = _create_email_and_attachment(app)

        # Missing required field
        resp = client.post("/data/api/annotations", json={"attachment_id": att_id})
        assert resp.status_code == 400

        # Coordinate out of range
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 1.5,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        })
        assert resp.status_code == 400

    def test_update_nonexistent_returns_404(self, client):
        """PUT to non-existent annotation returns 404."""
        resp = client.put("/data/api/annotations/99999", json={"x": 0.5})
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        """DELETE non-existent annotation returns 404."""
        resp = client.delete("/data/api/annotations/99999")
        assert resp.status_code == 404
