from __future__ import annotations

from typing import Any

STAGE = "appearance-boundary"
ADAPTER = "bodyrig.garment-policy"
REVISION = "external-outfit-v1"


class AppearanceBoundaryError(ValueError):
    pass


def provenance_stage() -> dict[str, str]:
    """Return the canonical portable-body appearance boundary provenance stage."""

    return {
        "stage": STAGE,
        "adapter": ADAPTER,
        "revision": REVISION,
    }


def validate_pipeline(pipeline: Any, *, required: bool = True) -> bool:
    """Validate that a provenance pipeline carries the canonical garment boundary.

    BodyRig owns the body identity and embodiment surface. Garments/outfits are
    external appearance assets. Source clothing may be observed during recovery
    or reconstruction as occlusion/context, but it is not a portable BodyRig
    capability and must not be treated as part of the body identity.
    """

    if not isinstance(pipeline, list):
        raise AppearanceBoundaryError("appearance boundary requires a provenance pipeline list")
    matches = [
        item
        for item in pipeline
        if isinstance(item, dict) and item.get("stage") == STAGE
    ]
    if not matches:
        if required:
            raise AppearanceBoundaryError("portable body provenance is missing the garment appearance boundary")
        return False
    if len(matches) != 1:
        raise AppearanceBoundaryError("portable body provenance must contain exactly one appearance boundary")
    if matches[0] != provenance_stage():
        raise AppearanceBoundaryError("portable body provenance contains a non-canonical appearance boundary")
    return True
