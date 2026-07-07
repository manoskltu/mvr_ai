"""Integration tests for the Groups CRUD API (Task 2.1).

Tests:
- Group CRUD: create → get → update → delete
- Validation: empty name, duplicate name, invalid color
- Display order auto-assignment
- 404 for non-existent resources
- Annotation count in group response
- Group deletion unassigns annotations
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


class TestGroupCRUD:
    """Test full CRUD operations on groups."""

    def test_create_group_with_defaults(self, app, client):
        """POST creates a group with default color and auto display_order."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Balkar",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Balkar"
        assert data["color"] == "#3498db"
        assert data["display_order"] == 1
        assert data["annotation_count"] == 0
        assert data["attachment_id"] == att_id
        assert "id" in data

    def test_create_group_with_custom_color(self, app, client):
        """POST creates a group with specified color."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Pelare",
            "color": "#e74c3c",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["color"] == "#e74c3c"

    def test_get_groups_ordered_by_display_order(self, app, client):
        """GET returns groups sorted by display_order."""
        att_id = _create_email_and_attachment(app)

        # Create 3 groups
        client.post("/data/api/groups", json={"attachment_id": att_id, "name": "A"})
        client.post("/data/api/groups", json={"attachment_id": att_id, "name": "B"})
        client.post("/data/api/groups", json={"attachment_id": att_id, "name": "C"})

        resp = client.get(f"/data/api/groups/{att_id}")
        assert resp.status_code == 200
        groups = resp.get_json()
        assert len(groups) == 3
        assert groups[0]["name"] == "A"
        assert groups[1]["name"] == "B"
        assert groups[2]["name"] == "C"
        assert groups[0]["display_order"] < groups[1]["display_order"] < groups[2]["display_order"]

    def test_get_groups_attachment_not_found(self, client):
        """GET returns 404 for non-existent attachment."""
        resp = client.get("/data/api/groups/99999")
        assert resp.status_code == 404

    def test_update_group_name(self, app, client):
        """PUT updates group name."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Original",
        })
        group_id = resp.get_json()["id"]

        resp = client.put(f"/data/api/groups/{group_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Updated"

    def test_update_group_color(self, app, client):
        """PUT updates group color."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Test",
        })
        group_id = resp.get_json()["id"]

        resp = client.put(f"/data/api/groups/{group_id}", json={"color": "#ff0000"})
        assert resp.status_code == 200
        assert resp.get_json()["color"] == "#ff0000"

    def test_update_nonexistent_group_returns_404(self, client):
        """PUT returns 404 for non-existent group."""
        resp = client.put("/data/api/groups/99999", json={"name": "X"})
        assert resp.status_code == 404

    def test_delete_group(self, app, client):
        """DELETE removes a group and returns success."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "ToDelete",
        })
        group_id = resp.get_json()["id"]

        resp = client.delete(f"/data/api/groups/{group_id}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        # Verify group is gone
        resp = client.get(f"/data/api/groups/{att_id}")
        assert len(resp.get_json()) == 0

    def test_delete_nonexistent_group_returns_404(self, client):
        """DELETE returns 404 for non-existent group."""
        resp = client.delete("/data/api/groups/99999")
        assert resp.status_code == 404

    def test_delete_group_unassigns_annotations(self, app, client):
        """Deleting a group sets group_id to null on assigned annotations."""
        att_id = _create_email_and_attachment(app)

        # Create group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "GroupX",
        })
        group_id = resp.get_json()["id"]

        # Create annotation and assign it to the group
        ann_resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        })
        ann_id = ann_resp.get_json()["id"]

        # Manually assign annotation to group
        with app.app_context():
            ann = db.session.get(AnnotationModel, ann_id)
            ann.group_id = group_id
            db.session.commit()

        # Delete group
        resp = client.delete(f"/data/api/groups/{group_id}")
        assert resp.status_code == 200

        # Verify annotation still exists but group_id is null
        with app.app_context():
            ann = db.session.get(AnnotationModel, ann_id)
            assert ann is not None
            assert ann.group_id is None


