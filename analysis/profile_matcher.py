"""Regex-based steel profile identification from text blocks."""

import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProfileMatch:
    """A matched steel profile with parsed dimensions."""

    profile_type: str
    raw_text: str
    dimensions: dict = field(default_factory=dict)
    page_number: int = 0
    position: tuple[float, float] = (0.0, 0.0)


# Compiled regex patterns for each profile type
PROFILE_PATTERNS: dict[str, re.Pattern] = {
    "KKR": re.compile(
        r"KKR\s*(\d+)\s*[x×]\s*(\d+)\s*[x×]\s*(\d+)", re.IGNORECASE
    ),
    "HSQ": re.compile(r"HSQ\s*(\d+)\s*[x×]\s*(\d+)", re.IGNORECASE),
    "HEA": re.compile(r"HEA\s*(\d+)", re.IGNORECASE),
    "UNP": re.compile(r"UNP\s*(\d+)", re.IGNORECASE),
    "L": re.compile(
        r"L\s*(\d+)\s*[x×]\s*(\d+)\s*[x×]\s*(\d+)", re.IGNORECASE
    ),
    "plåt": re.compile(r"pl[aå]t\s*(\d+)\s*(?:mm)?", re.IGNORECASE),
}


def match_profiles(
    text_blocks: list[Any], page_number: int
) -> list[ProfileMatch]:
    """Apply profile patterns to text blocks, returning all identified profiles.

    Accepts both TextBlock and OcrTextBlock (duck typing — both have text, x, y
    attributes).

    When a text block matches multiple patterns, the most specific match
    (longest matched substring) is selected.

    Args:
        text_blocks: List of text blocks with text, x, y attributes.
        page_number: Page number to associate with matches.

    Returns:
        List of ProfileMatch objects found in the text blocks.
    """
    matches: list[ProfileMatch] = []

    for block in text_blocks:
        text = block.text
        x = block.x
        y = block.y

        # Find all pattern matches for this text block
        block_matches: list[tuple[str, re.Match, int]] = []

        for profile_type, pattern in PROFILE_PATTERNS.items():
            for m in pattern.finditer(text):
                matched_length = len(m.group(0))
                block_matches.append((profile_type, m, matched_length))

        if not block_matches:
            continue

        # Group matches by their position in the text to handle overlapping
        # For overlapping matches at the same position, longest wins
        used_ranges: list[tuple[int, int]] = []

        # Sort by match length descending (longest first = most specific)
        block_matches.sort(key=lambda item: item[2], reverse=True)

        for profile_type, m, matched_length in block_matches:
            match_start = m.start()
            match_end = m.end()

            # Check if this range overlaps with any already-used range
            overlaps = False
            for used_start, used_end in used_ranges:
                if match_start < used_end and match_end > used_start:
                    overlaps = True
                    break

            if overlaps:
                continue

            used_ranges.append((match_start, match_end))

            dimensions = parse_profile_dimensions(profile_type, m)

            matches.append(
                ProfileMatch(
                    profile_type=profile_type,
                    raw_text=m.group(0),
                    dimensions=dimensions,
                    page_number=page_number,
                    position=(x, y),
                )
            )

    return matches


def parse_profile_dimensions(profile_type: str, match: re.Match) -> dict:
    """Extract dimensional parameters from a regex match based on profile type.

    Args:
        profile_type: The type of profile (KKR, HSQ, HEA, UNP, L, plåt).
        match: The regex match object.

    Returns:
        Dictionary with parsed dimensional parameters.
    """
    if profile_type == "KKR":
        return {
            "width": int(match.group(1)),
            "height": int(match.group(2)),
            "thickness": int(match.group(3)),
        }
    elif profile_type == "HSQ":
        return {
            "height": int(match.group(1)),
            "thickness": int(match.group(2)),
        }
    elif profile_type == "HEA":
        return {
            "size": int(match.group(1)),
        }
    elif profile_type == "UNP":
        return {
            "size": int(match.group(1)),
        }
    elif profile_type == "L":
        return {
            "side1": int(match.group(1)),
            "side2": int(match.group(2)),
            "thickness": int(match.group(3)),
        }
    elif profile_type == "plåt":
        return {
            "thickness": int(match.group(1)),
        }
    else:
        return {}
