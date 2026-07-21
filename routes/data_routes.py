"""Flask routes for the Data Tab feature.

Blueprint with all Data Tab endpoints for importing, viewing, and
managing email records. Split into sub-tabs: E-post (records), Import, and Analys.
"""

import os
import re
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import func

import data_store
import import_handler
from attachment_store import get_attachment_full_path
from db_models import AnalysisResultModel, AnnotationGroupModel, AnnotationModel, AttachmentModel, EmailRecordModel, db
from models import EmailRecord
from analysis.analysis_pipeline import run_analysis, serialize_result, deserialize_result
from analysis.config import get_analysis_config

data_bp = Blueprint("data", __name__, url_prefix="/data")


def validate_annotation_data(data):
    """Validate annotation request body.

    Returns (validated_data, None) on success or (None, error_message) on failure.
    """
    required = ["attachment_id", "page_number", "x", "y", "width", "height"]
    for field in required:
        if field not in data:
            return None, f"Missing required field: {field}"
    try:
        x = float(data["x"])
        y = float(data["y"])
        w = float(data["width"])
        h = float(data["height"])
        page = int(data["page_number"])
        att_id = int(data["attachment_id"])
    except (ValueError, TypeError):
        return None, "Invalid field types"
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= w <= 1.0 and 0.0 <= h <= 1.0):
        return None, "Coordinate values must be between 0.0 and 1.0"
    if page < 1:
        return None, "page_number must be >= 1"
    return {"attachment_id": att_id, "page_number": page, "x": x, "y": y, "width": w, "height": h}, None


def validate_hex_color(color: str) -> bool:
    """Return True if color matches #RRGGBB format (6 hex chars after #)."""
    return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", color))


def validate_group_data(data, attachment_id=None, group_id=None):
    """Validate group create/update request body.

    Checks: name is non-empty string, color is valid hex (#RRGGBB),
    attachment_id exists, name is unique per attachment.

    Returns (validated_data, None) on success or (None, error_message) on failure.
    """
    validated = {}

    # Validate name if provided
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            return None, "Group name cannot be empty"
        validated["name"] = name.strip()

    # Validate color if provided
    if "color" in data:
        color = data["color"]
        if not isinstance(color, str) or not validate_hex_color(color):
            return None, "Invalid color format. Use #RRGGBB"
        validated["color"] = color

    # Validate display_order if provided
    if "display_order" in data:
        try:
            validated["display_order"] = int(data["display_order"])
        except (ValueError, TypeError):
            return None, "Invalid display_order value"

    # Validate attachment_id if provided
    if attachment_id is not None:
        att = db.session.get(AttachmentModel, attachment_id)
        if att is None:
            return None, "Attachment not found"

    # Check name uniqueness per attachment
    if "name" in validated and attachment_id is not None:
        query = AnnotationGroupModel.query.filter_by(
            attachment_id=attachment_id, name=validated["name"]
        )
        if group_id is not None:
            query = query.filter(AnnotationGroupModel.id != group_id)
        if query.first() is not None:
            return None, "A group with this name already exists"

    return validated, None


@data_bp.route("/")
def data_index():
    """Render the Data page with records table and import controls."""
    records = data_store.get_all_records()
    asset_files = import_handler.list_asset_eml_files()
    return render_template("data_emails.html", records=records, asset_files=asset_files, active_tab="emails")


@data_bp.route("/import")
def import_index():
    """Render the Import sub-tab with upload/asset controls."""
    asset_files = import_handler.list_asset_eml_files()
    return render_template("data_import.html", asset_files=asset_files, active_tab="import")


@data_bp.route("/upload", methods=["POST"])
def upload():
    """Handle .eml file upload (multipart)."""
    files = request.files.getlist("files")

    if not files or all(f.filename == "" for f in files):
        flash("No files selected for upload.", "error")
        return redirect(url_for("data.data_index"))

    result = import_handler.import_uploaded_files(files)

    if result.success:
        flash(
            f"Successfully imported {len(result.success)} file(s).", "success"
        )
    for err in result.errors:
        flash(f"Error importing {err.filename}: {err.message}", "error")

    return redirect(url_for("data.data_index"))


