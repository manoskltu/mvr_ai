"""Vision AI client for analyzing construction drawing pages via Ollama (llama3.2-vision).

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
    model: str = "llama3.2-vision",
    base_url: str | None = None,
    timeout: int = 120,
) -> list[ProfileMatch]:
    """Send a page image to Ollama for vision analysis.

    Args:
        image: PIL Image of the rendered PDF page.
        model: Ollama model name (default: llama3.2-vision).
        base_url: Ollama API base URL (default: http://localhost:11434).
        timeout: Request timeout in seconds.

    Returns:
        List of ProfileMatch objects extracted by the vision model.
        Empty list if the model finds nothing or if the request fails.
    """
    url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    endpoint = f"{url}/api/chat"

    # Convert image to base64
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
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
