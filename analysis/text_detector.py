"""Text-based detection of steel profiles from PDF text layers.

Two-tier approach:
1. Fast regex matching for well-known profile patterns (instant)
2. LLM text classification for remaining unmatched spans (handles any notation)

Uses PyMuPDF (fitz) to extract text spans from a PDF page.
"""

import json
import logging
import re

import fitz  # PyMuPDF
import requests

from analysis.detection_result import DetectionResult

logger = logging.getLogger(__name__)

# Compiled regex patterns for each profile type (fast-path)
PROFILE_PATTERNS: dict[str, re.Pattern] = {
    "KKR": re.compile(r"KKR\s*\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "VKR": re.compile(r"VKR\s*\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "HEA": re.compile(r"HEA\s*\d+", re.IGNORECASE),
    "HEB": re.compile(r"HEB\s*\d+", re.IGNORECASE),
    "HEM": re.compile(r"HEM\s*\d+", re.IGNORECASE),
    "HSQ": re.compile(r"HSQ\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "IPE": re.compile(r"IPE\s*\d+", re.IGNORECASE),
    "UNP": re.compile(r"UNP\s*\d+", re.IGNORECASE),
    "INP": re.compile(r"INP\s*\d+", re.IGNORECASE),
    "RHS": re.compile(r"RHS\s*\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "SHS": re.compile(r"SHS\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "CHS": re.compile(r"CHS\s*\d+\s*[x×]\s*\d+(?:\.\d+)?", re.IGNORECASE),
    "L-profil": re.compile(r"L\s*\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "T-profil": re.compile(r"T\s*\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", re.IGNORECASE),
    "plåt": re.compile(r"pl(?:åt|at)\s*\d+", re.IGNORECASE),
    "diameter": re.compile(r"[Øø⌀]\s*\d+", re.IGNORECASE),
}

# LLM prompt for classifying text spans
_CLASSIFICATION_PROMPT = """Du får en lista med textetiketter från en svensk konstruktionsritning.
Identifiera vilka som är strukturella material/profiler (stålbalkar, pelare, rör, plåt, etc.) och normalisera deras namn.

Textetiketter:
{text_list}

Svara ENBART med en JSON-lista av objekt för de etiketter som ÄR material/profiler:
[{{"original": "...", "normalized": "..."}}]

Inkludera INTE: rumsnummer (A01, 102), area (16,5 m²), sektioner (Sektion A-A), ritningsnummer (K-20-1-0100), beskrivningar (KORRIDOR, HISS).
Inkludera BARA: stålprofiler, dimensioner, rör, plåt, etc.
Om ingen text är ett material, svara med en tom lista: []"""


def _point_in_zone(cx: float, cy: float, zone: dict) -> bool:
    """Check if a point (cx, cy) falls within a zone dict {x, y, width, height}."""
    return (
        zone["x"] <= cx <= zone["x"] + zone["width"]
        and zone["y"] <= cy <= zone["y"] + zone["height"]
    )


def extract_text_detections(
    file_path: str,
    page_number: int,
    exclusion_zones: list[dict] | None = None,
    use_llm: bool = True,
    llm_model: str = "llama3.1:latest",
    llm_base_url: str = "http://localhost:11434",
    llm_timeout: int = 30,
) -> list[DetectionResult]:
    """Extract structural detail instances from PDF text layer.

    Two-tier approach:
    1. Regex fast-path for known patterns (always runs, instant)
    2. LLM classification for unmatched text (optional, handles any notation)

    Args:
        file_path: Path to the PDF file.
        page_number: 1-indexed page number.
        exclusion_zones: Optional list of {x, y, width, height} dicts (0.0-1.0 ratios).
        use_llm: Whether to use LLM for unmatched text classification.
        llm_model: Ollama model for text classification (text-only, not vision).
        llm_base_url: Ollama API base URL.
        llm_timeout: Timeout in seconds for LLM request.

    Returns:
        List of DetectionResult objects, one per matched text instance.
    """
    if exclusion_zones is None:
        exclusion_zones = []

    try:
        doc = fitz.open(file_path)
    except Exception:
        logger.warning("Could not open PDF file: %s", file_path)
        return []

    # Validate page number (1-indexed)
    if page_number < 1 or page_number > len(doc):
        doc.close()
        return []

    page = doc[page_number - 1]
    page_width = page.rect.width
    page_height = page.rect.height

    if page_width == 0 or page_height == 0:
        doc.close()
        return []

    # Extract text with full structure
    text_dict = page.get_text("dict")
    doc.close()

    # Collect all text spans with their positions
    spans_data: list[dict] = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text or len(text) < 2:
                    continue

                bbox = span.get("bbox")
                if not bbox:
                    continue

                x0, y0, x1, y1 = bbox
                rx = max(0.0, min(1.0, x0 / page_width))
                ry = max(0.0, min(1.0, y0 / page_height))
                rw = max(0.0, min(1.0 - rx, (x1 - x0) / page_width))
                rh = max(0.0, min(1.0 - ry, (y1 - y0) / page_height))

                cx = rx + rw / 2
                cy = ry + rh / 2

                if any(_point_in_zone(cx, cy, zone) for zone in exclusion_zones):
                    continue

                spans_data.append({
                    "text": text,
                    "rx": rx, "ry": ry, "rw": rw, "rh": rh,
                })

    if not spans_data:
        return []

    # --- Tier 1: Regex fast-path ---
    results: list[DetectionResult] = []
    regex_matched_indices: set[int] = set()

    for i, span in enumerate(spans_data):
        text = span["text"]
        for _name, pattern in PROFILE_PATTERNS.items():
            for match in pattern.finditer(text):
                results.append(DetectionResult(
                    x=span["rx"], y=span["ry"],
                    width=span["rw"], height=span["rh"],
                    label=match.group(0),
                    detection_method="text",
                ))
                regex_matched_indices.add(i)

    # --- Tier 2: LLM classification for unmatched spans ---
    if use_llm:
        unmatched_spans = [
            spans_data[i] for i in range(len(spans_data))
            if i not in regex_matched_indices
        ]

        if unmatched_spans:
            llm_results = _classify_with_llm(
                unmatched_spans, llm_model, llm_base_url, llm_timeout
            )
            results.extend(llm_results)

    return results


def _classify_with_llm(
    spans: list[dict],
    model: str,
    base_url: str,
    timeout: int,
) -> list[DetectionResult]:
    """Send unmatched text spans to LLM for material classification.

    Args:
        spans: List of span dicts with "text", "rx", "ry", "rw", "rh".
        model: Ollama model name (text-only model, e.g., llama3.1:latest).
        base_url: Ollama API base URL.
        timeout: Request timeout in seconds.

    Returns:
        List of DetectionResult for spans the LLM identified as materials.
    """
    # Build text list for the prompt (deduplicate but keep position mapping)
    unique_texts = list(set(s["text"] for s in spans))

    # Limit to prevent huge prompts (take first 200 unique texts)
    if len(unique_texts) > 200:
        unique_texts = unique_texts[:200]

    text_list_str = json.dumps(unique_texts, ensure_ascii=False)
    prompt = _CLASSIFICATION_PROMPT.format(text_list=text_list_str)

    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.debug("LLM unavailable for text classification")
        return []
    except requests.exceptions.Timeout:
        logger.debug("LLM text classification timed out after %ds", timeout)
        return []
    except requests.exceptions.RequestException as e:
        logger.debug("LLM text classification failed: %s", e)
        return []

    # Parse response
    try:
        result = response.json()
        content = result.get("message", {}).get("content", "")
    except (ValueError, KeyError):
        return []

    # Extract JSON from response
    classifications = _parse_classification_response(content)
    if not classifications:
        return []

    # Map classifications back to span positions
    # Build a lookup: original text → list of spans with that text
    text_to_spans: dict[str, list[dict]] = {}
    for span in spans:
        text_to_spans.setdefault(span["text"], []).append(span)

    results: list[DetectionResult] = []
    for item in classifications:
        original = item.get("original", "")
        normalized = item.get("normalized", original)

        if not original or not normalized:
            continue

        # Find all spans with this text
        matching_spans = text_to_spans.get(original, [])
        for span in matching_spans:
            results.append(DetectionResult(
                x=span["rx"], y=span["ry"],
                width=span["rw"], height=span["rh"],
                label=normalized,
                detection_method="llm",
            ))

    return results


def _parse_classification_response(content: str) -> list[dict]:
    """Parse the LLM's classification response into a list of dicts."""
    # Try to extract JSON array
    # Handle markdown code fences
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if fence_match:
        try:
            items = json.loads(fence_match.group(1).strip())
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

    # Try direct parse
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Regex fallback
    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        try:
            items = json.loads(json_match.group())
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

    return []