@data_bp.route("/import-assets", methods=["POST"])
def import_assets():
    """Import selected .eml files from the assets directory."""
    file_paths = request.form.getlist("asset_files")

    if not file_paths:
        flash("No asset files selected for import.", "error")
        return redirect(url_for("data.data_index"))

    result = import_handler.import_from_assets(file_paths)

    if result.success:
        flash(
            f"Successfully imported {len(result.success)} file(s) from assets.",
            "success",
        )
    for err in result.errors:
        flash(f"Error importing {err.filename}: {err.message}", "error")

    return redirect(url_for("data.data_index"))


@data_bp.route("/record/<record_id>")
def record_detail(record_id):
    """View single record details. Returns 404 if not found."""
    record = data_store.get_record(record_id)
    if record is None:
        abort(404)

    return render_template("data_detail.html", record=record)


@data_bp.route("/record/<record_id>/attachment/<int:attachment_id>")
def download_attachment(record_id, attachment_id):
    """Serve an attachment file for download."""
    # Look up attachment in DB
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None or att.email_record_id != record_id:
        abort(404)
    if not att.file_path:
        abort(404)

    # Resolve full path and verify file exists
    full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
    if not os.path.isfile(full_path):
        abort(404)

    return send_file(
        full_path,
        mimetype=att.content_type,
        as_attachment=True,
        download_name=att.filename,
    )


@data_bp.route("/record/<record_id>/delete", methods=["POST"])
def delete_record(record_id):
    """Delete an email record and its attachments."""
    import shutil

    # Delete attachment files from disk
    record = data_store.get_record(record_id)
    if record is None:
        abort(404)

    att_dir = os.path.join(current_app.instance_path, "attachments", record_id)
    if os.path.isdir(att_dir):
        shutil.rmtree(att_dir, ignore_errors=True)

    data_store.delete_record(record_id)
    flash("Posten har tagits bort.", "success")
    return redirect(url_for("data.data_index"))


@data_bp.route("/record/<record_id>/update", methods=["POST"])
def update_record(record_id):
    """Update an email record's editable fields and delete marked attachments."""
    from db_models import EmailRecordModel

    orm_record = db.session.get(EmailRecordModel, record_id)
    if orm_record is None:
        abort(404)

    # Update text fields
    orm_record.sender = request.form.get("sender", "").strip()
    orm_record.recipient = request.form.get("recipient", "").strip()
    orm_record.subject = request.form.get("subject", "").strip()
    orm_record.body_text = request.form.get("body_text", "")

    # Delete marked attachments
    delete_ids = request.form.getlist("delete_attachments")
    for att_id_str in delete_ids:
        try:
            att_id = int(att_id_str)
        except (ValueError, TypeError):
            continue
        att = db.session.get(AttachmentModel, att_id)
        if att and att.email_record_id == record_id:
            # Delete file from disk
            if att.file_path:
                full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
                if os.path.isfile(full_path):
                    os.remove(full_path)
            db.session.delete(att)

    db.session.commit()

    flash("Ändringarna har sparats.", "success")
    return redirect(url_for("data.record_detail", record_id=record_id))


@data_bp.route("/record/<record_id>/attachment/<int:attachment_id>/delete", methods=["POST"])
def delete_attachment(record_id, attachment_id):
    """Delete a single attachment from a record."""
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None or att.email_record_id != record_id:
        abort(404)

    # Delete file from disk
    if att.file_path:
        full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
        if os.path.isfile(full_path):
            os.remove(full_path)

    db.session.delete(att)
    db.session.commit()
    return jsonify({"success": True})


