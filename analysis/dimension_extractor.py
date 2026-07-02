"""Extracts dimension annotations and quantities, links them to profiles."""

import math
import re
import logging
from dataclasses import dataclass
from typing import Any

from analysis.profile_matcher import ProfileMatch

logger = logging.getLogger(__name__)

# Patterns for dimension/quantity extraction
_LENGTH_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|m)\b")
_QUANTITY_ST_PATTERN = re.compile(r"(\d+)\s*st\b")
_QUANTITY_X_PATTERN = re.compile(r"x(\d+)\b")


@dataclass
class DimensionAnnotation:
    """A dimension or quantity annotation extracted from a text block."""

    value: float
    unit: str
    annotation_type: str  # "length" or "quantity"
    x: float
    y: float
    page_number: int


def extract_dimensions(
    text_blocks: list[Any], page_number: int
) -> list[DimensionAnnotation]:
    """Identify dimension and quantity annotations from text blocks.

    Accepts both TextBlock and OcrTextBlock (duck typing — both have text, x, y
    attributes).

    Args:
        text_blocks: List of text blocks with text, x, y attributes.
        page_number: Page number to associate with annotations.

    Returns:
        List of DimensionAnnotation objects found in the text blocks.
    """
    annotations: list[DimensionAnnotation] = []

    for block in text_blocks:
        text = block.text
        x = block.x
        y = block.y

        # Find length dimensions (mm, m)
        for m in _LENGTH_PATTERN.finditer(text):
            value = float(m.group(1))
            unit = m.group(2)
            annotations.append(
                DimensionAnnotation(
                    value=value,
                    unit=unit,
                    annotation_type="length",
                    x=x,
                    y=y,
                    page_number=page_number,
                )
            )

        # Find quantity annotations (N st)
        for m in _QUANTITY_ST_PATTERN.finditer(text):
            value = float(m.group(1))
            annotations.append(
                DimensionAnnotation(
                    value=value,
                    unit="st",
                    annotation_type="quantity",
                    x=x,
                    y=y,
                    page_number=page_number,
                )
            )

        # Find quantity annotations (xN)
        for m in _QUANTITY_X_PATTERN.finditer(text):
            value = float(m.group(1))
            annotations.append(
                DimensionAnnotation(
                    value=value,
                    unit="st",
                    annotation_type="quantity",
                    x=x,
                    y=y,
                    page_number=page_number,
                )
            )

    return annotations


def associate_dimensions(
    profiles: list[ProfileMatch],
    dimensions: list[DimensionAnnotation],
    proximity_threshold: float = 50.0,
) -> list[ProfileMatch]:
    """Link dimension annotations to nearby profiles based on spatial proximity.

    Uses Euclidean distance between profile position and dimension position.
    If distance < threshold, the dimension is added to the profile's dimensions dict.

    Args:
        profiles: List of ProfileMatch objects to associate dimensions with.
        dimensions: List of DimensionAnnotation objects to consider.
        proximity_threshold: Maximum distance for association (default 50.0).

    Returns:
        The profiles list (modified in-place) with dimensions added.
    """
    for dim in dimensions:
        for profile in profiles:
            px, py = profile.position
            distance = math.sqrt((px - dim.x) ** 2 + (py - dim.y) ** 2)

            if distance < proximity_threshold:
                if dim.annotation_type == "length":
                    profile.dimensions["length"] = dim.value
                elif dim.annotation_type == "quantity":
                    profile.dimensions["quantity"] = int(dim.value)

    return profiles
