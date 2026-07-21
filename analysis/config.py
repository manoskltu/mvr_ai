"""Configuration management for the analysis pipeline."""

import os


def get_analysis_config() -> dict:
    """Read analysis configuration from environment variables.

    Returns dict with keys:
        ocr_engine: str ("paddleocr" or "tesseract", default "tesseract")
        render_dpi: int (default 200)
        ocr_text_threshold: int (default 10)
        max_pages_per_pdf: int (default 50)
        vision_api_key: str | None
        vision_api_provider: str | None
        vision_model: str | None
    """
    return {
        "ocr_engine": os.environ.get("OCR_ENGINE", "tesseract"),
        "render_dpi": int(os.environ.get("RENDER_DPI", "200")),
        "ocr_text_threshold": int(os.environ.get("OCR_TEXT_THRESHOLD", "10")),
        "max_pages_per_pdf": int(os.environ.get("MAX_PAGES_PER_PDF", "50")),
        "vision_api_key": os.environ.get("VISION_API_KEY"),
        "vision_api_provider": os.environ.get("VISION_API_PROVIDER", "ollama"),
        "vision_model": os.environ.get("VISION_MODEL", "llama3.2-vision"),
        "vision_base_url": os.environ.get("VISION_BASE_URL", "http://localhost:11434"),
        "vision_timeout": int(os.environ.get("VISION_TIMEOUT", "60")),
        # Detection-specific configuration
        "detection_vector_threshold": int(os.environ.get("DETECTION_VECTOR_THRESHOLD", "10")),
        "detection_min_path_size": float(os.environ.get("DETECTION_MIN_PATH_SIZE", "0.01")),
        "detection_max_element_size": float(os.environ.get("DETECTION_MAX_ELEMENT_SIZE", "0.9")),
        "detection_group_proximity": float(os.environ.get("DETECTION_GROUP_PROXIMITY", "0.02")),
        "detection_label_proximity": float(os.environ.get("DETECTION_LABEL_PROXIMITY", "0.05")),
        "detection_max_results": int(os.environ.get("DETECTION_MAX_RESULTS", "100")),
        "detection_llm_threshold": int(os.environ.get("DETECTION_LLM_THRESHOLD", "1")),
        "detection_text_llm_model": os.environ.get("DETECTION_TEXT_LLM_MODEL", "llama3.1:latest"),
        "detection_duplicate_proximity": float(os.environ.get("DETECTION_DUPLICATE_PROXIMITY", "0.03")),
        "detection_use_vision": os.environ.get("DETECTION_USE_VISION", "true").lower() in ("true", "1", "yes"),
        "vision_min_box_size": float(os.environ.get("VISION_MIN_BOX_SIZE", "0.005")),
    }
