"""Flask routes for the Data Tab feature.

Blueprint with all Data Tab endpoints for importing, viewing, and
managing email records. Split into sub-tabs: E-post (records), Import, and Analys.
"""

import os
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

import data_store
import import_handler
from attachment_store import get_attachment_full_path
from db_models import AnalysisResultModel, AnnotationModel, AttachmentModel, EmailRecordModel, db
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


@data_bp.route("/")
def data_index():
    """Render the E-post sub-tab with records table only."""
    records = data_store.get_all_records()
    return render_template("data_emails.html", records=records, active_tab="emails")


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
        return redirect(url_for("data.import_index"))

    result = import_handler.import_uploaded_files(files)

    if result.success:
        flash(
            f"Successfully imported {len(result.success)} file(s).", "success"
        )
    for err in result.errors:
        flash(f"Error importing {err.filename}: {err.message}", "error")

    return redirect(url_for("data.import_index"))


@data_bp.route("/import-assets", methods=["POST"])
def import_assets():
    """Import selected .eml files from the assets directory."""
    file_paths = request.form.getlist("asset_files")

    if not file_paths:
        flash("No asset files selected for import.", "error")
        return redirect(url_for("data.import_index"))

    result = import_handler.import_from_assets(file_paths)

    if result.success:
        flash(
            f"Successfully imported {len(result.success)} file(s) from assets.",
            "success",
        )
    for err in result.errors:
        flash(f"Error importing {err.filename}: {err.message}", "error")

    return redirect(url_for("data.import_index"))


@data_bp.route("/record/<record_id>")
def record_detail(record_id):
    """View single record details. Returns 404 if not found."""
    record = data_store.get_record(record_id)
    if record is None:
        abort(404)

    # Get analysis status for each attachment
    analysis_status = {}
    has_analysis_results = False
    for att in record.attachments:
        if att.id:
            result = AnalysisResultModel.query.filter_by(attachment_id=att.id).first()
            if result:
                analysis_status[att.id] = result.status
                has_analysis_results = True

    return render_template(
        "data_detail.html",
        record=record,
        analysis_status=analysis_status,
        has_analysis_results=has_analysis_results,
    )


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


@data_bp.route("/manual")
def manual_form():
    """Render the manual entry form."""
    return render_template("data_manual.html", errors=[], form_data={})


@data_bp.route("/manual", methods=["POST"])
def manual_submit():
    """Validate and submit manual entry."""
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

    record = EmailRecord(
        sender=form_data["sender"],
        recipient=form_data["recipient"],
        subject=form_data["subject"],
        date=record_date,
        body_text=form_data["body_text"],
        source_file="manual entry",
    )

    data_store.add_record(record)
    flash("Record added successfully.", "success")
    return redirect(url_for("data.import_index"))


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
            existing.created_at = datetime.utcnow()
        else:
            new_result = AnalysisResultModel(
                attachment_id=att_id,
                status=result.status,
                created_at=datetime.utcnow(),
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
    analysis.created_at = datetime.utcnow()
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
        result.append({
            "id": ann.id,
            "attachment_id": ann.attachment_id,
            "page_number": ann.page_number,
            "x": ann.x,
            "y": ann.y,
            "width": ann.width,
            "height": ann.height,
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

    ann = AnnotationModel(
        attachment_id=validated["attachment_id"],
        page_number=validated["page_number"],
        x=validated["x"],
        y=validated["y"],
        width=validated["width"],
        height=validated["height"],
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


# --- Plan Tab Listing (Task 5.1) ---

@data_bp.route("/plan")
def plan_index():
    """Render the Plan sub-tab listing emails with PDF attachments."""
    # Query email records that have at least one PDF attachment
    records_with_pdfs = (
        db.session.query(EmailRecordModel)
        .join(AttachmentModel, EmailRecordModel.id == AttachmentModel.email_record_id)
        .filter(AttachmentModel.filename.ilike("%.pdf"))
        .distinct()
        .all()
    )

    return render_template(
        "data_plan.html",
        records=records_with_pdfs,
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
