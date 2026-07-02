"""Unit tests for the pretty printer functions (format_record, parse_formatted)."""

from datetime import datetime, timezone

from eml_parser import format_record, parse_formatted
from models import Attachment, EmailRecord


class TestFormatRecord:
    """Tests for format_record function."""

    def test_basic_format(self):
        """format_record produces expected structured text."""
        record = EmailRecord(
            id="test-id-123",
            sender="alice@example.com",
            recipient="bob@example.com",
            subject="Test Subject",
            date=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
            body_text="Hello, this is the body.",
            attachments=[],
            source_file="test.eml",
        )
        result = format_record(record)
        assert "From: alice@example.com" in result
        assert "To: bob@example.com" in result
        assert "Subject: Test Subject" in result
        assert "Date: 2024-06-15T10:30:00+00:00" in result
        assert "Source: test.eml" in result
        assert "Attachments: " in result
        assert "---" in result
        assert "Hello, this is the body." in result

    def test_id_not_in_output(self):
        """The ID field should NOT be included in the formatted output."""
        record = EmailRecord(
            id="unique-id-should-not-appear",
            sender="sender@example.com",
            subject="Subject",
        )
        result = format_record(record)
        assert "unique-id-should-not-appear" not in result

    def test_none_date_formats_as_empty(self):
        """When date is None, the Date line should be empty."""
        record = EmailRecord(sender="a@b.com", subject="Test")
        result = format_record(record)
        assert "Date: " in result
        # Should not have "Date: None"
        assert "None" not in result

    def test_attachments_formatting(self):
        """Attachments are formatted as 'filename (content_type)' separated by commas."""
        record = EmailRecord(
            sender="a@b.com",
            subject="With attachments",
            attachments=[
                Attachment(filename="doc.pdf", content_type="application/pdf"),
                Attachment(filename="image.png", content_type="image/png"),
            ],
        )
        result = format_record(record)
        assert "Attachments: doc.pdf (application/pdf), image.png (image/png)" in result

    def test_swedish_characters_preserved(self):
        """Swedish characters (å, ä, ö) must be preserved in output."""
        record = EmailRecord(
            sender="användare@företag.se",
            recipient="mottagare@företag.se",
            subject="Önskar offert på smide för SÄBO Finspång",
            body_text="Hej, vi önskar en offert på stålkonstruktioner.",
            source_file="VB_ SÄBO Finspång.eml",
        )
        result = format_record(record)
        assert "användare@företag.se" in result
        assert "Önskar offert på smide för SÄBO Finspång" in result
        assert "vi önskar en offert på stålkonstruktioner" in result
        assert "VB_ SÄBO Finspång.eml" in result

    def test_multiline_body(self):
        """Body text with multiple lines is preserved after the --- separator."""
        record = EmailRecord(
            sender="a@b.com",
            subject="Multi-line",
            body_text="Line 1\nLine 2\nLine 3",
        )
        result = format_record(record)
        parts = result.split("---\n")
        assert len(parts) == 2
        assert parts[1] == "Line 1\nLine 2\nLine 3"


class TestParseFormatted:
    """Tests for parse_formatted function."""

    def test_basic_parse(self):
        """parse_formatted correctly parses a formatted text."""
        text = (
            "From: alice@example.com\n"
            "To: bob@example.com\n"
            "Subject: Hello World\n"
            "Date: 2024-06-15T10:30:00+00:00\n"
            "Source: test.eml\n"
            "Attachments: \n"
            "---\n"
            "Body text here."
        )
        record = parse_formatted(text)
        assert record.sender == "alice@example.com"
        assert record.recipient == "bob@example.com"
        assert record.subject == "Hello World"
        assert record.date == datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert record.source_file == "test.eml"
        assert record.body_text == "Body text here."
        assert record.attachments == []

    def test_new_id_generated(self):
        """parse_formatted generates a new ID (not from the formatted text)."""
        text = (
            "From: a@b.com\n"
            "To: \n"
            "Subject: Test\n"
            "Date: \n"
            "Source: \n"
            "Attachments: \n"
            "---\n"
            ""
        )
        record1 = parse_formatted(text)
        record2 = parse_formatted(text)
        # Both should have IDs but they should be different (new UUID each time)
        assert record1.id != ""
        assert record2.id != ""
        assert record1.id != record2.id

    def test_parse_with_attachments(self):
        """parse_formatted correctly parses attachment list."""
        text = (
            "From: a@b.com\n"
            "To: c@d.com\n"
            "Subject: Docs\n"
            "Date: \n"
            "Source: mail.eml\n"
            "Attachments: report.pdf (application/pdf), photo.jpg (image/jpeg)\n"
            "---\n"
            "See attached."
        )
        record = parse_formatted(text)
        assert len(record.attachments) == 2
        assert record.attachments[0].filename == "report.pdf"
        assert record.attachments[0].content_type == "application/pdf"
        assert record.attachments[1].filename == "photo.jpg"
        assert record.attachments[1].content_type == "image/jpeg"

    def test_empty_date_parsed_as_none(self):
        """Empty Date line is parsed as None."""
        text = (
            "From: a@b.com\n"
            "To: \n"
            "Subject: No date\n"
            "Date: \n"
            "Source: \n"
            "Attachments: \n"
            "---\n"
            ""
        )
        record = parse_formatted(text)
        assert record.date is None

    def test_swedish_characters_preserved_in_parse(self):
        """Swedish characters survive parse_formatted."""
        text = (
            "From: användare@företag.se\n"
            "To: mottagare@företag.se\n"
            "Subject: Önskar offert\n"
            "Date: \n"
            "Source: SÄBO.eml\n"
            "Attachments: \n"
            "---\n"
            "Stålkonstruktioner med å, ä, ö."
        )
        record = parse_formatted(text)
        assert record.sender == "användare@företag.se"
        assert record.recipient == "mottagare@företag.se"
        assert record.subject == "Önskar offert"
        assert record.source_file == "SÄBO.eml"
        assert "å, ä, ö" in record.body_text


