"""Vision AI client for analyzing construction drawing pages via Ollama.

Sends rendered page images to a local Ollama instance and parses the response
for steel profile identification.
"""

import base64
import io
import json
import logging
import re

import requests
from PIL import Image

from analysis.detection_result import DetectionResult
from analysis.profile_matcher import ProfileMatch, PROFILE_PATTERNS, parse_profile_dimensions

logger = logging.getLogger(__name__)

# Default Ollama endpoint
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Prompt for steel profile extraction from construction drawings
ANALYSIS_PROMPT = """Du tittar på en svensk konstruktionsritning (construction drawing) för stålkonstruktioner.

Identifiera ALLA stålprofiler och material som visas i ritningen. Leta efter:
- KKR (fyrkantsprofil, t.ex. KKR 80x80x5)
- HSQ (varmvalsad stål, t.ex. HSQ 200x10)
- HEA (I-balk, t.ex. HEA 200)
- UNP (U-profil, t.ex. UNP 120)
- L-profil (vinkel, t.ex. L 50x50x5)
- Plåt (t.ex. plåt 10mm)

För varje hittat material, ange:
- Profiltyp (KKR, HSQ, HEA, UNP, L, plåt)
- Dimensioner (bredd, höjd, tjocklek i mm)
- Antal (om angivet, t.ex. "3 st")
- Längd (om angiven, t.ex. "L=2400")

Svara ENBART med en JSON-lista i följande format:
[
  {"profile_type": "KKR", "dimensions": "80x80x5", "quantity": 3, "length": 2400},
  {"profile_type": "HEA", "dimensions": "200", "quantity": null, "length": null}
]

Om inga stålprofiler hittas, svara med en tom lista: []
"""


def analyze_page_with_vision(
    image: Image.Image,
    model: str = "deepseek-ocr:latest",
    base_url: str | None = None,
    timeout: int = 300,
) -> list[ProfileMatch]:
    """Send a page image to Ollama for vision analysis.

    Args:
        image: PIL Image of the rendered PDF page.
        model: Ollama model name (default: deepseek-ocr:latest).
        base_url: Ollama API base URL (default: http://localhost:11434).
        timeout: Request timeout in seconds (default: 300 for local models).

    Returns:
        List of ProfileMatch objects extracted by the vision model.
        Empty list if the model finds nothing or if the request fails.
    """
    url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    endpoint = f"{url}/api/chat"

    # Resize image to reduce processing time (max 1024px on longest side)
    image = _resize_for_vision(image, max_size=1024)

    # Convert image to base64
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Build request payload
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": ANALYSIS_PROMPT,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot connect to Ollama at %s — is it running?", url)
        return []
    except requests.exceptions.Timeout:
        logger.warning("Ollama request timed out after %ds", timeout)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("Ollama request failed: %s", e)
        return []

    # Parse response
    try:
        result = response.json()
        content = result.get("message", {}).get("content", "")
    except (ValueError, KeyError):
        logger.warning("Invalid response from Ollama")
        return []

    return _parse_vision_response(content)


def _parse_vision_response(content: str) -> list[ProfileMatch]:
    """Parse the vision model's text response into ProfileMatch objects.

    Tries to extract a JSON array from the response, then falls back to
    regex matching on the raw text.
    """
    # Try to find JSON array in the response
    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        try:
            items = json.loads(json_match.group())
            return _items_to_profiles(items)
        except json.JSONDecodeError:
            pass

    # Fallback: use regex on the raw response text
    profiles = []
    for profile_type, pattern in PROFILE_PATTERNS.items():
        for m in pattern.finditer(content):
            dimensions = parse_profile_dimensions(profile_type, m)
            profiles.append(
                ProfileMatch(
                    profile_type=profile_type,
                    raw_text=m.group(0),
                    dimensions=dimensions,
                    page_number=0,
                    position=(0.0, 0.0),
                )
            )

    return profiles


def _items_to_profiles(items: list) -> list[ProfileMatch]:
    """Convert JSON items from vision response to ProfileMatch objects."""
    profiles = []

    for item in items:
        if not isinstance(item, dict):
            continue

        profile_type = item.get("profile_type", "").upper()
        if profile_type == "PLÅT" or profile_type == "PLAT":
            profile_type = "plåt"

        dims_str = str(item.get("dimensions", ""))
        quantity = item.get("quantity")
        length = item.get("length")

        # Parse dimensions string into dict
        dimensions = _parse_dims_string(profile_type, dims_str)

        if quantity is not None:
            dimensions["quantity"] = int(quantity)
        if length is not None:
            dimensions["length"] = float(length)

        if profile_type:
            profiles.append(
                ProfileMatch(
                    profile_type=profile_type,
                    raw_text=f"{profile_type} {dims_str}",
                    dimensions=dimensions,
                    page_number=0,
                    position=(0.0, 0.0),
                )
            )

    return profiles


