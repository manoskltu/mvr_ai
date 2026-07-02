"""Renders PDF pages to PIL Images for OCR or CV processing."""

import logging

import fitz
from PIL import Image

logger = logging.getLogger(__name__)


def render_page(file_path: str, page_number: int, dpi: int = 200) -> Image.Image | None:
    """Render a single PDF page to a PIL Image at the specified DPI.

    Args:
        file_path: Path to the PDF file.
        page_number: 1-indexed page number to render.
        dpi: Resolution for rendering (default 200).

    Returns:
        PIL Image of the rendered page, or None if rendering fails.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.warning("Failed to open PDF for rendering %s: %s", file_path, e)
        return None

    try:
        # Convert 1-indexed page number to 0-indexed
        page_idx = page_number - 1

        if page_idx < 0 or page_idx >= len(doc):
            logger.warning(
                "Page number %d out of range for %s (total: %d)",
                page_number,
                file_path,
                len(doc),
            )
            return None

        page = doc[page_idx]

        # Calculate zoom factor from DPI (default PDF is 72 DPI)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        # Render page to pixmap
        pixmap = page.get_pixmap(matrix=matrix)

        # Convert pixmap to PIL Image
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

        return image

    except Exception as e:
        logger.warning(
            "Failed to render page %d of %s: %s", page_number, file_path, e
        )
        return None
    finally:
        doc.close()