@data_bp.route("/record/<record_id>/export-to-plan", methods=["POST"])
def export_to_plan(record_id):
    """Mark selected PDF attachments as exported to Plan."""
    record = data_store.get_record(record_id)
    if record is None:
        abort(404)

    attachment_ids = request.form.getlist("plan_attachment_ids")
    if not attachment_ids:
        flash("Inga bilagor valda.", "error")
        return redirect(url_for("data.record_detail", record_id=record_id))

    count = 0
    for att_id_str in attachment_ids:
        try:
            att_id = int(att_id_str)
        except (ValueError, TypeError):
            continue
        att = db.session.get(AttachmentModel, att_id)
        if att and att.email_record_id == record_id:
            att.in_plan = True
            count += 1

    db.session.commit()
    flash(f"{count} bilaga(or) exporterade till Plan.", "success")
    return redirect(url_for("data.record_detail", record_id=record_id))


@data_bp.route("/manual")
def manual_form():
    """Render the manual entry form."""
    return render_template("data_manual.html", errors=[], form_data={})


@data_bp.route("/manual", methods=["POST"])
def manual_submit():
    """Validate and submit manual entry with optional file attachments."""
    form_data = {
        "sender": request.form.get("sender", "").strip(),
        "recipient": request.form.get("recipient", "").strip(),
        "subject": request.form.get("subject", "").strip(),
        "date": request.form.get("date", "").strip(),
        "body_text": request.form.get("body_text", "").strip(),
    }

    errors = []
    if not form_data["sender"]:
        errors.append("Avsändare (sender) is required")
    if not form_data["subject"]:
        errors.append("Ämne (subject) is required")

    if errors:
        return render_template(
            "data_manual.html", errors=errors, form_data=form_data
        )

    # Parse date if provided
    record_date = None
    if form_data["date"]:
        try:
            record_date = datetime.fromisoformat(form_data["date"])
        except (ValueError, TypeError):
            record_date = None

    # Handle file attachments
    from models import Attachment
    from attachment_store import save_attachments

    attachments = []
    uploaded_files = request.files.getlist("attachments")
    for f in uploaded_files:
        if f.filename and f.filename != "":
            content = f.read()
            attachments.append(
                Attachment(
                    filename=f.filename,
                    content_type=f.content_type or "application/octet-stream",
                    content=content,
                )
            )

    record = EmailRecord(
        sender=form_data["sender"],
        recipient=form_data["recipient"],
        subject=form_data["subject"],
        date=record_date,
        body_text=form_data["body_text"],
        source_file="manual entry",
        attachments=attachments,
    )

    # Save attachment files to disk
    if attachments:
        save_attachments(record.id, record.attachments, current_app.instance_path)

    data_store.add_record(record)
    flash("Record added successfully.", "success")
    return redirect(url_for("data.data_index"))


@data_bp.route("/record/<record_id>/analyze", methods=["POST"])
def trigger_analysis(record_id):
    """Trigger analysis for selected PDF attachments."""
    record = data_store.get_record(record_id)
    if record is None:
        abort(404)

    attachment_ids = request.form.getlist("attachment_ids")
    if not attachment_ids:
        flash("Inga bilagor valda för analys.", "error")
        return redirect(url_for("data.record_detail", record_id=record_id))

    config = get_analysis_config()
    success_count = 0
    error_count = 0

    for att_id_str in attachment_ids:
        try:
            att_id = int(att_id_str)
        except (ValueError, TypeError):
            error_count += 1
            continue

        att = db.session.get(AttachmentModel, att_id)
        if att is None or att.email_record_id != record_id:
            error_count += 1
            continue

        if not att.file_path:
            error_count += 1
            continue

        full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
        if not os.path.isfile(full_path):
            error_count += 1
            continue

        # Run analysis
        result = run_analysis(att_id, full_path, config)
        result_json = serialize_result(result)

        # Replace existing result if present
        existing = AnalysisResultModel.query.filter_by(attachment_id=att_id).first()
        if existing:
            existing.status = result.status
            existing.result_json = result_json
            existing.created_at = datetime.now()
        else:
            new_result = AnalysisResultModel(
                attachment_id=att_id,
                status=result.status,
                created_at=datetime.now(),
                result_json=result_json,
            )
            db.session.add(new_result)

        db.session.commit()
        success_count += 1

    if success_count > 0:
        flash(f"Analys klar för {success_count} bilaga(or).", "success")
    if error_count > 0:
        flash(f"{error_count} bilaga(or) kunde inte analyseras.", "error")

    return redirect(url_for("data.record_detail", record_id=record_id))


