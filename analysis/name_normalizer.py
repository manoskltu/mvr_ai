"""Detail type name normalization for consistent grouping.

Canonicalizes steel profile type strings so that minor variations
(whitespace, Unicode signs, casing) all map to the same group name.
"""

import re

# Known profile prefixes (uppercased canonical forms)
_KNOWN_PREFIXES = (
    "KKR", "HEA", "HEB", "HSQ", "IPE", "UNP",
    "RHS", "SHS", "CHS", "L-PROFIL", "PLÅT",
)

# Regex to match a known prefix at the start (case-insensitive)
_PREFIX_PATTERN = re.compile(
    r"^(KKR|HEA|HEB|HSQ|IPE|UNP|RHS|SHS|CHS|L-PROFIL|PLÅT)\s*",
    re.IGNORECASE,
)

# Unicode multiplication signs to normalize
_MULT_SIGNS = str.maketrans({
    "\u00d7": "x",  # ×
    "\u2715": "x",  # ✕
    "\u2716": "x",  # ✖
    "\u00b7": "x",  # · (middle dot, sometimes used)
})

# Diameter symbols to normalize
_DIAMETER_SIGNS = str.maketrans({
    "\u00f8": "\u00d8",  # ø → Ø
    "\u2300": "\u00d8",  # ⌀ → Ø
})


def normalize_detail_type(raw: str) -> str:
    """Normalize a detail type string to canonical form.

    Steps:
    1. Strip leading/trailing whitespace
    2. Replace Unicode multiplication signs (×, ✕, ✖) with ASCII 'x'
    3. Normalize diameter symbols (ø, ⌀) to 'Ø'
    4. Collapse multiple consecutive whitespace to single space
    5. Uppercase known profile prefixes (KKR, HEA, HSQ, HEB, IPE, UNP, etc.)
    6. Ensure exactly one space between prefix and dimension string

    This function is idempotent: normalize(normalize(s)) == normalize(s).

    Args:
        raw: Raw detail type string from text extraction or LLM output.

    Returns:
        Canonicalized detail type string.
    """
    if not raw:
        return ""

    # Step 1: Strip
    s = raw.strip()
    if not s:
        return ""

    # Step 2: Replace Unicode multiplication signs
    s = s.translate(_MULT_SIGNS)

    # Step 3: Normalize diameter symbols
    s = s.translate(_DIAMETER_SIGNS)

    # Step 4: Collapse multiple whitespace to single space
    s = re.sub(r"\s+", " ", s)

    # Step 5 & 6: Uppercase known prefix and ensure spacing
    match = _PREFIX_PATTERN.match(s)
    if match:
        prefix = match.group(1).upper()
        rest = s[match.end():].strip()
        if rest:
            s = f"{prefix} {rest}"
        else:
            s = prefix

    return s