def _parse_dims_string(profile_type: str, dims_str: str) -> dict:
    """Parse a dimensions string like '80x80x5' into a dict."""
    parts = re.findall(r"\d+(?:\.\d+)?", dims_str)
    parts = [float(p) for p in parts]

    if profile_type == "KKR" and len(parts) >= 3:
        return {"width": int(parts[0]), "height": int(parts[1]), "thickness": int(parts[2])}
    elif profile_type == "HSQ" and len(parts) >= 2:
        return {"height": int(parts[0]), "thickness": int(parts[1])}
    elif profile_type in ("HEA", "UNP") and len(parts) >= 1:
        return {"size": int(parts[0])}
    elif profile_type == "L" and len(parts) >= 3:
        return {"side1": int(parts[0]), "side2": int(parts[1]), "thickness": int(parts[2])}
    elif profile_type == "plåt" and len(parts) >= 1:
        return {"thickness": int(parts[0])}
    else:
        return {}


def _resize_for_vision(image: Image.Image, max_size: int = 1024) -> Image.Image:
    """Resize image so longest side is at most max_size pixels.

    This significantly speeds up local vision model inference without
    losing too much detail for text/profile recognition.
    """
    w, h = image.size
    if w <= max_size and h <= max_size:
        return image

    if w > h:
        new_w = max_size
        new_h = int(h * (max_size / w))
    else:
        new_h = max_size
        new_w = int(w * (max_size / h))

    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)


# Prompt for element detection with bounding boxes
DETECTION_PROMPT = """Du tittar på en svensk konstruktionsritning.

Identifiera alla strukturella element (balkar, pelare, väggar, stålprofiler) i ritningen.
För varje element, ange dess position som en bounding box.

Svara ENBART med en JSON-lista:
[
  {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.15, "label": "HEA 200"},
  {"x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1, "label": "beam"}
]

Koordinaterna ska vara relativa (0.0–1.0) där 0,0 är övre vänstra hörnet.
x = vänster kant, y = övre kant, width = bredd, height = höjd.
Om inga element hittas, svara med en tom lista: []
"""


def detect_elements_vision(
    image: Image.Image,
    model: str = "deepseek-ocr:latest",
    base_url: str | None = None,
    timeout: int = 300,
    min_box_size: float = 0.005,
) -> list[DetectionResult]:
    """Send page image to Ollama for bounding-box element detection.

    Different from analyze_page_with_vision() which extracts profile text.
    This function returns spatial bounding boxes for detected elements.

    Args:
        image: PIL Image of the rendered PDF page.
        model: Ollama model name (default: deepseek-ocr:latest).
        base_url: Ollama API base URL (default: http://localhost:11434).
        timeout: Request timeout in seconds (default: 300 for local models).
        min_box_size: Minimum width/height ratio to keep (default: 0.005).

    Returns:
        List of DetectionResult objects with bounding boxes.
        Empty list if the model finds nothing or if the request fails.
    """
    url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    endpoint = f"{url}/api/chat"

    # Resize image to reduce processing time (max 1024px on longest side)
    image = _resize_for_vision(image, max_size=1024)
    image_width, image_height = image.size

    # Convert image to base64
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Build request payload
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": DETECTION_PROMPT,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot connect to Ollama at %s — is it running?", url)
        return []
    except requests.exceptions.Timeout:
        logger.warning("Ollama request timed out after %ds", timeout)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("Ollama request failed: %s", e)
        return []

    # Parse response
    try:
        result = response.json()
        content = result.get("message", {}).get("content", "")
    except (ValueError, KeyError):
        logger.warning("Invalid response from Ollama")
        return []

    return _parse_detection_response(content, image_width, image_height, min_box_size)


def _parse_detection_response(
    content: str,
    image_width: int,
    image_height: int,
    min_box_size: float,
) -> list[DetectionResult]:
    """Parse the vision model's detection response into DetectionResult objects.

    Handles:
    - Direct JSON array in the response
    - JSON wrapped in markdown code fences (```json ... ```)
    - Regex-based JSON array extraction as fallback
    - Pixel values > 1.0 normalized to ratios
    - Coordinate clamping to [0.0, 1.0]
    - Min box size filtering

    Args:
        content: Raw text content from the vision model response.
        image_width: Width of the image sent to the model (for pixel normalization).
        image_height: Height of the image sent to the model (for pixel normalization).
        min_box_size: Minimum width/height ratio to keep a detection.

    Returns:
        List of DetectionResult objects. Empty list if nothing can be parsed.
    """
    items = None

    # Try 1: Strip markdown code fences and parse JSON
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if fence_match:
        try:
            items = json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try 2: Direct JSON array parse
    if items is None:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            pass

    # Try 3: Regex-based extraction of JSON array
    if items is None:
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            try:
                items = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    if not items or not isinstance(items, list):
        logger.warning("Could not parse detection response as JSON array")
        return []

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
            width = float(item.get("width", 0))
            height = float(item.get("height", 0))
        except (TypeError, ValueError):
            continue

        # Normalize pixel values to ratios if > 1.0
        if x > 1.0:
            x = x / image_width
        if y > 1.0:
            y = y / image_height
        if width > 1.0:
            width = width / image_width
        if height > 1.0:
            height = height / image_height

        # Clamp all values to [0.0, 1.0]
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        width = max(0.0, min(1.0, width))
        height = max(0.0, min(1.0, height))

        # Filter by minimum box size
        if width < min_box_size or height < min_box_size:
            continue

        label = str(item.get("label", "unknown")) or "unknown"

        results.append(
            DetectionResult(
                x=x,
                y=y,
                width=width,
                height=height,
                label=label,
                detection_method="vision",
            )
        )

    return results
