"""Hybrid detection dispatcher for structural element detection (V2).

Two-tier approach:
1. Extract text from PDF and run regex matching (fast, instant)
2. Always send the page image + text context to the vision LLM for full analysis
3. Merge and deduplicate results
"""

import logging

from analysis.detection_result import DetectionResult
from analysis.page_renderer import render_page
from analysis.text_detector import extract_text_detections
from analysis.vision_client import detect_elements_vision

logger = logging.getLogger(__name__)


def run_detection_v2(
    file_path: str,
    page_number: int,
    config: dict,
    exclusion_zones: list[dict] | None = None,
) -> tuple[list[DetectionResult], list[str]]:
    """Run two-tier detection for a PDF page.

    1. Run regex text detection (fast, always runs)
    2. Send page image to vision model for visual detection (always runs)
    3. Merge results, deduplicate by proximity

    Args:
        file_path: Path to the PDF file.
        page_number: 1-indexed page number.
        config: Configuration dict from get_analysis_config().
        exclusion_zones: Optional exclusion zone rectangles.

    Returns:
        Tuple of (merged_results, methods_used).
        methods_used is a list like ["text"] or ["text", "vision"].
    """
    max_results = config.get("detection_max_results", 100)
    duplicate_proximity = config.get("detection_duplicate_proximity", 0.03)
    use_vision = config.get("detection_use_vision", True)

    methods_used: list[str] = []

    # Tier 1: Regex text detection (always runs, instant)
    text_results = extract_text_detections(
        file_path, page_number, exclusion_zones,
        use_llm=False,  # Don't use text-only LLM, we'll use vision instead
    )
    methods_used.append("text")

    # Tier 2: Vision model detection (sends the actual image)
    vision_results: list[DetectionResult] = []
    if use_vision:
        try:
            image = render_page(file_path, page_number)
            if image is not None:
                model = config.get("vision_model", "llama3.2-vision")
                base_url = config.get("vision_base_url", "http://localhost:11434")
                timeout = config.get("vision_timeout", 60)
                min_box_size = config.get("vision_min_box_size", 0.005)

                vision_results = detect_elements_vision(
                    image=image,
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    min_box_size=min_box_size,
                )
                if vision_results:
                    methods_used.append("vision")
        except Exception as e:
            logger.warning("Vision detection failed: %s", e)

    # Merge and deduplicate
    merged = deduplicate_results(
        text_results + vision_results,
        proximity_threshold=duplicate_proximity,
    )

    # Truncate to max results
    if len(merged) > max_results:
        merged = merged[:max_results]

    return (merged, methods_used)


def deduplicate_results(
    results: list[DetectionResult],
    proximity_threshold: float = 0.03,
) -> list[DetectionResult]:
    """Remove duplicate detections based on center-point proximity.

    When two detections are within proximity_threshold distance,
    keep the one from the more reliable method (text > vision).
    """
    if not results:
        return []

    method_priority = {"text": 0, "llm": 1, "vision": 2}

    kept: list[DetectionResult] = []

    for result in results:
        cx = result.x + result.width / 2
        cy = result.y + result.height / 2

        is_duplicate = False
        for i, existing in enumerate(kept):
            ex = existing.x + existing.width / 2
            ey = existing.y + existing.height / 2

            dist = ((cx - ex) ** 2 + (cy - ey) ** 2) ** 0.5
            if dist <= proximity_threshold:
                result_priority = method_priority.get(result.detection_method, 3)
                existing_priority = method_priority.get(existing.detection_method, 3)
                if result_priority < existing_priority:
                    kept[i] = result
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(result)

    return kept