@data_bp.route("/analys")
def analys_index():
    """Render the Analys sub-tab listing all analyses grouped by email."""
    results = (
        db.session.query(AnalysisResultModel)
        .join(AttachmentModel, AnalysisResultModel.attachment_id == AttachmentModel.id)
        .join(EmailRecordModel, AttachmentModel.email_record_id == EmailRecordModel.id)
        .order_by(EmailRecordModel.subject, AnalysisResultModel.created_at.desc())
        .all()
    )

    # Group by email record
    grouped = {}
    for r in results:
        email = r.attachment.email_record
        if email.id not in grouped:
            grouped[email.id] = {
                "email": email,
                "analyses": [],
            }
        grouped[email.id]["analyses"].append(r)

    return render_template(
        "data_analys.html",
        grouped=grouped,
        active_tab="analys",
    )


@data_bp.route("/analys/<int:analysis_id>")
def analys_detail(analysis_id):
    """Render analysis detail view with material items table."""
    analysis = db.session.get(AnalysisResultModel, analysis_id)
    if analysis is None:
        abort(404)

    result = deserialize_result(analysis.result_json)

    return render_template(
        "data_analys_detail.html",
        analysis=analysis,
        result=result,
        active_tab="analys",
    )


@data_bp.route("/analys/<int:analysis_id>/rerun", methods=["POST"])
def rerun_analysis(analysis_id):
    """Re-run analysis for a specific attachment."""
    analysis = db.session.get(AnalysisResultModel, analysis_id)
    if analysis is None:
        abort(404)

    att = db.session.get(AttachmentModel, analysis.attachment_id)
    if att is None or not att.file_path:
        flash("Bilagan kunde inte hittas.", "error")
        return redirect(url_for("data.analys_detail", analysis_id=analysis_id))

    full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
    if not os.path.isfile(full_path):
        flash("Bilagefilen saknas på disk.", "error")
        return redirect(url_for("data.analys_detail", analysis_id=analysis_id))

    config = get_analysis_config()
    result = run_analysis(att.id, full_path, config)
    result_json = serialize_result(result)

    analysis.status = result.status
    analysis.result_json = result_json
    analysis.created_at = datetime.now()
    db.session.commit()

    flash("Analysen har körts om.", "success")
    return redirect(url_for("data.analys_detail", analysis_id=analysis_id))


# --- Page Image API (Task 2.1) ---

@data_bp.route("/api/page-image/<int:attachment_id>/<int:page_number>")
def page_image(attachment_id, page_number):
    """Serve a rendered PDF page as PNG with X-Page-Count header."""
    import io

    import fitz

    from analysis.page_renderer import render_page

    att = db.session.get(AttachmentModel, attachment_id)
    if not att or not att.file_path:
        abort(404)

    full_path = get_attachment_full_path(att.file_path, current_app.instance_path)
    if not os.path.isfile(full_path):
        abort(404)

    # Get total pages
    try:
        doc = fitz.open(full_path)
        total_pages = len(doc)
        doc.close()
    except Exception:
        abort(404)

    if page_number < 1 or page_number > total_pages:
        abort(404)

    image = render_page(full_path, page_number, dpi=150)
    if image is None:
        abort(404)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    response = send_file(buffer, mimetype="image/png")
    response.headers["X-Page-Count"] = str(total_pages)
    return response


