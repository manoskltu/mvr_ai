"""Data models for the email data import feature."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class Attachment:
    """Represents an email attachment."""

    filename: str
    content_type: str
    content: bytes | None = None  # Transient binary content during import
    file_path: str = ""  # Relative path from instance dir to saved file
    id: int | None = None  # Database ID (populated on retrieval from store)


@dataclass
class EmailRecord:
    """Structured data extracted from an .eml file or manual entry."""

    id: str = field(default_factory=lambda: str(uuid4()))
    sender: str = ""
    recipient: str = ""
    subject: str = ""
    date: datetime | None = None
    body_text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    source_file: str = ""


@dataclass
class ImportError:
    """Describes a failure to import a single file."""

    filename: str
    message: str


@dataclass
class ImportResult:
    """Collects outcomes of an import operation (one or more files)."""

    success: list[EmailRecord] = field(default_factory=list)
    errors: list[ImportError] = field(default_factory=list)
