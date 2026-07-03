"""Integration tests for Data Tab routes.

Tests the split sub-tabs (E-post and Import), upload, asset import,
manual entry, and display functionality.
"""

from io import BytesIO
from pathlib import Path

import pytest

import data_store
from models import EmailRecord


@pytest.fixture(autouse=True)
def clean_store(app):
    """Clear data store before and after each test."""
    data_store.clear_records()
    yield
    data_store.clear_records()


def _load_real_eml(relative_path: str) -> bytes:
    """Load a real .eml file from the project root."""
    path = Path(relative_path)
    if not path.exists():
        pytest.skip(f"Asset file not found: {path}")
    return path.read_bytes()


class TestEmailsTab:
    """Test GET /data/ (Data page)."""

    def test_emails_page_returns_200(self, client):
        """GET /data/ should return HTTP 200."""
        response = client.get("/data/")
        assert response.status_code == 200

    def test_emails_page_shows_no_data_message_when_empty(self, client):
        """When no records exist, page should show informational message."""
        response = client.get("/data/")
        text = response.data.decode("utf-8")
        assert "ingen data" in text.lower() or "no data" in text.lower()

    def test_emails_page_contains_import_button(self, client):
        """Data page should contain an import button."""
        response = client.get("/data/")
        text = response.data.decode("utf-8")
        assert "Importera" in text

    def test_emails_page_has_import_panel(self, client):
        """Data page should contain the hidden import panel."""
        response = client.get("/data/")
        text = response.data.decode("utf-8")
        assert "import-panel" in text

    def test_emails_page_does_not_show_import_forms_by_default(self, client):
        """Import panel should be hidden by default (has 'hidden' class)."""
        response = client.get("/data/")
        text = response.data.decode("utf-8")
        assert 'import-panel hidden' in text

    def test_emails_page_shows_records(self, client):
        """When records exist, they should appear in the table."""
        record = EmailRecord(
            sender="test@example.com",
            subject="Test Subject",
        )
        data_store.add_record(record)
        response = client.get("/data/")
        text = response.data.decode("utf-8")
        assert "Test Subject" in text
        assert "data-table" in text


class TestUpload:
    """Test POST /data/upload route."""

    def test_upload_valid_eml_file(self, client):
        """Uploading a valid .eml file should redirect to data page."""
        content = _load_real_eml("assets/ex4/Sv_ Fostira.eml")

        response = client.post(
            "/data/upload",
            data={"files": (BytesIO(content), "Sv_ Fostira.eml")},
            content_type="multipart/form-data",
        )

        # Should redirect to /data/
        assert response.status_code == 302
        assert "/data/" in response.headers["Location"]
        # Record should be created
        assert len(data_store.get_all_records()) == 1

    def test_upload_invalid_file(self, client):
        """Uploading a non-.eml file should redirect to data page with error."""
        response = client.post(
            "/data/upload",
            data={"files": (BytesIO(b"not an email"), "document.pdf")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        assert "/data/" in response.headers["Location"]
        assert len(data_store.get_all_records()) == 0


class TestImportAssets:
    """Test POST /data/import-assets route."""

    def test_import_valid_asset_file(self, client):
        """Importing a valid asset .eml file should redirect to data page."""
        response = client.post(
            "/data/import-assets",
            data={"asset_files": "assets/ex4/Sv_ Fostira.eml"},
        )

        assert response.status_code == 302
        assert "/data/" in response.headers["Location"]
        assert len(data_store.get_all_records()) == 1


class TestRecordDetail:
    """Test GET /data/record/<id> route."""

    def test_unknown_record_returns_404(self, client):
        """Requesting a non-existent record should return 404."""
        response = client.get("/data/record/nonexistent-id-12345")
        assert response.status_code == 404

    def test_existing_record_returns_200(self, client):
        """Requesting an existing record should return 200 with details."""
        record = EmailRecord(
            sender="test@example.com",
            subject="Test Subject",
            body_text="Test body",
        )
        data_store.add_record(record)

        response = client.get(f"/data/record/{record.id}")
        assert response.status_code == 200
        text = response.data.decode("utf-8")
        assert "test@example.com" in text
        assert "Test Subject" in text


class TestManualEntry:
    """Test GET /data/manual and POST /data/manual routes."""

    def test_manual_form_returns_200(self, client):
        """GET /data/manual should return 200."""
        response = client.get("/data/manual")
        assert response.status_code == 200

    def test_manual_submit_valid_data_creates_record(self, client):
        """Submitting valid data should create a record and redirect."""
        response = client.post(
            "/data/manual",
            data={
                "sender": "manual@example.com",
                "recipient": "recipient@example.com",
                "subject": "Manual Test Subject",
                "date": "2024-01-15",
                "body_text": "This is a manual entry.",
            },
        )

        # Should redirect to import tab
        assert response.status_code == 302
        records = data_store.get_all_records()
        assert len(records) == 1
        assert records[0].sender == "manual@example.com"
        assert records[0].subject == "Manual Test Subject"

    def test_manual_submit_missing_sender_shows_error(self, client):
        """Missing sender should show validation error."""
        response = client.post(
            "/data/manual",
            data={
                "sender": "",
                "subject": "Has Subject",
            },
        )

        assert response.status_code == 200
        text = response.data.decode("utf-8")
        assert "sender" in text.lower() or "avsändare" in text.lower()
        assert len(data_store.get_all_records()) == 0

    def test_manual_submit_missing_subject_shows_error(self, client):
        """Missing subject should show validation error."""
        response = client.post(
            "/data/manual",
            data={
                "sender": "has@sender.com",
                "subject": "",
            },
        )

        assert response.status_code == 200
        text = response.data.decode("utf-8")
        assert "subject" in text.lower() or "ämne" in text.lower()
        assert len(data_store.get_all_records()) == 0

    def test_manual_submit_missing_both_shows_errors(self, client):
        """Missing both sender and subject should show both errors."""
        response = client.post(
            "/data/manual",
            data={
                "sender": "",
                "subject": "",
            },
        )

        assert response.status_code == 200
        text = response.data.decode("utf-8")
        assert "required" in text.lower() or "avsändare" in text.lower() or "sender" in text.lower()
        assert len(data_store.get_all_records()) == 0
