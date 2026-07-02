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
    }
