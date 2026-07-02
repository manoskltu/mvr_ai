"""Data store for email records — SQLite persistence via Flask-SQLAlchemy.

Provides the same public interface as the original in-memory implementation.
All functions require Flask application context to access the database session.
"""

from db_models import AttachmentModel, EmailRecordModel, db
from models import Attachment, EmailRecord


def _to_orm(record: EmailRecord) -> EmailRecordModel:
    """Convert an EmailRecord dataclass to an ORM model instance."""
    orm_record = EmailRecordModel(
        id=record.id,
        sender=record.sender,
        recipient=record.recipient,
        subject=record.subject,
        date=record.date,
        body_text=record.body_text,
        source_file=record.source_file,
    )
    for att in record.attachments:
        orm_record.attachments.append(
            AttachmentModel(
                filename=att.filename,
                content_type=att.content_type,
                file_path=att.file_path,
            )
        )
    return orm_record


def _to_dataclass(orm_record: EmailRecordModel) -> EmailRecord:
    """Convert an ORM model instance to an EmailRecord dataclass."""
    attachments = [
        Attachment(
            filename=att.filename,
            content_type=att.content_type,
            file_path=att.file_path,
            id=att.id,
        )
        for att in orm_record.attachments
    ]
    return EmailRecord(
        id=orm_record.id,
        sender=orm_record.sender,
        recipient=orm_record.recipient,
        subject=orm_record.subject,
        date=orm_record.date,
        body_text=orm_record.body_text,
        attachments=attachments,
        source_file=orm_record.source_file,
    )


def add_record(record: EmailRecord) -> str:
    """Add an EmailRecord to the store. Returns the assigned ID."""
    orm_record = _to_orm(record)
    db.session.add(orm_record)
    db.session.commit()
    return record.id


def get_all_records() -> list[EmailRecord]:
    """Return all stored EmailRecords."""
    orm_records = db.session.execute(
        db.select(EmailRecordModel)
    ).scalars().all()
    return [_to_dataclass(r) for r in orm_records]


def get_record(record_id: str) -> EmailRecord | None:
    """Return a single record by ID, or None if not found."""
    orm_record = db.session.get(EmailRecordModel, record_id)
    if orm_record is None:
        return None
    return _to_dataclass(orm_record)


def clear_records() -> None:
    """Remove all records (useful for testing)."""
    db.session.execute(db.delete(AttachmentModel))
    db.session.execute(db.delete(EmailRecordModel))
    db.session.commit()


def delete_record(record_id: str) -> bool:
    """Delete a single record by ID. Returns True if found and deleted."""
    orm_record = db.session.get(EmailRecordModel, record_id)
    if orm_record is None:
        return False
    db.session.delete(orm_record)
    db.session.commit()
    return True
