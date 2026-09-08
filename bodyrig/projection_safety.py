from __future__ import annotations

from typing import Any, Mapping

PROJECTION_AMBIGUOUS_MIN_WIDTH = 2880
PROJECTION_AMBIGUOUS_MIN_HEIGHT = 1440
PROJECTION_AMBIGUOUS_MIN_ASPECT = 1.95
PROJECTION_AMBIGUOUS_MAX_ASPECT = 2.05


def is_projection_ambiguous_geometry(width: int, height: int) -> bool:
    """Return True for high-resolution ~2:1 geometry unsupported by flat observation."""
    if isinstance(width, bool) or isinstance(height, bool):
        return False
    try:
        normalized_width = int(width)
        normalized_height = int(height)
    except (TypeError, ValueError):
        return False
    if normalized_width < PROJECTION_AMBIGUOUS_MIN_WIDTH or normalized_height < PROJECTION_AMBIGUOUS_MIN_HEIGHT:
        return False
    if normalized_height <= 0:
        return False
    aspect_ratio = normalized_width / normalized_height
    return PROJECTION_AMBIGUOUS_MIN_ASPECT <= aspect_ratio <= PROJECTION_AMBIGUOUS_MAX_ASPECT


def projection_ambiguous_manifest_entries(manifest: Mapping[str, Any]) -> list[int]:
    """Return zero-based selected-entry indexes whose declared geometry is projection-ambiguous."""
    selected = manifest.get("selected")
    if not isinstance(selected, list):
        return []
    result: list[int] = []
    for index, item in enumerate(selected):
        if not isinstance(item, Mapping):
            continue
        if is_projection_ambiguous_geometry(item.get("width"), item.get("height")):
            result.append(index)
    return result
