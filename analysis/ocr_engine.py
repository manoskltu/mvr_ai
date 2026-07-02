"""OCR wrapper supporting Tesseract and PaddleOCR backends."""

import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class OcrTextBlock:
    """A text element recognized by OCR with position and confidence."""

    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float


def recognize(image: Image.Image, engine: str = "tesseract") -> list[OcrTextBlock]:
    """Perform OCR on a page image, returning text blocks with positions.

    Args:
        image: PIL Image of the rendered page.
        engine: OCR backend to use ("tesseract" or "paddleocr").

    Returns:
        List of recognized text blocks with bounding boxes.
        Empty list if OCR produces no results or the backend is unavailable.
    """
    if engine == "tesseract":
        return _recognize_tesseract(image)
    elif engine == "paddleocr":
        return _recognize_paddleocr(image)
    else:
        logger.warning("Unknown OCR engine '%s', falling back to tesseract", engine)
        return _recognize_tesseract(image)


def _recognize_tesseract(image: Image.Image) -> list[OcrTextBlock]:
    """Perform OCR using Tesseract via pytesseract."""
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not installed, OCR unavailable")
        return []

    try:
        # Use Swedish + English for better recognition of Swedish characters
        data = pytesseract.image_to_data(
            image, lang="swe+eng", output_type=pytesseract.Output.DICT
        )
    except Exception as e:
        logger.warning("Tesseract OCR failed: %s", e)
        return []

    blocks: list[OcrTextBlock] = []
    n_items = len(data.get("text", []))

    for i in range(n_items):
        text = data["text"][i].strip()
        if not text:
            continue

        confidence = float(data["conf"][i])
        # Skip very low confidence results (pytesseract uses -1 for invalid)
        if confidence < 0:
            continue

        x = float(data["left"][i])
        y = float(data["top"][i])
        width = float(data["width"][i])
        height = float(data["height"][i])

        blocks.append(
            OcrTextBlock(
                text=text,
                x=x,
                y=y,
                width=width,
                height=height,
                confidence=confidence,
            )
        )

    return blocks


def _recognize_paddleocr(image: Image.Image) -> list[OcrTextBlock]:
    """Perform OCR using PaddleOCR."""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        logger.warning("PaddleOCR not installed, OCR unavailable")
        return []

    try:
        import numpy as np

        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        # Convert PIL Image to numpy array for PaddleOCR
        img_array = np.array(image)
        result = ocr.ocr(img_array, cls=True)
    except Exception as e:
        logger.warning("PaddleOCR failed: %s", e)
        return []

    blocks: list[OcrTextBlock] = []

    if not result or not result[0]:
        return blocks

    for line in result[0]:
        # Each line: [bbox_points, (text, confidence)]
        bbox_points = line[0]
        text_info = line[1]

        text = text_info[0].strip()
        if not text:
            continue

        confidence = float(text_info[1])

        # bbox_points is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        # Convert to x, y, width, height
        x_coords = [p[0] for p in bbox_points]
        y_coords = [p[1] for p in bbox_points]

        x = min(x_coords)
        y = min(y_coords)
        width = max(x_coords) - x
        height = max(y_coords) - y

        blocks.append(
            OcrTextBlock(
                text=text,
                x=x,
                y=y,
                width=width,
                height=height,
                confidence=confidence,
            )
        )

    return blocks