# --- Annotations CRUD API (Tasks 3.1-3.4) ---

@data_bp.route("/api/annotations/<int:attachment_id>/<int:page_number>")
def get_annotations(attachment_id, page_number):
    """Get annotations for a specific attachment page as JSON array."""
    annotations = AnnotationModel.query.filter_by(
        attachment_id=attachment_id, page_number=page_number
    ).all()
    result = []
    for ann in annotations:
        group_color = None
        if ann.group_id is not None and ann.group is not None:
            group_color = ann.group.color
        result.append({
            "id": ann.id,
            "attachment_id": ann.attachment_id,
            "page_number": ann.page_number,
            "x": ann.x,
            "y": ann.y,
            "width": ann.width,
            "height": ann.height,
            "group_id": ann.group_id,
            "group_color": group_color,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })
    return jsonify(result)


@data_bp.route("/api/annotations", methods=["POST"])
def create_annotation():
    """Create a new annotation. Returns 201 with created annotation."""
    data = request.get_json(force=True)
    validated, error = validate_annotation_data(data)
    if error:
        return jsonify({"error": error}), 400

    # Verify attachment exists
    att = db.session.get(AttachmentModel, validated["attachment_id"])
    if att is None:
        abort(404)

    # Handle optional group_id
    group_id = data.get("group_id")
    group_color = None
    if group_id is not None:
        try:
            group_id = int(group_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid group_id"}), 400
        group = db.session.get(AnnotationGroupModel, group_id)
        if group is None:
            return jsonify({"error": "Group not found"}), 404
        if group.attachment_id != validated["attachment_id"]:
            return jsonify({"error": "Group does not belong to the same attachment"}), 400
        group_color = group.color

    ann = AnnotationModel(
        attachment_id=validated["attachment_id"],
        page_number=validated["page_number"],
        x=validated["x"],
        y=validated["y"],
        width=validated["width"],
        height=validated["height"],
        group_id=group_id,
    )
    db.session.add(ann)
    db.session.commit()

    return jsonify({
        "id": ann.id,
        "attachment_id": ann.attachment_id,
        "page_number": ann.page_number,
        "x": ann.x,
        "y": ann.y,
        "width": ann.width,
        "height": ann.height,
        "group_id": ann.group_id,
        "group_color": group_color,
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
    }), 201


@data_bp.route("/api/annotations/<int:annotation_id>", methods=["PUT"])
def update_annotation(annotation_id):
    """Update an annotation's position/size. Returns 200 with updated annotation."""
    ann = db.session.get(AnnotationModel, annotation_id)
    if ann is None:
        abort(404)

    data = request.get_json(force=True)

    # Validate coordinate fields if present
    for field in ["x", "y", "width", "height"]:
        if field in data:
            try:
                val = float(data[field])
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid value for {field}"}), 400
            if not (0.0 <= val <= 1.0):
                return jsonify({"error": f"{field} must be between 0.0 and 1.0"}), 400
            setattr(ann, field, val)

    if "page_number" in data:
        try:
            page = int(data["page_number"])
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid page_number"}), 400
        if page < 1:
            return jsonify({"error": "page_number must be >= 1"}), 400
        ann.page_number = page

    db.session.commit()

    return jsonify({
        "id": ann.id,
        "attachment_id": ann.attachment_id,
        "page_number": ann.page_number,
        "x": ann.x,
        "y": ann.y,
        "width": ann.width,
        "height": ann.height,
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
    })


@data_bp.route("/api/annotations/<int:annotation_id>", methods=["DELETE"])
def delete_annotation(annotation_id):
    """Delete an annotation. Returns 200 with success flag."""
    ann = db.session.get(AnnotationModel, annotation_id)
    if ann is None:
        abort(404)

    db.session.delete(ann)
    db.session.commit()

    return jsonify({"success": True})


@data_bp.route("/api/annotations/<int:attachment_id>/unassigned", methods=["DELETE"])
def delete_unassigned_annotations(attachment_id):
    """Delete all annotations without a group for the given attachment.

    Returns 200 with count of deleted annotations.
    """
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None:
        abort(404)

    count = AnnotationModel.query.filter_by(
        attachment_id=attachment_id, group_id=None
    ).delete()
    db.session.commit()

    return jsonify({"success": True, "deleted_count": count})


# --- Groups CRUD API (Task 2.1) ---

@data_bp.route("/api/groups/<int:attachment_id>")
def get_groups(attachment_id):
    """Get all annotation groups for an attachment, ordered by display_order.

    Each group includes an annotation_count field.
    Returns 404 if attachment doesn't exist.
    """
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None:
        abort(404)

    groups = AnnotationGroupModel.query.filter_by(
        attachment_id=attachment_id
    ).order_by(AnnotationGroupModel.display_order).all()

    result = []
    for group in groups:
        annotation_count = AnnotationModel.query.filter_by(group_id=group.id).count()
        result.append({
            "id": group.id,
            "attachment_id": group.attachment_id,
            "name": group.name,
            "color": group.color,
            "display_order": group.display_order,
            "created_at": group.created_at.isoformat() if group.created_at else None,
            "annotation_count": annotation_count,
        })

    return jsonify(result)


@data_bp.route("/api/groups", methods=["POST"])
def create_group():
    """Create a new annotation group.

    Accepts JSON body with attachment_id (required), name (required), color (optional).
    Auto-assigns display_order as max(display_order)+1 for the attachment.
    Returns 201 with created group including annotation_count=0.
    """
    data = request.get_json(force=True)

    # attachment_id is required
    if "attachment_id" not in data:
        return jsonify({"error": "Missing required field: attachment_id"}), 400

    try:
        attachment_id = int(data["attachment_id"])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid attachment_id"}), 400

    # Check attachment exists
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None:
        abort(404)

    # name is required for creation
    if "name" not in data:
        return jsonify({"error": "Group name cannot be empty"}), 400

    validated, error = validate_group_data(data, attachment_id=attachment_id)
    if error:
        return jsonify({"error": error}), 400

    # Auto-assign display_order as max+1
    max_order = db.session.query(func.max(AnnotationGroupModel.display_order)).filter_by(
        attachment_id=attachment_id
    ).scalar()
    next_order = (max_order or 0) + 1

    color = validated.get("color", "#3498db")

    group = AnnotationGroupModel(
        attachment_id=attachment_id,
        name=validated["name"],
        color=color,
        display_order=next_order,
    )
    db.session.add(group)
    db.session.commit()

    return jsonify({
        "id": group.id,
        "attachment_id": group.attachment_id,
        "name": group.name,
        "color": group.color,
        "display_order": group.display_order,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "annotation_count": 0,
    }), 201


@data_bp.route("/api/groups/<int:group_id>", methods=["PUT"])
def update_group(group_id):
    """Update an annotation group (name, color, display_order).

    Validates name uniqueness (excluding self) and color format.
    Returns 200 with updated group. Returns 404 if group not found, 400 for invalid data.
    """
    group = db.session.get(AnnotationGroupModel, group_id)
    if group is None:
        abort(404)

    data = request.get_json(force=True)

    validated, error = validate_group_data(
        data, attachment_id=group.attachment_id, group_id=group_id
    )
    if error:
        return jsonify({"error": error}), 400

    # Apply validated updates
    if "name" in validated:
        group.name = validated["name"]
    if "color" in validated:
        group.color = validated["color"]
    if "display_order" in validated:
        group.display_order = validated["display_order"]

    db.session.commit()

    annotation_count = AnnotationModel.query.filter_by(group_id=group.id).count()

    return jsonify({
        "id": group.id,
        "attachment_id": group.attachment_id,
        "name": group.name,
        "color": group.color,
        "display_order": group.display_order,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "annotation_count": annotation_count,
    })


@data_bp.route("/api/groups/<int:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """Delete an annotation group.

    SQLAlchemy FK SET NULL handles unassigning annotations.
    Returns 200 with {"success": true}. Returns 404 if group not found.
    """
    group = db.session.get(AnnotationGroupModel, group_id)
    if group is None:
        abort(404)

    # Manually unassign annotations since SQLite may not enforce ON DELETE SET NULL
    AnnotationModel.query.filter_by(group_id=group_id).update({"group_id": None})
    db.session.delete(group)
    db.session.commit()

    return jsonify({"success": True})


@data_bp.route("/api/annotations/<int:annotation_id>/group", methods=["PATCH"])
def assign_annotation_group(annotation_id):
    """Assign or unassign an annotation to/from a group.

    Accepts JSON body: {"group_id": <int>} or {"group_id": null}.
    Validates annotation exists (404), group exists (404 if non-null),
    and group belongs to same attachment as annotation (400 if mismatch).
    Returns 200 with annotation JSON including group_id and group_color.
    """
    ann = db.session.get(AnnotationModel, annotation_id)
    if ann is None:
        abort(404)

    data = request.get_json(force=True)
    group_id = data.get("group_id")

    group_color = None
    if group_id is not None:
        # Validate group exists
        group = db.session.get(AnnotationGroupModel, group_id)
        if group is None:
            abort(404)
        # Validate group belongs to same attachment
        if group.attachment_id != ann.attachment_id:
            return jsonify({"error": "Group does not belong to the same attachment"}), 400
        group_color = group.color

    ann.group_id = group_id
    db.session.commit()

    return jsonify({
        "id": ann.id,
        "attachment_id": ann.attachment_id,
        "page_number": ann.page_number,
        "x": ann.x,
        "y": ann.y,
        "width": ann.width,
        "height": ann.height,
        "group_id": ann.group_id,
        "group_color": group_color,
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
    })


# --- Detection API (Task 7) ---

AUTO_DETECT_COLORS = ["#e74c3c", "#27ae60", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e", "#2980b9"]


@data_bp.route("/api/detect/<int:attachment_id>/<int:page_number>", methods=["POST"])
def detect_elements(attachment_id, page_number):
    """Trigger element detection for a specific PDF page.

    Optional JSON body: {"group_id": <int>}
    If group_id omitted, creates new "Auto-detected" group.

    Returns 200:
    {
        "annotations": [...],
        "group": {"id": ..., "name": ..., "color": ...},
        "detection_method": "vector" | "vision",
        "count": <int>
    }

    Errors: 404 (attachment/file not found), 400 (page out of range), 503 (vision unavailable)
    """
    import fitz
    import requests
    from analysis.detection_dispatcher import run_detection

    # Validate attachment exists
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None or not att.file_path:
        abort(404)

    # Resolve PDF file path
    file_path = get_attachment_full_path(att.file_path, current_app.instance_path)
    if not os.path.isfile(file_path):
        abort(404)

    # Validate page_number is within PDF page range
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        doc.close()
    except Exception:
        abort(404)

    if page_number < 1 or page_number > total_pages:
        return jsonify({"error": f"Page number out of range (1-{total_pages})"}), 400

    # Run detection
    config = get_analysis_config()
    try:
        results, method = run_detection(file_path, page_number, config)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Vision service unavailable"}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Vision service timeout"}), 503

    # Handle group assignment
    body = request.get_json(silent=True) or {}
    group_id = body.get("group_id")

    if group_id is not None:
        # Validate provided group
        group = db.session.get(AnnotationGroupModel, group_id)
        if group is None:
            abort(404)
        if group.attachment_id != attachment_id:
            return jsonify({"error": "Group does not belong to this attachment"}), 400
    else:
        # Create new auto-detected group
        group = _create_auto_detect_group(attachment_id)

    # Create annotations for each detection result
    annotations = []
    for result in results:
        ann = AnnotationModel(
            attachment_id=attachment_id,
            page_number=page_number,
            x=result.x,
            y=result.y,
            width=result.width,
            height=result.height,
            group_id=group.id,
        )
        db.session.add(ann)
        annotations.append(ann)

    db.session.commit()

    # Build response
    annotation_list = []
    for ann in annotations:
        annotation_list.append({
            "id": ann.id,
            "attachment_id": ann.attachment_id,
            "page_number": ann.page_number,
            "x": ann.x,
            "y": ann.y,
            "width": ann.width,
            "height": ann.height,
            "group_id": ann.group_id,
            "group_color": group.color,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    return jsonify({
        "annotations": annotation_list,
        "group": {"id": group.id, "name": group.name, "color": group.color},
        "detection_method": method,
        "count": len(annotations),
    })


def _create_auto_detect_group(attachment_id: int) -> AnnotationGroupModel:
    """Create a new auto-detect group with a unique name and distinct color.

    Tries "Auto-detected", then "Auto-detected 2", "Auto-detected 3", etc.
    Picks a color not already used by existing groups for this attachment.
    """
    # Find existing groups for this attachment
    existing_groups = AnnotationGroupModel.query.filter_by(
        attachment_id=attachment_id
    ).all()
    existing_names = {g.name for g in existing_groups}
    existing_colors = {g.color for g in existing_groups}

    # Determine unique name
    name = "Auto-detected"
    if name in existing_names:
        counter = 2
        while f"Auto-detected {counter}" in existing_names:
            counter += 1
        name = f"Auto-detected {counter}"

    # Pick a color not already used
    color = AUTO_DETECT_COLORS[0]  # default fallback
    for c in AUTO_DETECT_COLORS:
        if c not in existing_colors:
            color = c
            break

    # Determine display_order
    max_order = db.session.query(func.max(AnnotationGroupModel.display_order)).filter_by(
        attachment_id=attachment_id
    ).scalar()
    next_order = (max_order or 0) + 1

    group = AnnotationGroupModel(
        attachment_id=attachment_id,
        name=name,
        color=color,
        display_order=next_order,
    )
    db.session.add(group)
    db.session.flush()  # Get the group.id before creating annotations

    return group


# --- Plan Tab Listing (Task 5.1) ---

@data_bp.route("/plan")
def plan_index():
    """Render the Plan tab listing PDFs exported to plan, grouped by email."""
    # Query attachments marked in_plan, grouped by email
    plan_attachments = (
        db.session.query(AttachmentModel)
        .filter(AttachmentModel.in_plan == True)
        .filter(AttachmentModel.filename.ilike("%.pdf"))
        .all()
    )

    # Group by email record
    grouped = {}
    for att in plan_attachments:
        email = att.email_record
        if email.id not in grouped:
            grouped[email.id] = {
                "email": email,
                "attachments": [],
            }
        grouped[email.id]["attachments"].append(att)

    return render_template(
        "data_plan.html",
        grouped=grouped,
        active_tab="plan",
    )


# --- Plan Editor Page (Task 6.1) ---

@data_bp.route("/plan/<int:attachment_id>")
def plan_editor(attachment_id):
    """Render the Plan Editor page for a specific PDF attachment."""
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None:
        abort(404)
    if not att.filename.lower().endswith(".pdf"):
        abort(404)

    return render_template(
        "data_plan_editor.html",
        attachment=att,
        active_tab="plan",
    )


@data_bp.route("/plan/<int:attachment_id>/remove", methods=["POST"])
def remove_from_plan(attachment_id):
    """Remove a PDF attachment from the Plan (unmark in_plan)."""
    att = db.session.get(AttachmentModel, attachment_id)
    if att is None:
        abort(404)
    att.in_plan = False
    db.session.commit()
    return jsonify({"success": True})
