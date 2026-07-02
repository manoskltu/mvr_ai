"""Unit tests for the import handler module."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import FileStorage

import data_store
import import_handler


@pytest.fixture(autouse=True)
def clean_store(app):
    """Clear the data store before and after each test."""
    data_store.clear_records()
    yield
    data_store.clear_records()


def _make_file_storage(content: bytes, filename: str) -> FileStorage:
    """Create a mock FileStorage object with given content and filename."""
    return FileStorage(
        stream=BytesIO(content),
        filename=filename,
        content_type="message/rfc822",
    )


def _load_real_eml(relative_path: str) -> bytes:
    """Load a real .eml file from the project root."""
    path = Path(relative_path)
    if not path.exists():
        pytest.skip(f"Asset file not found: {path}")
    return path.read_bytes()


class TestListAssetEmlFiles:
    """Test list_asset_eml_files finds .eml files recursively."""

    def test_finds_eml_files(self):
        """Should find all .eml files in the assets/ directory."""
        eml_files = import_handler.list_asset_eml_files()
        assert len(eml_files) >= 4  # We know there are 4 .eml files in assets/

    def test_all_results_end_with_eml(self):
        """All returned paths should end with .eml extension."""
        eml_files = import_handler.list_asset_eml_files()
        for path in eml_files:
            assert path.lower().endswith(".eml"), f"Non-.eml file found: {path}"

    def test_results_are_sorted(self):
        """Results should be returned in sorted order."""
        eml_files = import_handler.list_asset_eml_files()
        assert eml_files == sorted(eml_files)

    def test_results_contain_known_files(self):
        """Results should include known .eml files from assets/."""
        eml_files = import_handler.list_asset_eml_files()
        # Check that our known files are present (using partial match for encoding)
        has_ex4 = any("ex4" in f and "Fostira" in f for f in eml_files)
        assert has_ex4, f"Expected ex4/Fostira .eml in results: {eml_files}"


class TestImportUploadedFiles:
    """Test import_uploaded_files with valid and invalid files."""

    def test_valid_eml_upload(self):
        """Uploading a valid .eml file should create a record."""
        content = _load_real_eml("assets/ex4/Sv_ Fostira.eml")
        file_storage = _make_file_storage(content, "Sv_ Fostira.eml")

        result = import_handler.import_uploaded_files([file_storage])

        assert len(result.success) == 1
        assert len(result.errors) == 0
        assert result.success[0].sender != ""
        # Verify record was added to store
        assert len(data_store.get_all_records()) == 1

    def test_rejects_non_eml_file(self):
        """Uploading a non-.eml file should produce an error."""
        file_storage = _make_file_storage(b"not an email", "document.pdf")

        result = import_handler.import_uploaded_files([file_storage])

        assert len(result.success) == 0
        assert len(result.errors) == 1
        assert "document.pdf" in result.errors[0].filename
        # No record should be added to store
        assert len(data_store.get_all_records()) == 0

    def test_rejects_txt_file(self):
        """Uploading a .txt file should produce an error."""
        file_storage = _make_file_storage(b"plain text", "notes.txt")

        result = import_handler.import_uploaded_files([file_storage])

        assert len(result.success) == 0
        assert len(result.errors) == 1

    def test_batch_continues_after_failure(self):
        """A failed file should not prevent other valid files from processing."""
        valid_content = _load_real_eml("assets/ex4/Sv_ Fostira.eml")
        valid_file = _make_file_storage(valid_content, "good.eml")
        invalid_file = _make_file_storage(b"not an email", "bad.pdf")

        result = import_handler.import_uploaded_files([invalid_file, valid_file])

        assert len(result.success) == 1
        assert len(result.errors) == 1
        assert len(data_store.get_all_records()) == 1


class TestImportFromAssets:
    """Test import_from_assets with real asset files."""

    def test_import_real_asset_file(self):
        """Importing a real asset .eml file should succeed."""
        result = import_handler.import_from_assets(["assets/ex4/Sv_ Fostira.eml"])

        assert len(result.success) == 1
        assert len(result.errors) == 0
        assert result.success[0].source_file == "assets/ex4/Sv_ Fostira.eml"
        assert len(data_store.get_all_records()) == 1

    def test_import_nonexistent_file(self):
        """Importing a nonexistent file should produce an error."""
        result = import_handler.import_from_assets(["assets/nonexistent.eml"])

        assert len(result.success) == 0
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].message.lower() or "File not found" in result.errors[0].message

    def test_batch_continues_after_one_failure(self):
        """A failed file should not prevent other files from being imported."""
        result = import_handler.import_from_assets([
            "assets/nonexistent.eml",
            "assets/ex4/Sv_ Fostira.eml",
        ])

        assert len(result.success) == 1
        assert len(result.errors) == 1
        assert len(data_store.get_all_records()) == 1
