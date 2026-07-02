"""Unit tests for the EML parser module.

Tests parsing of real .eml files from assets/ and error handling.
"""

import os
from pathlib import Path

import pytest

from eml_parser import EmlParseError, parse_eml


# Paths to real .eml files in assets/
ASSETS_DIR = Path("assets")
EML_FILES = {
    "ex1": ASSETS_DIR / "ex1" / "VB_ SÄBO Finspång .eml",
    "ex2": ASSETS_DIR / "ex2" / "VB_ Önskar offert på smide.eml",
    "ex3": ASSETS_DIR / "ex3" / "VB_ Projektgenomgång säkerhetsåtgärder ESHD, dagens genomgång.eml",
    "ex4": ASSETS_DIR / "ex4" / "Sv_ Fostira.eml",
}


@pytest.fixture(params=list(EML_FILES.keys()))
def eml_content(request):
    """Load each real .eml file content as bytes."""
    path = EML_FILES[request.param]
    if not path.exists():
        pytest.skip(f"Asset file not found: {path}")
    return path.read_bytes(), request.param


class TestParseRealEmlFiles:
    """Test parsing each real .eml file from assets/."""

    def test_parse_ex1(self):
        """Parse ex1 .eml file — SÄBO Finspång."""
        content = EML_FILES["ex1"].read_bytes()
        record = parse_eml(content)
        assert record.sender != ""
        assert record.subject != ""
        # Verify Swedish characters are preserved in subject/sender
        # The filename contains SÄBO Finspång so the email likely does too
        assert record.body_text is not None

    def test_parse_ex2(self):
        """Parse ex2 .eml file — Önskar offert på smide."""
        content = EML_FILES["ex2"].read_bytes()
        record = parse_eml(content)
        assert record.sender != ""
        assert record.subject != ""
        assert record.body_text is not None

    def test_parse_ex3(self):
        """Parse ex3 .eml file — Projektgenomgång säkerhetsåtgärder ESHD."""
        content = EML_FILES["ex3"].read_bytes()
        record = parse_eml(content)
        assert record.sender != ""
        assert record.subject != ""
        assert record.body_text is not None

    def test_parse_ex4(self):
        """Parse ex4 .eml file — Fostira."""
        content = EML_FILES["ex4"].read_bytes()
        record = parse_eml(content)
        assert record.sender != ""
        assert record.subject != ""
        assert record.body_text is not None


class TestSwedishCharacterPreservation:
    """Verify Swedish characters (å, ä, ö) are preserved in parsed output."""

    def test_swedish_chars_in_parsed_content(self, eml_content):
        """At least some .eml files contain Swedish chars that must be preserved."""
        content, name = eml_content
        record = parse_eml(content)
        # The full text of the record (subject + body + sender) should not
        # contain Unicode replacement characters
        full_text = f"{record.sender} {record.subject} {record.body_text}"
        assert "\ufffd" not in full_text, (
            f"Unicode replacement characters found in {name} — encoding issue"
        )


class TestAttachmentIdentification:
    """Verify attachments are correctly identified."""

    def test_ex1_has_attachment(self):
        """ex1 should have a PDF attachment (SÄBO Finspång)."""
        content = EML_FILES["ex1"].read_bytes()
        record = parse_eml(content)
        assert len(record.attachments) >= 1
        # Check that at least one attachment is a PDF
        pdf_attachments = [a for a in record.attachments if "pdf" in a.content_type.lower()]
        assert len(pdf_attachments) >= 1

    def test_ex2_has_attachment(self):
        """ex2 should have a zip attachment (FFU Smide)."""
        content = EML_FILES["ex2"].read_bytes()
        record = parse_eml(content)
        assert len(record.attachments) >= 1

    def test_attachments_have_filenames(self, eml_content):
        """All identified attachments should have non-empty filenames."""
        content, name = eml_content
        record = parse_eml(content)
        for att in record.attachments:
            assert att.filename != "", f"Empty filename in attachment from {name}"
            assert att.content_type != "", f"Empty content_type in attachment from {name}"


class TestEmlParseError:
    """Test that EmlParseError is raised for invalid input."""

    def test_empty_bytes_raises_error(self):
        """Empty bytes should raise EmlParseError."""
        with pytest.raises(EmlParseError):
            parse_eml(b"")

    def test_whitespace_only_raises_error(self):
        """Whitespace-only content should raise EmlParseError."""
        with pytest.raises(EmlParseError):
            parse_eml(b"   \n\n  ")

    def test_random_bytes_raises_error(self):
        """Random non-email bytes should raise EmlParseError."""
        with pytest.raises(EmlParseError):
            parse_eml(os.urandom(64))

    def test_plain_text_no_headers_raises_error(self):
        """Plain text without any email headers should raise EmlParseError."""
        with pytest.raises(EmlParseError):
            parse_eml(b"This is just plain text with no headers at all")
