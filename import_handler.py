"""Import handler for processing .eml files from uploads or the assets directory.

Orchestrates file reception and parsing. Bridges Flask routes and the parser.
"""

import os
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

import data_store
from attachment_store import save_attachments
from eml_parser import EmlParseError, parse_eml
from models import ImportError, ImportResult


def import_uploaded_files(files: list[FileStorage]) -> ImportResult:
    """Parse uploaded .eml files and add them to the data store.

    Each file is processed independently — one failure does not abort the batch.

    Args:
        files: List of werkzeug FileStorage objects from the upload.

    Returns:
        ImportResult with successful records and any errors encountered.
    """
    result = ImportResult()

    for file in files:
        filename = file.filename or "unnamed"

        if not filename.lower().endswith(".eml"):
            result.errors.append(
                ImportError(filename=filename, message=f"Not a valid .eml file: {filename}")
            )
            continue

        try:
            file_content = file.read()
            record = parse_eml(file_content)
            record.source_file = filename
            # Save attachment files to disk
            try:
                save_attachments(record.id, record.attachments, current_app.instance_path)
            except OSError as e:
                result.errors.append(
                    ImportError(filename=filename, message=f"Failed to save attachments: {e}")
                )
                continue
            data_store.add_record(record)
            result.success.append(record)
        except EmlParseError as e:
            result.errors.append(
                ImportError(filename=filename, message=str(e))
            )

    return result


def import_from_assets(file_paths: list[str]) -> ImportResult:
    """Parse .eml files from the assets directory and add them to the data store.

    Each file is processed independently — one failure does not abort the batch.

    Args:
        file_paths: List of relative file paths (relative to project root,
                    e.g. "assets/ex1/file.eml").

    Returns:
        ImportResult with successful records and any errors encountered.
    """
    result = ImportResult()

    for file_path in file_paths:
        try:
            path = Path(file_path)
            file_content = path.read_bytes()
            record = parse_eml(file_content)
            record.source_file = file_path
            # Save attachment files to disk
            try:
                save_attachments(record.id, record.attachments, current_app.instance_path)
            except OSError as e:
                result.errors.append(
                    ImportError(filename=file_path, message=f"Failed to save attachments: {e}")
                )
                continue
            data_store.add_record(record)
            result.success.append(record)
        except FileNotFoundError:
            result.errors.append(
                ImportError(filename=file_path, message=f"File not found: {file_path}")
            )
        except PermissionError:
            result.errors.append(
                ImportError(filename=file_path, message=f"Permission denied: {file_path}")
            )
        except EmlParseError as e:
            result.errors.append(
                ImportError(filename=file_path, message=str(e))
            )

    return result


def list_asset_eml_files() -> list[str]:
    """Recursively scan the assets/ directory for files ending in .eml.

    Returns:
        Sorted list of relative paths (relative to project root) for all
        .eml files found under assets/.
    """
    assets_dir = Path("assets")
    if not assets_dir.is_dir():
        return []

    eml_files = []
    for path in assets_dir.rglob("*.eml"):
        if path.is_file():
            eml_files.append(str(path))

    return sorted(eml_files)
