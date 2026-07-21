"""Integration tests for Exclusion Zone CRUD, Group Merge, and Quantity Override (Tasks 7.1-7.3).

Tests:
- Exclusion Zone: create, list, delete, validation
- Group Merge: move annotations, delete source, validation
- Quantity Override: update, effective_quantity computation, GET includes fields
"""

import uuid

import pytest

from app import create_app
from db_models import AnnotationGroupModel, AnnotationModel, AttachmentModel, EmailRecordModel, ExclusionZoneModel, db


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


class TestExclusionZoneCRUD:
    """Test exclusion zone CRUD operations."""

    def test_create_exclusion_zone(self, app, client):
        """POST creates an exclusion zone and returns 201 with id."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.75,
            "y": 0.85,
            "width": 0.25,
            "height": 0.15,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "id" in data
        assert data["x"] == 0.75
        assert data["y"] == 0.85
        assert data["width"] == 0.25
        assert data["height"] == 0.15

    def test_list_exclusion_zones(self, app, client):
        """GET returns zones for the specified page."""
        att_id = _create_email_and_attachment(app)

        # Create two zones on page 1
        client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 1,
            "x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1,
        })
        client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 1,
            "x": 0.5, "y": 0.5, "width": 0.2, "height": 0.2,
        })
        # Create one zone on page 2
        client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 2,
            "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.1,
        })

        resp = client.get(f"/data/api/exclusion-zones/{att_id}/1")
        assert resp.status_code == 200
        zones = resp.get_json()
        assert len(zones) == 2

        resp = client.get(f"/data/api/exclusion-zones/{att_id}/2")
        assert resp.status_code == 200
        zones = resp.get_json()
        assert len(zones) == 1

    def test_list_exclusion_zones_empty_page(self, app, client):
        """GET returns empty array for page with no zones."""
        att_id = _create_email_and_attachment(app)

        resp = client.get(f"/data/api/exclusion-zones/{att_id}/5")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_exclusion_zones_attachment_not_found(self, client):
        """GET returns 404 for non-existent attachment."""
        resp = client.get("/data/api/exclusion-zones/99999/1")
        assert resp.status_code == 404

    def test_delete_exclusion_zone(self, app, client):
        """DELETE removes the zone and returns success."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 1,
            "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4,
        })
        zone_id = resp.get_json()["id"]

        resp = client.delete(f"/data/api/exclusion-zones/{zone_id}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        # Verify gone
        resp = client.get(f"/data/api/exclusion-zones/{att_id}/1")
        assert resp.get_json() == []

    def test_delete_nonexistent_zone_returns_404(self, client):
        """DELETE returns 404 for non-existent zone."""
        resp = client.delete("/data/api/exclusion-zones/99999")
        assert resp.status_code == 404

    def test_create_zone_missing_field_returns_400(self, app, client):
        """POST with missing field returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id,
            "page_number": 1,
            "x": 0.5,
            # missing y, width, height
        })
        assert resp.status_code == 400

    def test_create_zone_invalid_coordinates_returns_400(self, app, client):
        """POST with coordinates out of [0, 1] range returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 1,
            "x": 1.5, "y": 0.5, "width": 0.1, "height": 0.1,
        })
        assert resp.status_code == 400

    def test_create_zone_invalid_page_number_returns_400(self, app, client):
        """POST with page_number < 1 returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": att_id, "page_number": 0,
            "x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1,
        })
        assert resp.status_code == 400

    def test_create_zone_nonexistent_attachment_returns_404(self, client):
        """POST with non-existent attachment returns 404."""
        resp = client.post("/data/api/exclusion-zones", json={
            "attachment_id": 99999, "page_number": 1,
            "x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1,
        })
        assert resp.status_code == 404


class TestGroupMerge:
    """Test group merge endpoint."""

    def test_merge_moves_annotations_and_deletes_source(self, app, client):
        """POST /merge moves annotations from source to target and deletes source."""
        att_id = _create_email_and_attachment(app)

        # Create two groups
        r1 = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Target"})
        target_id = r1.get_json()["id"]
        r2 = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Source"})
        source_id = r2.get_json()["id"]

        # Create annotations in both groups
        with app.app_context():
            for i in range(3):
                ann = AnnotationModel(
                    attachment_id=att_id, page_number=1,
                    x=0.1 * i, y=0.1, width=0.05, height=0.05,
                    group_id=source_id,
                )
                db.session.add(ann)
            for i in range(2):
                ann = AnnotationModel(
                    attachment_id=att_id, page_number=1,
                    x=0.5 + 0.1 * i, y=0.1, width=0.05, height=0.05,
                    group_id=target_id,
                )
                db.session.add(ann)
            db.session.commit()

        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": source_id,
            "target_group_id": target_id,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == target_id
        assert data["annotation_count"] == 5  # 3 + 2

        # Verify source group is deleted
        with app.app_context():
            assert db.session.get(AnnotationGroupModel, source_id) is None

        # Verify all annotations now belong to target
        with app.app_context():
            anns = AnnotationModel.query.filter_by(attachment_id=att_id).all()
            for ann in anns:
                assert ann.group_id == target_id

    def test_merge_nonexistent_source_returns_404(self, app, client):
        """POST /merge with non-existent source returns 404."""
        att_id = _create_email_and_attachment(app)
        r = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Target"})
        target_id = r.get_json()["id"]

        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": 99999,
            "target_group_id": target_id,
        })
        assert resp.status_code == 404

    def test_merge_nonexistent_target_returns_404(self, app, client):
        """POST /merge with non-existent target returns 404."""
        att_id = _create_email_and_attachment(app)
        r = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Source"})
        source_id = r.get_json()["id"]

        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": source_id,
            "target_group_id": 99999,
        })
        assert resp.status_code == 404

    def test_merge_same_group_returns_400(self, app, client):
        """POST /merge with same source and target returns 400."""
        att_id = _create_email_and_attachment(app)
        r = client.post("/data/api/groups", json={"attachment_id": att_id, "name": "Same"})
        group_id = r.get_json()["id"]

        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": group_id,
            "target_group_id": group_id,
        })
        assert resp.status_code == 400

    def test_merge_different_attachments_returns_400(self, app, client):
        """POST /merge with groups from different attachments returns 400."""
        att_id_1 = _create_email_and_attachment(app)
        att_id_2 = _create_email_and_attachment(app)

        r1 = client.post("/data/api/groups", json={"attachment_id": att_id_1, "name": "G1"})
        r2 = client.post("/data/api/groups", json={"attachment_id": att_id_2, "name": "G2"})

        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": r1.get_json()["id"],
            "target_group_id": r2.get_json()["id"],
        })
        assert resp.status_code == 400

    def test_merge_missing_fields_returns_400(self, client):
        """POST /merge with missing fields returns 400."""
        resp = client.post("/data/api/groups/merge", json={
            "source_group_id": 1,
        })
        assert resp.status_code == 400


class TestQuantityOverride:
    """Test quantity_override on groups."""

    def test_update_group_with_quantity_override(self, app, client):
        """PUT updates quantity_override and returns effective_quantity."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id, "name": "Override Test",
        })
        group_id = resp.get_json()["id"]

        # Create 3 annotations
        with app.app_context():
            for i in range(3):
                ann = AnnotationModel(
                    attachment_id=att_id, page_number=1,
                    x=0.1 * i, y=0.1, width=0.05, height=0.05,
                    group_id=group_id,
                )
                db.session.add(ann)
            db.session.commit()

        # Set override to 10
        resp = client.put(f"/data/api/groups/{group_id}", json={
            "quantity_override": 10,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["quantity_override"] == 10
        assert data["effective_quantity"] == 10
        assert data["annotation_count"] == 3

    def test_clear_quantity_override(self, app, client):
        """PUT with quantity_override=null clears the override."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id, "name": "Clear Override",
        })
        group_id = resp.get_json()["id"]

        # Set override
        client.put(f"/data/api/groups/{group_id}", json={"quantity_override": 5})

        # Clear override
        resp = client.put(f"/data/api/groups/{group_id}", json={"quantity_override": None})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["quantity_override"] is None
        assert data["effective_quantity"] == 0  # no annotations

    def test_effective_quantity_without_override(self, app, client):
        """Without override, effective_quantity equals annotation_count."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id, "name": "No Override",
        })
        group_id = resp.get_json()["id"]

        # Create 2 annotations
        with app.app_context():
            for i in range(2):
                ann = AnnotationModel(
                    attachment_id=att_id, page_number=1,
                    x=0.1 * i, y=0.2, width=0.05, height=0.05,
                    group_id=group_id,
                )
                db.session.add(ann)
            db.session.commit()

        resp = client.get(f"/data/api/groups/{att_id}")
        groups = resp.get_json()
        assert len(groups) == 1
        assert groups[0]["quantity_override"] is None
        assert groups[0]["effective_quantity"] == 2
        assert groups[0]["annotation_count"] == 2

    def test_get_groups_includes_quantity_fields(self, app, client):
        """GET /api/groups includes quantity_override and effective_quantity."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id, "name": "Fields Test",
        })
        group_id = resp.get_json()["id"]

        # Set override
        client.put(f"/data/api/groups/{group_id}", json={"quantity_override": 7})

        resp = client.get(f"/data/api/groups/{att_id}")
        groups = resp.get_json()
        assert "quantity_override" in groups[0]
        assert "effective_quantity" in groups[0]
        assert groups[0]["quantity_override"] == 7
        assert groups[0]["effective_quantity"] == 7

    def test_invalid_quantity_override_returns_400(self, app, client):
        """PUT with non-integer quantity_override returns 400."""
        att_id = _create_email_and_attachment(app)

        resp = client.post("/data/api/groups", json={
            "attachment_id": att_id, "name": "Invalid Override",
        })
        group_id = resp.get_json()["id"]

        resp = client.put(f"/data/api/groups/{group_id}", json={
            "quantity_override": "abc",
        })
        assert resp.status_code == 400
