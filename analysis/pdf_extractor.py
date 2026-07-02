"""PyMuPDF wrapper for extracting text and geometry from PDF pages."""

import logging
from dataclasses import dataclass, field

import fitz

logger = logging.getLogger(__name__)


@dataclass
class TextBlock:
    """A text element extracted from a PDF page with its position."""

    text: str
    x: float
    y: float
    width: float
    height: float
    page_number: int


@dataclass
class LineSegment:
    """A vector line segment extracted from a PDF page."""

    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int


@dataclass
class PageExtraction:
    """Extraction results for a single PDF page."""

    page_number: int
    text_blocks: list[TextBlock] = field(default_factory=list)
    lines: list[LineSegment] = field(default_factory=list)
    needs_ocr: bool = False


@dataclass
class PdfExtractionResult:
    """Complete extraction results for a PDF document."""

    pages: list[PageExtraction] = field(default_factory=list)
    total_pages: int = 0
    truncated: bool = False
    error: str | None = None


def extract(
    file_path: str, max_pages: int = 50, ocr_threshold: int = 10
) -> PdfExtractionResult:
    """Extract text blocks and line geometry from all pages of a PDF.

    Args:
        file_path: Path to the PDF file.
        max_pages: Maximum number of pages to process.
        ocr_threshold: Minimum character count per page before flagging for OCR.

    Returns:
        PdfExtractionResult with extracted pages, or error if the file is unreadable.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", file_path, e)
        return PdfExtractionResult(error=str(e))

    try:
        total_pages = len(doc)
        truncated = total_pages > max_pages
        pages_to_process = min(total_pages, max_pages)

        pages: list[PageExtraction] = []

        for page_idx in range(pages_to_process):
            page_number = page_idx + 1
            page = doc[page_idx]

            # Extract text blocks
            text_blocks = _extract_text_blocks(page, page_number)

            # Extract vector lines
            lines = _extract_lines(page, page_number)

            # Determine if OCR is needed
            total_chars = sum(len(tb.text) for tb in text_blocks)
            needs_ocr = total_chars < ocr_threshold

            pages.append(
                PageExtraction(
                    page_number=page_number,
                    text_blocks=text_blocks,
                    lines=lines,
                    needs_ocr=needs_ocr,
                )
            )

        return PdfExtractionResult(
            pages=pages,
            total_pages=total_pages,
            truncated=truncated,
        )
    except Exception as e:
        logger.error("Error extracting PDF %s: %s", file_path, e)
        return PdfExtractionResult(error=str(e))
    finally:
        doc.close()


def _extract_text_blocks(page: fitz.Page, page_number: int) -> list[TextBlock]:
    """Extract text blocks with positions from a PDF page using get_text('dict')."""
    text_blocks: list[TextBlock] = []

    try:
        page_dict = page.get_text("dict")
    except Exception as e:
        logger.warning("Failed to extract text from page %d: %s", page_number, e)
        return text_blocks

    for block in page_dict.get("blocks", []):
        # Only process text blocks (type 0), skip image blocks (type 1)
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                bbox = span.get("bbox", (0, 0, 0, 0))
                x = bbox[0]
                y = bbox[1]
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]

                text_blocks.append(
                    TextBlock(
                        text=text,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        page_number=page_number,
                    )
                )

    return text_blocks


def _extract_lines(page: fitz.Page, page_number: int) -> list[LineSegment]:
    """Extract vector line segments from a PDF page using get_drawings()."""
    lines: list[LineSegment] = []

    try:
        drawings = page.get_drawings()
    except Exception as e:
        logger.warning("Failed to extract drawings from page %d: %s", page_number, e)
        return lines

    for drawing in drawings:
        for item in drawing.get("items", []):
            # Each item is a tuple like ("l", p1, p2) for lines,
            # ("re", rect) for rectangles, ("c", p1, p2, p3, p4) for curves, etc.
            if item[0] == "l":
                # Line: ("l", Point(x0,y0), Point(x1,y1))
                p1 = item[1]
                p2 = item[2]
                lines.append(
                    LineSegment(
                        x0=p1.x,
                        y0=p1.y,
                        x1=p2.x,
                        y1=p2.y,
                        page_number=page_number,
                    )
                )

    return lines