class TestGroupValidation:
    """Test validation logic for group creation/update."""

    def test_create_group_empty_name_returns_400(self, app, client):
        """POST with empty name returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "",
        })
        assert resp.status_code == 400
        assert "empty" in resp.get_json()["error"].lower()

    def test_create_group_whitespace_name_returns_400(self, app, client):
        """POST with whitespace-only name returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "   ",
        })
        assert resp.status_code == 400

    def test_create_group_duplicate_name_returns_400(self, app, client):
        """POST with duplicate name for same attachment returns 400."""
        att_id = _create_email_and_attachment(app)

        client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Duplicate",
        })
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Duplicate",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_create_group_invalid_color_returns_400(self, app, client):
        """POST with invalid color format returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Test",
            "color": "red",
        })
        assert resp.status_code == 400
        assert "color" in resp.get_json()["error"].lower()

    def test_create_group_nonexistent_attachment_returns_404(self, client):
        """POST with non-existent attachment_id returns 404."""
        resp = client.post("/data/api/groups", json={
            "attachment_id": 99999,
            "name": "Test",
        })
        assert resp.status_code == 404

    def test_update_group_duplicate_name_returns_400(self, app, client):
        """PUT with name that already exists for same attachment returns 400."""
        att_id = _create_email_and_attachment(app)

        client.post("/data/api/groups", json={"attachment_id": att_id, "name": "A"})
        resp = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "B"})
        group_b_id = resp.get_json()["id"]

        # Try to rename B to A
        resp = client.put(f"/data/api/groups/{group_b_id}", json={"name": "A"})
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_update_group_same_name_allowed(self, app, client):
        """PUT with the group's own current name should succeed (not a duplicate)."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Keep"})
        group_id = resp.get_json()["id"]

        resp = client.put(f"/data/api/groups/{group_id}", json={"name": "Keep"})
        assert resp.status_code == 200

    def test_update_group_invalid_color_returns_400(self, app, client):
        """PUT with invalid color returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "X"})
        group_id = resp.get_json()["id"]

        resp = client.put(f"/data/api/groups/{group_id}", json={"color": "#GGG"})
        assert resp.status_code == 400


class TestGroupAnnotationCount:
    """Test that annotation_count is correctly reported."""

    def test_annotation_count_reflects_assigned_annotations(self, app, client):
        """Group annotation_count matches actual assigned annotations."""
        att_id = _create_email_and_attachment(app)

        # Create group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Counter",
        })
        group_id = resp.get_json()["id"]

        # Create 2 annotations and assign to group
        for i in range(2):
            client.post("/data/api/annotations", json={
                "attachment_id": att_id,
                "page_number": 1,
                "x": 0.1 * (i + 1),
                "y": 0.2,
                "width": 0.1,
                "height": 0.1,
            })

        with app.app_context():
            anns = AnnotationModel.query.filter_by(attachment_id=att_id).all()
            for ann in anns:
                ann.group_id = group_id
            db.session.commit()

        # Verify count in GET response
        resp = client.get(f"/data/api/groups/{att_id}")
        groups = resp.get_json()
        assert groups[0]["annotation_count"] == 2


class TestDisplayOrder:
    """Test auto-assigned display_order."""

    def test_sequential_creation_increments_order(self, app, client):
        """Each new group gets a higher display_order."""
        att_id = _create_email_and_attachment(app)

        r1 = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "First"})
        r2 = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Second"})
        r3 = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Third"})

        assert r1.get_json()["display_order"] == 1
        assert r2.get_json()["display_order"] == 2
        assert r3.get_json()["display_order"] == 3


class TestAnnotationGroupAssignment:
    """Test the PATCH /data/api/annotations/<id>/group endpoint."""

    def test_assign_annotation_to_group(self, app, client):
        """PATCH assigns an annotation to a group and returns annotation with group data."""
        att_id = _create_email_and_attachment(app)

        # Create group
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Assign Group",
            "color": "#e74c3c",
        })
        group_id = resp.get_json()["id"]

        # Create annotation
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
        })
        ann_id = resp.get_json()["id"]

        # Assign annotation to group
        resp = client.patch(f"/data/api/annotations/{ann_id}/group", json={
            "group_id": group_id,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == ann_id
        assert data["group_id"] == group_id
        assert data["group_color"] == "#e74c3c"
        assert data["attachment_id"] == att_id
        assert data["page_number"] == 1
        assert data["x"] == 0.1
        assert data["y"] == 0.2
        assert data["width"] == 0.3
        assert data["height"] == 0.2

    def test_unassign_annotation_from_group(self, app, client):
        """PATCH with group_id=null unassigns annotation from group."""
        att_id = _create_email_and_attachment(app)

        # Create group and annotation
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id,
            "name": "Unassign Group",
            "color": "#27ae60",
        })
        group_id = resp.get_json()["id"]

        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.5,
            "y": 0.5,
            "width": 0.1,
            "height": 0.1,
        })
        ann_id = resp.get_json()["id"]

        # Assign first
        client.patch(f"/data/api/annotations/{ann_id}/group", json={
            "group_id": group_id,
        })

        # Now unassign
        resp = client.patch(f"/data/api/annotations/{ann_id}/group", json={
            "group_id": None,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["group_id"] is None
        assert data["group_color"] is None

    def test_assign_nonexistent_annotation_returns_404(self, client):
        """PATCH with non-existent annotation_id returns 404."""
        resp = client.patch("/data/api/annotations/99999/group", json={
            "group_id": 1,
        })
        assert resp.status_code == 404

    def test_assign_nonexistent_group_returns_404(self, app, client):
        """PATCH with non-existent group_id returns 404."""
        att_id = _create_email_and_attachment(app)

        # Create annotation
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        })
        ann_id = resp.get_json()["id"]

        # Try to assign to non-existent group
        resp = client.patch(f"/data/api/annotations/{ann_id}/group", json={
            "group_id": 99999,
        })
        assert resp.status_code == 404

    def test_assign_group_from_different_attachment_returns_400(self, app, client):
        """PATCH with group_id from a different attachment returns 400."""
        att_id_1 = _create_email_and_attachment(app)
        att_id_2 = _create_email_and_attachment(app)

        # Create group on attachment 1
        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id_1,
            "name": "Group on Att 1",
        })
        group_id = resp.get_json()["id"]

        # Create annotation on attachment 2
        resp = client.post("/data/api/annotations", json={
            "attachment_id": att_id_2,
            "page_number": 1,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
        })
        ann_id = resp.get_json()["id"]

        # Try to assign annotation (att 2) to group (att 1) — should fail
        resp = client.patch(f"/data/api/annotations/{ann_id}/group", json={
            "group_id": group_id,
        })
        assert resp.status_code == 400
        assert "attachment" in resp.get_json()["error"].lower()