class TestRoundTrip:
    """Tests for format_record -> parse_formatted round trip."""

    def test_round_trip_basic(self):
        """format then parse produces equivalent record (ignoring ID)."""
        original = EmailRecord(
            sender="test@example.com",
            recipient="other@example.com",
            subject="Round Trip Test",
            date=datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
            body_text="This should survive the round trip.",
            attachments=[
                Attachment(filename="file.pdf", content_type="application/pdf"),
            ],
            source_file="original.eml",
        )
        formatted = format_record(original)
        parsed = parse_formatted(formatted)

        assert parsed.sender == original.sender
        assert parsed.recipient == original.recipient
        assert parsed.subject == original.subject
        assert parsed.date == original.date
        assert parsed.body_text == original.body_text
        assert parsed.source_file == original.source_file
        assert len(parsed.attachments) == len(original.attachments)
        assert parsed.attachments[0].filename == original.attachments[0].filename
        assert parsed.attachments[0].content_type == original.attachments[0].content_type
        # ID is NOT preserved (new ID generated)
        assert parsed.id != original.id

    def test_round_trip_empty_fields(self):
        """Round trip works with empty/default fields."""
        original = EmailRecord(
            sender="",
            recipient="",
            subject="",
            date=None,
            body_text="",
            attachments=[],
            source_file="",
        )
        formatted = format_record(original)
        parsed = parse_formatted(formatted)

        assert parsed.sender == original.sender
        assert parsed.recipient == original.recipient
        assert parsed.subject == original.subject
        assert parsed.date is None
        assert parsed.body_text == original.body_text
        assert parsed.attachments == []
        assert parsed.source_file == original.source_file

    def test_round_trip_swedish_content(self):
        """Round trip preserves Swedish characters throughout."""
        original = EmailRecord(
            sender="förnamn.efternamn@företag.se",
            recipient="kund@städföretag.se",
            subject="Förfrågan om stålkonstruktioner i Finspång",
            date=datetime(2024, 3, 20, 14, 0, 0, tzinfo=timezone.utc),
            body_text="Vi behöver en offert för:\n- Stålpelare\n- Balkar\nMed vänliga hälsningar",
            attachments=[
                Attachment(
                    filename="107342 SÄBO Finspång 2026-05-18.pdf",
                    content_type="application/pdf",
                ),
            ],
            source_file="VB_ SÄBO Finspång.eml",
        )
        formatted = format_record(original)
        parsed = parse_formatted(formatted)

        assert parsed.sender == original.sender
        assert parsed.recipient == original.recipient
        assert parsed.subject == original.subject
        assert parsed.date == original.date
        assert parsed.body_text == original.body_text
        assert parsed.source_file == original.source_file
        assert parsed.attachments[0].filename == original.attachments[0].filename

    def test_round_trip_multiline_body(self):
        """Round trip preserves multi-line body text."""
        original = EmailRecord(
            sender="a@b.com",
            subject="Multi",
            body_text="Line 1\nLine 2\n\nLine 4 after blank",
        )
        formatted = format_record(original)
        parsed = parse_formatted(formatted)

        assert parsed.body_text == original.body_text
