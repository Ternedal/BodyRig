from __future__ import annotations

from typing import Any, Mapping

from .stash_source import _has_projection_ambiguous_geometry


def is_projection_ambiguous_geometry(width: int, height: int) -> bool:
    """Return True for geometry rejected by the package-owned Stash projection policy."""
    if isinstance(width, bool) or isinstance(height, bool):
        return False
    try:
        normalized_width = int(width)
        normalized_height = int(height)
    except (TypeError, ValueError):
        return False
    return _has_projection_ambiguous_geometry(
        width=normalized_width,
        height=normalized_height,
    )


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
