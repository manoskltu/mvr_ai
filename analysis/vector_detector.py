"""Vector-based element detection from PDF drawing paths.

Extracts structural elements from CAD-generated PDFs by analyzing vector
paths extracted via PyMuPDF's page.get_drawings() API. Groups paths by
stroke/fill color — each color layer represents a logical system (e.g.,
fire boundaries, sprinkler lines, structural elements).
"""

import logging
import re
from collections import defaultdict

import fitz

from analysis.detection_result import DetectionResult

logger = logging.getLogger(__name__)

# Swedish steel profile pattern: prefix followed by dimensions
_PROFILE_PATTERN = re.compile(
    r"\b(KKR|HEA|HSQ|UNP|IPE|L)\s*\d+", re.IGNORECASE
)


def detect_elements_vector(
    file_path: str,
    page_number: int,
    config: dict,
) -> list[DetectionResult]:
    """Extract structural elements from PDF vector paths, grouped by color.

    Each distinct stroke/fill color in the PDF is treated as a separate
    layer/system. Paths of the same color are grouped together and their
    individual bounding boxes become detection results. This works well for
    CAD-generated construction drawings where color distinguishes systems
    (fire zones, sprinkler, structural steel, etc.).

    Args:
        file_path: Path to the PDF file.
        page_number: 1-indexed page number to analyze.
        config: Configuration dict with detection thresholds.

    Returns:
        List of DetectionResult objects for detected elements.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.warning("Failed to open PDF for vector detection %s: %s", file_path, e)
        return []

    try:
        page_idx = page_number - 1
        if page_idx < 0 or page_idx >= len(doc):
            logger.warning(
                "Page number %d out of range for %s (total: %d)",
                page_number, file_path, len(doc),
            )
            return []

        page = doc[page_idx]
        page_width = page.rect.width
        page_height = page.rect.height

        if page_width <= 0 or page_height <= 0:
            logger.warning("Page %d has zero dimensions in %s", page_number, file_path)
            return []

        min_path_size = config.get("detection_min_path_size", 0.005)
        max_element_size = config.get("detection_max_element_size", 0.9)
        group_proximity = config.get("detection_group_proximity", 0.015)
        label_proximity = config.get("detection_label_proximity", 0.05)

        # Step 1: Extract all vector paths and group by color
        drawings = page.get_drawings()
        if not drawings:
            return []

        # Group paths by their stroke color (primary) or fill color
        color_groups: dict[tuple, list[tuple[float, float, float, float]]] = defaultdict(list)

        for path in drawings:
            rect = path.get("rect")
            if rect is None:
                continue

            # Determine the path's color identity
            color_key = _get_color_key(path)
            if color_key is None:
                continue  # Skip paths with no color (invisible)

            # Convert from PDF points to 0-1 ratios
            x = rect.x0 / page_width
            y = rect.y0 / page_height
            w = (rect.x1 - rect.x0) / page_width
            h = (rect.y1 - rect.y0) / page_height

            # Filter tiny paths (noise: dots, very short line segments)
            if w < min_path_size and h < min_path_size:
                continue

            color_groups[color_key].append((x, y, w, h))

        if not color_groups:
            return []

        # Step 2: For each color group, cluster nearby same-color paths
        # Skip black/very dark colors (usually background lines, text, grids)
        # and very light colors (near-white backgrounds)
        results: list[DetectionResult] = []
        text_blocks = _extract_text_blocks(page)

        for color_key, rects in color_groups.items():
            # Skip black/near-black (likely floor plan base lines)
            if _is_near_black(color_key) or _is_near_white(color_key):
                continue

            # Skip color groups with too few paths (likely noise)
            if len(rects) < 3:
                continue

            # Group nearby same-color paths by proximity
            groups = _group_paths_by_proximity(rects, group_proximity)

            for group_indices in groups:
                # Skip very small clusters (noise)
                if len(group_indices) < 3:
                    continue

                bbox = _compute_union_bbox(rects, group_indices)
                x, y, w, h = bbox

                # Skip if covering entire page
                if w > max_element_size and h > max_element_size:
                    continue

                # Skip very tiny grouped results
                if w < min_path_size and h < min_path_size:
                    continue

                # Try to find a label near this group
                label = _find_label_for_bbox(bbox, text_blocks, label_proximity)
                if label == "unknown":
                    label = _color_to_label(color_key)

                results.append(DetectionResult(
                    x=x, y=y, width=w, height=h,
                    label=label,
                    detection_method="vector",
                ))

        return results

    except Exception as e:
        logger.warning(
            "Error during vector detection on page %d of %s: %s",
            page_number, file_path, e,
        )
        return []
    finally:
        doc.close()


def _get_color_key(path: dict) -> tuple | None:
    """Extract a color identity tuple from a path dict.

    Prefers stroke color, falls back to fill color.
    Returns None if both are None (invisible path).
    Returns a tuple of (r, g, b) rounded to avoid floating-point duplicates.
    """
    color = path.get("color")  # stroke color
    if color is None:
        color = path.get("fill")  # fill color

    if color is None:
        return None

    # Color can be a tuple of floats (0-1 range) or a single float (grayscale)
    if isinstance(color, (int, float)):
        c = round(float(color), 2)
        return (c, c, c)

    if isinstance(color, (list, tuple)) and len(color) >= 3:
        return (round(color[0], 2), round(color[1], 2), round(color[2], 2))

    return None


def _is_near_black(color_key: tuple) -> bool:
    """Check if a color is near-black (all channels < 0.15)."""
    return all(c < 0.15 for c in color_key)


def _is_near_white(color_key: tuple) -> bool:
    """Check if a color is near-white (all channels > 0.85)."""
    return all(c > 0.85 for c in color_key)


def _color_to_label(color_key: tuple) -> str:
    """Convert a color tuple to a human-readable label."""
    r, g, b = color_key
    # Convert to hex for display
    hex_color = "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )
    return f"Färg {hex_color}"


def _group_paths_by_proximity(
    path_rects: list[tuple[float, float, float, float]],
    proximity: float,
) -> list[list[int]]:
    """Group path indices whose bounding boxes overlap or are within proximity.

    Uses union-find for efficient grouping.

    Args:
        path_rects: List of (x, y, width, height) tuples in ratio coordinates.
        proximity: Maximum distance between rect edges to be grouped together.

    Returns:
        List of groups, where each group is a list of indices into path_rects.
    """
    n = len(path_rects)
    if n == 0:
        return []

    # Union-find
    parent = list(range(n))
    rank = [0] * n

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        if rank[ri] < rank[rj]:
            ri, rj = rj, ri
        parent[rj] = ri
        if rank[ri] == rank[rj]:
            rank[ri] += 1

    # For large path sets, use spatial binning to avoid O(n²)
    if n > 500:
        # Bin-based approach for performance
        _group_with_bins(path_rects, proximity, union)
    else:
        for i in range(n):
            for j in range(i + 1, n):
                if _rect_distance(path_rects[i], path_rects[j]) <= proximity:
                    union(i, j)

    # Collect groups
    groups_map: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        if root not in groups_map:
            groups_map[root] = []
        groups_map[root].append(i)

    return list(groups_map.values())


def _group_with_bins(
    path_rects: list[tuple[float, float, float, float]],
    proximity: float,
    union_fn,
) -> None:
    """Spatial binning approach for grouping large path sets efficiently."""
    bin_size = max(proximity * 2, 0.05)
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)

    for i, (x, y, w, h) in enumerate(path_rects):
        # Assign to bins based on center
        cx = x + w / 2
        cy = y + h / 2
        bx = int(cx / bin_size)
        by = int(cy / bin_size)
        bins[(bx, by)].append(i)

    # Check within same bin and neighboring bins
    for (bx, by), indices in bins.items():
        # Check all pairs within this bin
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i, j = indices[a], indices[b]
                if _rect_distance(path_rects[i], path_rects[j]) <= proximity:
                    union_fn(i, j)

        # Check neighboring bins
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                neighbor = (bx + dx, by + dy)
                if neighbor not in bins:
                    continue
                for i in indices:
                    for j in bins[neighbor]:
                        if _rect_distance(path_rects[i], path_rects[j]) <= proximity:
                            union_fn(i, j)


def _rect_distance(
    rect1: tuple[float, float, float, float],
    rect2: tuple[float, float, float, float],
) -> float:
    """Compute minimum edge-to-edge distance between two rectangles."""
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2

    dx = max(0.0, max(x1 - (x2 + w2), x2 - (x1 + w1)))
    dy = max(0.0, max(y1 - (y2 + h2), y2 - (y1 + h1)))

    return (dx * dx + dy * dy) ** 0.5


def _compute_union_bbox(
    rects: list[tuple[float, float, float, float]],
    indices: list[int],
) -> tuple[float, float, float, float]:
    """Compute the union bounding box for a subset of rectangles."""
    min_x = float("inf")
    min_y = float("inf")
    max_x2 = float("-inf")
    max_y2 = float("-inf")

    for idx in indices:
        x, y, w, h = rects[idx]
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x2 = max(max_x2, x + w)
        max_y2 = max(max_y2, y + h)

    return (min_x, min_y, max_x2 - min_x, max_y2 - min_y)


def _extract_text_blocks(page) -> list[dict]:
    """Extract text blocks from a PDF page with center positions as 0-1 ratios."""
    page_width = page.rect.width
    page_height = page.rect.height

    if page_width <= 0 or page_height <= 0:
        return []

    text_blocks: list[dict] = []

    try:
        text_dict = page.get_text("dict")
    except Exception as e:
        logger.warning("Failed to extract text from page: %s", e)
        return []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                bbox = span.get("bbox")
                if bbox is None:
                    continue

                x0, y0, x1, y1 = bbox
                cx = ((x0 + x1) / 2.0) / page_width
                cy = ((y0 + y1) / 2.0) / page_height

                text_blocks.append({"text": text, "cx": cx, "cy": cy})

    return text_blocks


def _find_label_for_bbox(
    bbox: tuple[float, float, float, float],
    text_blocks: list[dict],
    label_proximity: float,
) -> str:
    """Find the closest text label within proximity of a bounding box."""
    best_label = "unknown"
    best_distance = float("inf")

    for tb in text_blocks:
        dist = _point_to_rect_distance(tb["cx"], tb["cy"], bbox)
        if dist <= label_proximity and dist < best_distance:
            best_distance = dist
            best_label = tb["text"]

    return best_label


def _point_to_rect_distance(
    px: float, py: float,
    rect: tuple[float, float, float, float],
) -> float:
    """Compute distance from a point to the nearest edge of a rectangle."""
    rx, ry, rw, rh = rect
    nearest_x = max(rx, min(px, rx + rw))
    nearest_y = max(ry, min(py, ry + rh))
    dx = px - nearest_x
    dy = py - nearest_y
    return (dx * dx + dy * dy) ** 0.5
