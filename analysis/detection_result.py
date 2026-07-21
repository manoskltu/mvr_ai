"""DetectionResult data class for the hybrid auto-detection system.

Represents a single detected structural element on a PDF page as a bounding box
with label and detection method metadata.
"""

from dataclasses import dataclass


@dataclass
class DetectionResult:
    """A single detected element on a PDF page.

    All coordinates are expressed as ratios (0.0–1.0) relative to the page dimensions.
    x, y represent the top-left corner of the bounding box.
    """

    x: float  # 0.0–1.0 ratio (left edge)
    y: float  # 0.0–1.0 ratio (top edge)
    width: float  # 0.0–1.0 ratio
    height: float  # 0.0–1.0 ratio
    label: str  # e.g. "HEA 200", "beam", "unknown"
    detection_method: str  # "vector", "vision", or "text"
    page_number: int = 0  # 1-indexed page where detected (0 = unset)

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "label": self.label,
            "detection_method": self.detection_method,
            "page_number": self.page_number,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DetectionResult":
        """Deserialize from a dictionary."""
        return cls(
            x=d["x"],
            y=d["y"],
            width=d["width"],
            height=d["height"],
            label=d.get("label", "unknown"),
            detection_method=d.get("detection_method", "unknown"),
            page_number=d.get("page_number", 0),
        )
