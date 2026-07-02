"""SQLAlchemy ORM models for the email data store.

Defines the database schema for EmailRecord and Attachment persistence.
"""

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class EmailRecordModel(db.Model):
    """ORM model representing an email record row in the database."""

    __tablename__ = "email_records"

    id = db.Column(db.String(36), primary_key=True)
    sender = db.Column(db.Text, nullable=False, default="")
    recipient = db.Column(db.Text, nullable=False, default="")
    subject = db.Column(db.Text, nullable=False, default="")
    date = db.Column(db.DateTime, nullable=True)
    body_text = db.Column(db.Text, nullable=False, default="")
    source_file = db.Column(db.Text, nullable=False, default="")

    attachments = db.relationship(
        "AttachmentModel",
        backref="email_record",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AttachmentModel(db.Model):
    """ORM model representing an attachment row linked to an EmailRecord."""

    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email_record_id = db.Column(
        db.String(36),
        db.ForeignKey("email_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename = db.Column(db.Text, nullable=False, default="")
    content_type = db.Column(db.Text, nullable=False, default="")
    file_path = db.Column(db.Text, nullable=False, default="")


class AnnotationModel(db.Model):
    """Stores rectangle annotations for PDF pages."""

    __tablename__ = "annotations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    attachment_id = db.Column(
        db.Integer,
        db.ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number = db.Column(db.Integer, nullable=False)  # 1-indexed
    x = db.Column(db.Float, nullable=False)       # ratio 0.0–1.0
    y = db.Column(db.Float, nullable=False)       # ratio 0.0–1.0
    width = db.Column(db.Float, nullable=False)   # ratio 0.0–1.0
    height = db.Column(db.Float, nullable=False)  # ratio 0.0–1.0
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    attachment = db.relationship("AttachmentModel", backref="annotations")

    __table_args__ = (
        db.Index("ix_annotations_attachment_page", "attachment_id", "page_number"),
    )


class AnalysisResultModel(db.Model):
    """Stores analysis results for a single PDF attachment."""

    __tablename__ = "analysis_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    attachment_id = db.Column(
        db.Integer,
        db.ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    result_json = db.Column(db.Text, nullable=False, default="{}")

    attachment = db.relationship("AttachmentModel", backref="analysis_results")
