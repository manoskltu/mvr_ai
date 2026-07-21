"""Unit tests for analysis/text_detector.py."""

import os
import tempfile

import fitz  # PyMuPDF
import pytest

from analysis.text_detector import (
    PROFILE_PATTERNS,
    _point_in_zone,
    extract_text_detections,
)


def _create_pdf_with_text(texts_and_positions: list[tuple[str, float, float]]) -> str:
    """Create a temporary PDF with text inserted at specified positions.

    Args:
        texts_and_positions: List of (text, x_point, y_point) tuples.

    Returns:
        Path to the created temporary PDF file.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in points

    for text, x, y in texts_and_positions:
        page.insert_text((x, y), text, fontsize=10)

    path = tempfile.mktemp(suffix=".pdf")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def simple_pdf():
    """Create a PDF with a single KKR profile text."""
    path = _create_pdf_with_text([("KKR 80x80x5", 100, 200)])
    yield path
    os.unlink(path)


@pytest.fixture
def multi_profile_pdf():
    """Create a PDF with multiple profiles on a single page."""
    path = _create_pdf_with_text([
        ("KKR 80x80x5", 100, 100),
        ("HEA 200", 100, 200),
        ("HEB 300", 100, 300),
        ("IPE 240", 100, 400),
    ])
    yield path
    os.unlink(path)


@pytest.fixture
def multi_match_span_pdf():
    """Create a PDF with a span containing multiple profile matches."""
    path = _create_pdf_with_text([("KKR 80x80x5 + HEA 200", 100, 200)])
    yield path
    os.unlink(path)


class TestExtractTextDetections:
    """Tests for extract_text_detections function."""

    def test_returns_empty_for_nonexistent_file(self):
        """Should return empty list for a file that doesn't exist."""
        results = extract_text_detections("/nonexistent/path.pdf", 1)
        assert results == []

    def test_returns_empty_for_out_of_range_page(self, simple_pdf):
        """Should return empty list when page number is out of range."""
        results = extract_text_detections(simple_pdf, 99)
        assert results == []

    def test_returns_empty_for_page_zero(self, simple_pdf):
        """Should return empty list for page 0 (pages are 1-indexed)."""
        results = extract_text_detections(simple_pdf, 0)
        assert results == []

    def test_returns_empty_for_negative_page(self, simple_pdf):
        """Should return empty list for negative page number."""
        results = extract_text_detections(simple_pdf, -1)
        assert results == []

    def test_detects_kkr_profile(self, simple_pdf):
        """Should detect a KKR profile on the page."""
        results = extract_text_detections(simple_pdf, 1)
        assert len(results) >= 1
        labels = [r.label for r in results]
        assert any("KKR" in label for label in labels)

    def test_detection_method_is_text(self, simple_pdf):
        """All detections should have detection_method='text'."""
        results = extract_text_detections(simple_pdf, 1)
        assert all(r.detection_method == "text" for r in results)

    def test_coordinates_are_ratios(self, simple_pdf):
        """All coordinates should be in [0.0, 1.0] range."""
        results = extract_text_detections(simple_pdf, 1)
        for r in results:
            assert 0.0 <= r.x <= 1.0
            assert 0.0 <= r.y <= 1.0
            assert 0.0 <= r.width <= 1.0
            assert 0.0 <= r.height <= 1.0
            assert r.x + r.width <= 1.0
            assert r.y + r.height <= 1.0

    def test_detects_multiple_profiles(self, multi_profile_pdf):
        """Should detect multiple different profile types."""
        results = extract_text_detections(multi_profile_pdf, 1)
        labels = [r.label for r in results]
        assert any("KKR" in l for l in labels)
        assert any("HEA" in l for l in labels)
        assert any("HEB" in l for l in labels)
        assert any("IPE" in l for l in labels)

    def test_multiple_matches_in_single_span(self, multi_match_span_pdf):
        """A span with two profile references should yield two results."""
        results = extract_text_detections(multi_match_span_pdf, 1)
        labels = [r.label for r in results]
        kkr_count = sum(1 for l in labels if "KKR" in l)
        hea_count = sum(1 for l in labels if "HEA" in l)
        assert kkr_count >= 1
        assert hea_count >= 1

    def test_exclusion_zone_filters_span(self, simple_pdf):
        """Spans within an exclusion zone should be filtered out."""
        # First get results without exclusion
        results_no_zone = extract_text_detections(simple_pdf, 1)
        assert len(results_no_zone) >= 1

        # Now exclude the entire page
        exclusion_zones = [{"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}]
        results_with_zone = extract_text_detections(simple_pdf, 1, exclusion_zones)
        assert len(results_with_zone) == 0

    def test_exclusion_zone_partial_does_not_filter(self, simple_pdf):
        """A span NOT in an exclusion zone should still be detected."""
        # The text is at approximately (100/595, 200/842) ~ (0.168, 0.237)
        # Place exclusion zone far away
        exclusion_zones = [{"x": 0.8, "y": 0.8, "width": 0.2, "height": 0.2}]
        results = extract_text_detections(simple_pdf, 1, exclusion_zones)
        assert len(results) >= 1

    def test_empty_page_returns_empty(self):
        """A page with no text should return empty list."""
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        path = tempfile.mktemp(suffix=".pdf")
        doc.save(path)
        doc.close()

        try:
            results = extract_text_detections(path, 1)
            assert results == []
        finally:
            os.unlink(path)

    def test_no_exclusion_zones_is_none(self, simple_pdf):
        """Passing None for exclusion_zones should work fine."""
        results = extract_text_detections(simple_pdf, 1, None)
        assert len(results) >= 1


class TestPointInZone:
    """Tests for the _point_in_zone helper."""

    def test_point_inside_zone(self):
        zone = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
        assert _point_in_zone(0.3, 0.3, zone) is True

    def test_point_outside_zone(self):
        zone = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
        assert _point_in_zone(0.8, 0.8, zone) is False

    def test_point_on_boundary(self):
        zone = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
        # Point on the edge should be included (<=)
        assert _point_in_zone(0.1, 0.1, zone) is True
        assert _point_in_zone(0.6, 0.6, zone) is True

    def test_point_just_outside(self):
        zone = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
        assert _point_in_zone(0.61, 0.3, zone) is False
        assert _point_in_zone(0.3, 0.61, zone) is False


class TestProfilePatterns:
    """Test that profile patterns match expected strings."""

    @pytest.mark.parametrize("text,expected_key", [
        ("KKR 80x80x5", "KKR"),
        ("KKR80×80×5", "KKR"),
        ("HEA 200", "HEA"),
        ("HEA200", "HEA"),
        ("HEB 300", "HEB"),
        ("HSQ 200x10", "HSQ"),
        ("IPE 240", "IPE"),
        ("UNP 120", "UNP"),
        ("RHS 120x60x5", "RHS"),
        ("SHS 80x5", "SHS"),
        ("CHS 60x3.2", "CHS"),
        ("L 80x80x8", "L-profil"),
        ("plåt 10", "plåt"),
        ("plat 12", "plåt"),
        ("Ø355", "diameter"),
        ("ø200", "diameter"),
        ("⌀150", "diameter"),
    ])
    def test_pattern_matches(self, text, expected_key):
        """Each profile text should match its expected pattern."""
        pattern = PROFILE_PATTERNS[expected_key]
        assert pattern.search(text) is not None
