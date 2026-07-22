"""Orchestrates the full PDF analysis pipeline for a single attachment."""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from analysis import pdf_extractor, page_renderer, ocr_engine
from analysis import profile_matcher, dimension_extractor, layout_grouper
from analysis.layout_grouper import TitleBlockInfo

logger = logging.getLogger(__name__)


@dataclass
class MaterialItem:
    """A single identified material entry with profile type, dimensions, quantity, and source page."""

    profile_type: str
    dimensions: dict = field(default_factory=dict)
    quantity: int | None = None
    unit: str | None = None
    length: float | None = None
    source_page: int = 0
    raw_text: str = ""


@dataclass
class PageMetadata:
    """Per-page processing metadata."""

    page_number: int = 0
    title_block: TitleBlockInfo | None = None
    text_block_count: int = 0
    used_ocr: bool = False


@dataclass
class AnalysisResult:
    """Complete analysis result for a single PDF attachment."""

    attachment_id: int = 0
    status: str = "pending"
    timestamp: str = ""
    materials: list[MaterialItem] = field(default_factory=list)
    pages: list[PageMetadata] = field(default_factory=list)
    error_message: str | None = None
    truncated: bool = False
    vision_ai_used: bool = False


def run_analysis(attachment_id: int, file_path: str, config: dict) -> AnalysisResult:
    """Run the full analysis pipeline for a single PDF attachment.

    Steps:
    1. Extract text and geometry (pdf_extractor)
    2. Render and OCR sparse-text pages (page_renderer + ocr_engine)
    3. Match steel profiles (profile_matcher)
    4. Extract dimensions and quantities (dimension_extractor)
    5. Identify title blocks and layout (layout_grouper)
    6. Build and return AnalysisResult
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Step 1: Extract text and geometry
    max_pages = config.get("max_pages_per_pdf", 50)
    ocr_threshold = config.get("ocr_text_threshold", 10)
    extraction = pdf_extractor.extract(file_path, max_pages, ocr_threshold)

    if extraction.error:
        return AnalysisResult(
            attachment_id=attachment_id,
            status="failed",
            timestamp=timestamp,
            error_message=extraction.error,
            truncated=False,
            vision_ai_used=False,
        )

    vision_ai_used = False
    materials: list[MaterialItem] = []
    pages_metadata: list[PageMetadata] = []
    render_dpi = config.get("render_dpi", 200)
    ocr_engine_name = config.get("ocr_engine", "tesseract")

    for page_ext in extraction.pages:
        page_num = page_ext.page_number
        used_ocr = False
        all_text_blocks = list(page_ext.text_blocks)

        # Step 2: If page needs OCR, render and recognize
        if page_ext.needs_ocr:
            image = page_renderer.render_page(file_path, page_num, render_dpi)
            if image is not None:
                ocr_blocks = ocr_engine.recognize(image, ocr_engine_name)
                # Merge OCR blocks with existing text blocks for processing
                all_text_blocks.extend(ocr_blocks)
                used_ocr = True

        # Step 3: Match steel profiles
        profiles = profile_matcher.match_profiles(all_text_blocks, page_num)

        # Step 3b: Vision AI fallback for pages with no profile matches
        vision_used_on_page = False
        if not profiles and config.get("vision_api_key") or config.get("vision_api_provider") == "ollama":
            # Render page image if not already rendered
            if page_ext.needs_ocr and 'image' in dir():
                page_image = image
            else:
                page_image = page_renderer.render_page(file_path, page_num, render_dpi)

            if page_image is not None:
                try:
                    from analysis.vision_client import analyze_page_with_vision
                    vision_model = config.get("vision_model", "deepseek-ocr:latest")
                    vision_base_url = config.get("vision_base_url")
                    vision_timeout = config.get("vision_timeout", 300)
                    vision_profiles = analyze_page_with_vision(
                        page_image,
                        model=vision_model,
                        base_url=vision_base_url,
                        timeout=vision_timeout,
                    )
                    # Set page number on vision results
                    for vp in vision_profiles:
                        vp.page_number = page_num
                    profiles.extend(vision_profiles)
                    vision_used_on_page = True
                except Exception as e:
                    logger.warning("Vision AI fallback failed for page %d: %s", page_num, e)

        # Step 4: Extract dimensions and associate
        dimensions = dimension_extractor.extract_dimensions(all_text_blocks, page_num)
        dimension_extractor.associate_dimensions(profiles, dimensions)

        # Step 5: Find title block
        # Use page dimensions (A4 landscape as default: 842x595 pts)
        page_width = 842.0
        page_height = 595.0
        title_block = layout_grouper.find_title_block(
            all_text_blocks, page_width, page_height, page_num
        )

        # Build MaterialItems from matched profiles
        for prof in profiles:
            quantity = prof.dimensions.pop("quantity", None)
            length = prof.dimensions.pop("length", None)

            unit = None
            if quantity is not None:
                unit = "st"

            materials.append(
                MaterialItem(
                    profile_type=prof.profile_type,
                    dimensions=prof.dimensions,
                    quantity=int(quantity) if quantity is not None else None,
                    unit=unit,
                    length=float(length) if length is not None else None,
                    source_page=page_num,
                    raw_text=prof.raw_text,
                )
            )

        pages_metadata.append(
            PageMetadata(
                page_number=page_num,
                title_block=title_block,
                text_block_count=len(all_text_blocks),
                used_ocr=used_ocr,
            )
        )

        if vision_used_on_page:
            vision_ai_used = True

    return AnalysisResult(
        attachment_id=attachment_id,
        status="completed",
        timestamp=timestamp,
        materials=materials,
        pages=pages_metadata,
        error_message=None,
        truncated=extraction.truncated,
        vision_ai_used=vision_ai_used,
    )


def serialize_result(result: AnalysisResult) -> str:
    """Serialize an AnalysisResult to a JSON string for database storage."""

    def _convert(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    data = asdict(result)
    return json.dumps(data, ensure_ascii=False, default=_convert)


def deserialize_result(json_str: str) -> AnalysisResult:
    """Deserialize a JSON string back to an AnalysisResult.

    Handles missing fields gracefully by applying defaults.
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return AnalysisResult(status="failed", error_message="Invalid JSON data")

    if not isinstance(data, dict):
        return AnalysisResult(status="failed", error_message="Invalid JSON structure")

    # Parse materials
    materials_data = data.get("materials", [])
    materials = []
    for m in materials_data:
        if isinstance(m, dict):
            materials.append(
                MaterialItem(
                    profile_type=m.get("profile_type", ""),
                    dimensions=m.get("dimensions", {}),
                    quantity=m.get("quantity"),
                    unit=m.get("unit"),
                    length=m.get("length"),
                    source_page=m.get("source_page", 0),
                    raw_text=m.get("raw_text", ""),
                )
            )

    # Parse pages
    pages_data = data.get("pages", [])
    pages = []
    for p in pages_data:
        if isinstance(p, dict):
            tb_data = p.get("title_block")
            title_block = None
            if tb_data and isinstance(tb_data, dict):
                title_block = TitleBlockInfo(
                    drawing_number=tb_data.get("drawing_number"),
                    revision=tb_data.get("revision"),
                    sheet_title=tb_data.get("sheet_title"),
                    page_number=tb_data.get("page_number", 0),
                )
            pages.append(
                PageMetadata(
                    page_number=p.get("page_number", 0),
                    title_block=title_block,
                    text_block_count=p.get("text_block_count", 0),
                    used_ocr=p.get("used_ocr", False),
                )
            )

    return AnalysisResult(
        attachment_id=data.get("attachment_id", 0),
        status=data.get("status", "pending"),
        timestamp=data.get("timestamp", ""),
        materials=materials,
        pages=pages,
        error_message=data.get("error_message"),
        truncated=data.get("truncated", False),
        vision_ai_used=data.get("vision_ai_used", False),
    )
