"""Identifies title blocks and groups text by spatial proximity."""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TitleBlockInfo:
    """Metadata extracted from a drawing title block."""

    drawing_number: str | None = None
    revision: str | None = None
    sheet_title: str | None = None
    page_number: int = 0


def find_title_block(
    text_blocks: list[Any],
    page_width: float,
    page_height: float,
    page_number: int,
) -> TitleBlockInfo | None:
    """Identify and extract title block metadata from bottom-right region.

    Looks for text blocks in the bottom-right 25% of the page (x > 0.75*width
    AND y > 0.75*height) and searches for Swedish field labels.

    Accepts both TextBlock and OcrTextBlock (duck typing — both have text, x, y
    attributes).

    Args:
        text_blocks: List of text blocks with text, x, y attributes.
        page_width: Width of the page in points.
        page_height: Height of the page in points.
        page_number: Page number for the result.

    Returns:
        TitleBlockInfo if title block patterns are found, None otherwise.
    """
    # Filter text blocks to bottom-right 25% region
    x_threshold = 0.75 * page_width
    y_threshold = 0.75 * page_height

    region_blocks = [
        block
        for block in text_blocks
        if block.x > x_threshold and block.y > y_threshold
    ]

    if not region_blocks:
        return None

    drawing_number: str | None = None
    revision: str | None = None
    sheet_title: str | None = None

    # Sort blocks by position (top to bottom, left to right) for sequential parsing
    region_blocks.sort(key=lambda b: (b.y, b.x))

    # Search for Swedish field labels and extract the next text value
    for i, block in enumerate(region_blocks):
        text = block.text.strip()
        text_lower = text.lower()

        # Check for drawing number label
        if "ritningsnr" in text_lower or "ritn" in text_lower:
            # The drawing number might be in this block after the label,
            # or in the next block
            value = _extract_value_after_label(text, ["ritningsnr", "ritn"])
            if value:
                drawing_number = value
            elif i + 1 < len(region_blocks):
                next_text = region_blocks[i + 1].text.strip()
                if next_text and not _is_label(next_text):
                    drawing_number = next_text

        # Check for revision label
        elif text_lower.startswith("rev") and len(text_lower) <= 10:
            value = _extract_value_after_label(text, ["rev"])
            if value:
                revision = value
            elif i + 1 < len(region_blocks):
                next_text = region_blocks[i + 1].text.strip()
                if next_text and not _is_label(next_text):
                    revision = next_text

        # Check for sheet title label
        elif "benämning" in text_lower or "benamning" in text_lower:
            value = _extract_value_after_label(text, ["benämning", "benamning"])
            if value:
                sheet_title = value
            elif i + 1 < len(region_blocks):
                next_text = region_blocks[i + 1].text.strip()
                if next_text and not _is_label(next_text):
                    sheet_title = next_text

    # Only return a TitleBlockInfo if we found at least one field
    if drawing_number is None and revision is None and sheet_title is None:
        return None

    return TitleBlockInfo(
        drawing_number=drawing_number,
        revision=revision,
        sheet_title=sheet_title,
        page_number=page_number,
    )


def _extract_value_after_label(text: str, labels: list[str]) -> str | None:
    """Extract the value part after a label, separated by colon or whitespace.

    Tries labels longest-first to avoid partial matches. Once a label is found
    in the text, shorter labels are not attempted (to prevent extracting parts
    of the label itself as a value).
    """
    text_lower = text.lower()

    # Sort labels longest first to prefer full matches
    sorted_labels = sorted(labels, key=len, reverse=True)

    for label in sorted_labels:
        idx = text_lower.find(label)
        if idx == -1:
            continue

        # Label was found — extract remainder after it
        remainder = text[idx + len(label) :].strip()

        # Remove leading colon or separator
        if remainder.startswith(":") or remainder.startswith("."):
            remainder = remainder[1:].strip()

        # Return remainder if non-empty, otherwise None (don't try shorter labels)
        return remainder if remainder else None

    return None


def _is_label(text: str) -> bool:
    """Check if a text looks like a field label (contains known keywords)."""
    text_lower = text.lower()
    labels = ["ritningsnr", "ritn", "rev", "benämning", "benamning", "datum", "skala"]
    return any(label in text_lower for label in labels)
