"""Hybrid detection dispatcher for structural element detection.

Decides whether to use vector path extraction or vision model fallback
based on the number of vector paths present on a PDF page.
"""

import logging

import fitz

from analysis.detection_result import DetectionResult
from analysis.page_renderer import render_page
from analysis.vector_detector import detect_elements_vector
from analysis.vision_client import detect_elements_vision

logger = logging.getLogger(__name__)


def run_detection(
    file_path: str,
    page_number: int,
    config: dict,
) -> tuple[list[DetectionResult], str]:
    """Run hybrid detection for a PDF page.

    Decides between vector detection and vision model fallback based on
    the number of vector paths on the page:
    - If path count >= threshold: use vector detection (fast, precise)
    - If path count < threshold: use vision model (for rasterized/scanned pages)

    Args:
        file_path: Path to the PDF file.
        page_number: 1-indexed page number to analyze.
        config: Configuration dict from get_analysis_config().

    Returns:
        Tuple of (results_list, method_used) where method_used is "vector" or "vision".
        Returns ([], method) if detection finds nothing or fails.
    """
    threshold = config.get("detection_vector_threshold", 10)
    max_results = config.get("detection_max_results", 50)

    # Count vector paths to decide which detector to use
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.warning("Failed to open PDF for detection: %s: %s", file_path, e)
        return ([], "vector")

    try:
        page_idx = page_number - 1
        if page_idx < 0 or page_idx >= len(doc):
            logger.warning(
                "Page %d out of range for %s (total: %d)",
                page_number, file_path, len(doc),
            )
            return ([], "vector")

        page = doc[page_idx]
        path_count = len(page.get_drawings())
    except Exception as e:
        logger.warning("Failed to count paths on page %d of %s: %s", page_number, file_path, e)
        return ([], "vector")
    finally:
        doc.close()

    # Dispatch based on path count threshold
    if path_count >= threshold:
        # Primary: vector detection
        results = detect_elements_vector(file_path, page_number, config)
        method = "vector"
    else:
        # Fallback: vision model detection
        image, _ = render_page(file_path, page_number)
        if image is None:
            logger.warning("Failed to render page %d of %s for vision detection", page_number, file_path)
            return ([], "vision")

        model = config.get("vision_model", "llama3.2-vision")
        base_url = config.get("vision_base_url", "http://localhost:11434")
        timeout = config.get("vision_timeout", 300)
        min_box_size = config.get("vision_min_box_size", 0.005)

        results = detect_elements_vision(
            image=image,
            model=model,
            base_url=base_url,
            timeout=timeout,
            min_box_size=min_box_size,
        )
        method = "vision"

    # Truncate to max_results
    if len(results) > max_results:
        results = results[:max_results]

    return (results, method)
