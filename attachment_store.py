"""Filesystem operations for attachment persistence.

Handles sanitization, deduplication, and saving of attachment binary content
to a managed directory structure on disk.
"""

import os

from models import Attachment


def sanitize_filename(filename: str) -> str:
    """Remove filesystem-unsafe characters, preserve Swedish chars.

    Rules:
    - Remove null bytes (\\x00)
    - Replace path separators (/ and \\) with underscore _
    - Preserve all other characters including Swedish å, ä, ö
    - Enforce max 255 bytes UTF-8 encoded filename length
    - Fall back to "attachment" if filename is empty after sanitization

    Args:
        filename: The original filename to sanitize.

    Returns:
        A filesystem-safe filename string.
    """
    # Remove null bytes
    result = filename.replace("\x00", "")
    # Replace path separators with underscore
    result = result.replace("/", "_").replace("\\", "_")

    # If empty after sanitization, use fallback
    if not result.strip():
        return "attachment"

    # Enforce max 255 bytes UTF-8 encoded length
    encoded = result.encode("utf-8")
    if len(encoded) > 255:
        # Truncate by removing characters from the end until we fit
        while len(result.encode("utf-8")) > 255:
            result = result[:-1]
        if not result.strip():
            return "attachment"

    return result


def deduplicate_filename(filename: str, existing: set[str]) -> str:
    """Append _1, _2 etc. before the file extension when collisions occur.

    Args:
        filename: The filename to deduplicate.
        existing: Set of filenames already used in the directory.

    Returns:
        A unique filename that does not collide with existing names.
    """
    if filename not in existing:
        return filename

    # Split into name and extension
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = f"{base}_{counter}{ext}"
        if candidate not in existing:
            return candidate
        counter += 1


def save_attachments(
    record_id: str, attachments: list[Attachment], instance_path: str
) -> list[Attachment]:
    """Write attachment files to disk, populate file_path on each Attachment.

    Creates the directory instance_path/attachments/<record_id>/ if needed.
    Skips attachments with content=None. Overwrites existing files on re-import.

    Args:
        record_id: The unique record ID for directory naming.
        attachments: List of Attachment objects (some may have content bytes).
        instance_path: The Flask instance path (base directory).

    Returns:
        The same list of attachments with file_path populated for those saved.
    """
    # Create target directory
    target_dir = os.path.join(instance_path, "attachments", record_id)
    os.makedirs(target_dir, exist_ok=True)

    used_filenames: set[str] = set()

    for att in attachments:
        if att.content is None:
            continue

        # Sanitize and deduplicate
        safe_name = sanitize_filename(att.filename)
        unique_name = deduplicate_filename(safe_name, used_filenames)
        used_filenames.add(unique_name)

        # Write bytes to disk
        file_full_path = os.path.join(target_dir, unique_name)
        with open(file_full_path, "wb") as f:
            f.write(att.content)

        # Set relative path from instance directory
        att.file_path = os.path.join("attachments", record_id, unique_name)

    return attachments


def get_attachment_full_path(file_path: str, instance_path: str) -> str:
    """Resolve relative file_path to absolute path for serving.

    Args:
        file_path: Relative path from instance directory.
        instance_path: The Flask instance path (base directory).

    Returns:
        Full absolute path to the attachment file.
    """
    return os.path.join(instance_path, file_path)
