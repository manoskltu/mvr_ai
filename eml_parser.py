"""EML parser module for parsing .eml files into structured EmailRecord objects.

Uses Python's stdlib email module. No Flask dependency.
"""

import email
import email.header
import email.policy
import email.utils
import re
from datetime import datetime
from email.message import EmailMessage

from models import Attachment, EmailRecord


class EmlParseError(Exception):
    """Raised when an .eml file cannot be parsed due to malformed MIME structure."""

    pass


def _decode_header(header_value: str | None) -> str:
    """Decode an email header value, handling RFC 2047 encoded-words."""
    if header_value is None:
        return ""
    # With email.policy.default, headers are already decoded as str objects.
    # However, we still handle the case where raw encoded-words slip through.
    decoded_parts = email.header.decode_header(header_value)
    parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _extract_body_text(msg: EmailMessage) -> str:
    """Walk the MIME tree and extract the plain text body content.

    Handles base64 and quoted-printable Content-Transfer-Encoding.
    """
    # Try the simple approach first for non-multipart messages
    if not msg.is_multipart():
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            payload = msg.get_content()
            if isinstance(payload, str):
                return payload
            elif isinstance(payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    # Walk multipart messages
    text_parts = []
    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "")

        # Skip attachments
        if "attachment" in disposition:
            continue

        if content_type == "text/plain":
            try:
                payload = part.get_content()
                if isinstance(payload, str):
                    text_parts.append(payload)
                elif isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    text_parts.append(payload.decode(charset, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                # Unrecognized encoding or decode failure
                try:
                    raw = part.get_payload(decode=True)
                    if raw:
                        text_parts.append(raw.decode("utf-8", errors="replace"))
                except Exception:
                    pass

    return "\n".join(text_parts)


def _extract_attachments(msg: EmailMessage) -> list[Attachment]:
    """Identify attachments by filename and content type."""
    attachments = []

    for part in msg.walk():
        disposition = str(part.get("Content-Disposition") or "")
        content_type = part.get_content_type()
        filename = part.get_filename()

        # A part is an attachment if it has Content-Disposition: attachment
        # or if it's a non-text part with a filename
        is_attachment = "attachment" in disposition
        is_non_text_with_filename = (
            filename is not None
            and not content_type.startswith("multipart/")
            and "attachment" not in disposition
            and content_type not in ("text/plain", "text/html")
        )

        if is_attachment or is_non_text_with_filename:
            att_filename = filename or "unnamed"
            # Decode filename if needed
            if isinstance(att_filename, bytes):
                att_filename = att_filename.decode("utf-8", errors="replace")

            # Extract decoded binary content
            payload = part.get_payload(decode=True)
            if payload is None:
                continue  # Skip parts with no decodable payload

            attachments.append(
                Attachment(
                    filename=att_filename,
                    content_type=content_type,
                    content=payload,
                )
            )

    return attachments


def parse_eml(file_content: bytes) -> EmailRecord:
    """Parse raw .eml bytes into a structured EmailRecord.

    Args:
        file_content: Raw bytes of the .eml file.

    Returns:
        An EmailRecord with all fields populated from the parsed email.

    Raises:
        EmlParseError: If the MIME structure is malformed or unreadable.
    """
    if not file_content or not file_content.strip():
        raise EmlParseError("Empty or blank content cannot be parsed as an email")

    try:
        msg = email.message_from_bytes(file_content, policy=email.policy.default)
    except Exception as e:
        raise EmlParseError(f"Failed to parse MIME structure: {e}") from e

    # Validate that this looks like an email (has at least some headers)
    if not msg.keys():
        raise EmlParseError(
            "No email headers found — content does not appear to be a valid email"
        )

    # Extract headers
    sender = _decode_header(msg.get("From"))
    recipient = _decode_header(msg.get("To"))
    subject = _decode_header(msg.get("Subject"))

    # Parse date
    date: datetime | None = None
    date_header = msg.get("Date")
    if date_header:
        try:
            date = email.utils.parsedate_to_datetime(date_header)
        except (TypeError, ValueError, IndexError):
            # Unparseable date — leave as None
            date = None

    # Extract body
    body_text = _extract_body_text(msg)

    # Extract attachments
    attachments = _extract_attachments(msg)

    return EmailRecord(
        sender=sender,
        recipient=recipient,
        subject=subject,
        date=date,
        body_text=body_text,
        attachments=attachments,
    )


def format_record(record: EmailRecord) -> str:
    """Format an EmailRecord into a human-readable text representation.

    Used for round-trip verification (pretty printer).

    Args:
        record: The EmailRecord to format.

    Returns:
        A structured text representation of the record.
    """
    lines = []
    lines.append(f"From: {record.sender}")
    lines.append(f"To: {record.recipient}")
    lines.append(f"Subject: {record.subject}")

    # Format date as ISO format or empty
    if record.date is not None:
        lines.append(f"Date: {record.date.isoformat()}")
    else:
        lines.append("Date: ")

    lines.append(f"Source: {record.source_file}")

    # Format attachments
    if record.attachments:
        att_parts = [
            f"{att.filename} ({att.content_type})" for att in record.attachments
        ]
        lines.append(f"Attachments: {', '.join(att_parts)}")
    else:
        lines.append("Attachments: ")

    # Separator before body
    lines.append("---")
    lines.append(record.body_text)

    return "\n".join(lines)


def parse_formatted(text: str) -> EmailRecord:
    """Parse a formatted text representation back into an EmailRecord.

    Inverse of format_record for round-trip property.

    Args:
        text: The structured text output from format_record.

    Returns:
        An EmailRecord with fields populated from the text.
    """
    lines = text.split("\n")

    sender = ""
    recipient = ""
    subject = ""
    date: datetime | None = None
    source_file = ""
    attachments: list[Attachment] = []
    body_start_index = 0

    # Parse header lines until we hit the --- separator
    for i, line in enumerate(lines):
        if line == "---":
            # Found the separator; body starts on the next line
            body_start_index = i + 1
            break

        if line.startswith("From: "):
            sender = line[len("From: "):]
        elif line.startswith("To: "):
            recipient = line[len("To: "):]
        elif line.startswith("Subject: "):
            subject = line[len("Subject: "):]
        elif line.startswith("Date: "):
            date_str = line[len("Date: "):].strip()
            if date_str:
                try:
                    date = datetime.fromisoformat(date_str)
                except (ValueError, TypeError):
                    date = None
        elif line.startswith("Source: "):
            source_file = line[len("Source: "):]
        elif line.startswith("Attachments: "):
            att_str = line[len("Attachments: "):].strip()
            if att_str:
                attachments = _parse_attachments_str(att_str)

    # Everything after the --- separator is body text
    body_text = "\n".join(lines[body_start_index:])

    return EmailRecord(
        sender=sender,
        recipient=recipient,
        subject=subject,
        date=date,
        body_text=body_text,
        attachments=attachments,
        source_file=source_file,
    )


def _parse_attachments_str(att_str: str) -> list[Attachment]:
    """Parse the attachments string back into a list of Attachment objects.

    Format: "filename1 (content_type1), filename2 (content_type2)"
    """
    attachments = []
    # Match pattern: filename (content_type)
    # We split by "), " to handle multiple attachments, then handle the trailing ")"
    pattern = re.compile(r"(.+?)\s+\(([^)]+)\)")

    # Split on ", " but only when followed by a filename pattern
    # A simpler approach: find all matches of the pattern
    matches = pattern.findall(att_str)
    for filename, content_type in matches:
        # Handle case where filename might have ", " from previous split
        # Clean up any leading ", " that got included
        clean_filename = filename.lstrip(", ").strip()
        if clean_filename:
            attachments.append(
                Attachment(filename=clean_filename, content_type=content_type)
            )

    return attachments
