from __future__ import annotations

import math
from typing import Any

from . import skin_qa as legacy

CANONICAL_APPEARANCE = "canonical-smplx-closest-surface-bake-v1"
ANATOMY_APPEARANCE = "canonical-smplx-anatomy-normal-bake-v2"
_HEX = set("0123456789abcdef")
_ANATOMY_REGIONS = {"torso", "head", "left_arm", "right_arm", "left_leg", "right_leg"}


class GateAppearanceError(legacy.SkinQaError):
    pass


def _finite(value: Any, *, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    if minimum is not None and result < minimum:
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    if maximum is not None and result > maximum:
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    return result


def _positive_int(value: Any, *, label: str) -> int:
    number = _finite(value, label=label, minimum=0.0)
    integer = int(number)
    if integer < 1 or abs(number - integer) > 1e-9:
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    return integer


def _nonnegative_int(value: Any, *, label: str) -> int:
    number = _finite(value, label=label, minimum=0.0)
    integer = int(number)
    if abs(number - integer) > 1e-9:
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    return integer


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    digest = value.strip().lower()
    if len(digest) != 64 or any(ch not in _HEX for ch in digest):
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    return digest


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise GateAppearanceError(f"skin QA: donor appearance {label} evidence is invalid")
    return value.strip()


def _validate_canonical_fields(appearance: dict[str, Any]) -> None:
    for field in (
        "canonicalDonorAtlas",
        "sourceTextureBytesPreservedAsSeparateAuthority",
        "bakedBaseColorConsumedByRefinement",
        "sourceDerivedPbrApplied",
        "boundedBaseColorRefinementApplied",
    ):
        if appearance.get(field) is not True:
            raise GateAppearanceError(f"skin QA: donor appearance {field} authority is invalid")
    for field in ("activeBaseColorUsesExactSourceBytes", "generativeAppearanceSynthesis", "geometryModified"):
        if appearance.get(field) is not False:
            raise GateAppearanceError(f"skin QA: donor appearance {field} authority is invalid")

    _sha(appearance.get("canonicalUvTemplateSha256"), label="canonical UV SHA-256")
    _sha(appearance.get("sourceReconstructionTextureSha256"), label="source texture SHA-256")
    _sha(appearance.get("bakedBaseColorSha256"), label="baked base-color SHA-256")
    _sha(appearance.get("activeBaseColorSha256"), label="active base-color SHA-256")

    width = _positive_int(appearance.get("bakeWidth"), label="bake width")
    height = _positive_int(appearance.get("bakeHeight"), label="bake height")
    occupied = _positive_int(appearance.get("occupiedTexelCount"), label="occupied texel count")
    if occupied > width * height:
        raise GateAppearanceError("skin QA: donor appearance occupied texel evidence is invalid")
    occupied_ratio = _finite(appearance.get("occupiedTexelRatio"), label="occupied ratio", minimum=0.0, maximum=1.0)
    padded_ratio = _finite(appearance.get("paddedTexelRatio"), label="padded ratio", minimum=0.0, maximum=1.0)
    if padded_ratio + 1e-9 < occupied_ratio:
        raise GateAppearanceError("skin QA: donor appearance padded coverage evidence is invalid")
    gutter = _nonnegative_int(appearance.get("gutterPixels"), label="gutter pixels")
    if gutter > 64:
        raise GateAppearanceError("skin QA: donor appearance gutter evidence is invalid")

    surface_p95 = _finite(
        appearance.get("nearestSourceSurfaceDistanceP95"),
        label="nearest source surface p95",
        minimum=0.0,
    )
    surface_max = _finite(
        appearance.get("nearestSourceSurfaceDistanceMax"),
        label="nearest source surface max",
        minimum=0.0,
    )
    if surface_p95 > surface_max + 1e-9:
        raise GateAppearanceError("skin QA: donor appearance surface-distance evidence is invalid")

    _text(appearance.get("pbrRefinementMethod"), label="PBR refinement method")
    _text(appearance.get("baseColorRefinementMethod"), label="base-color refinement method")
    observed = _finite(
        appearance.get("baseColorMaxObservedChannelDelta"),
        label="base-color max channel delta",
        minimum=0.0,
    )
    cap = _finite(
        appearance.get("baseColorChannelDeltaCap"),
        label="base-color channel delta cap",
        minimum=0.0,
    )
    if observed > cap + (1.0 / 255.0) + 1e-6:
        raise GateAppearanceError("skin QA: donor appearance base-color refinement exceeded its declared cap")


def _validate_anatomy_fields(appearance: dict[str, Any]) -> None:
    _validate_canonical_fields(appearance)
    if appearance.get("anatomyRestrictedSourceSearch") is not True:
        raise GateAppearanceError("skin QA: donor anatomy-restricted source authority is invalid")
    if appearance.get("normalAwareFallback") is not True:
        raise GateAppearanceError("skin QA: donor normal-aware fallback authority is invalid")
    if appearance.get("sourceCandidateSearchGlobal") is not False:
        raise GateAppearanceError("skin QA: donor source-candidate search authority is invalid")
    if _positive_int(appearance.get("anatomyRegionCount"), label="anatomy region count") != 6:
        raise GateAppearanceError("skin QA: donor anatomy region count is invalid")
    restricted = _finite(
        appearance.get("anatomyRestrictedTexelRatio"),
        label="anatomy restricted texel ratio",
        minimum=0.0,
        maximum=1.0,
    )
    if abs(restricted - 1.0) > 1e-9:
        raise GateAppearanceError("skin QA: donor anatomy restriction does not cover every baked texel")

    _nonnegative_int(appearance.get("normalRetryTexelCount"), label="normal retry texel count")
    _finite(appearance.get("normalRetryTexelRatio"), label="normal retry texel ratio", minimum=0.0, maximum=1.0)
    _finite(appearance.get("normalAlignmentMean"), label="normal alignment mean", minimum=-1.0, maximum=1.0)
    _finite(appearance.get("normalAlignmentP05"), label="normal alignment p05", minimum=-1.0, maximum=1.0)
    _finite(
        appearance.get("normalLowAlignmentRatio"),
        label="normal low-alignment ratio",
        minimum=0.0,
        maximum=1.0,
    )
    if _finite(appearance.get("bodyScale"), label="body scale", minimum=0.0) <= 1e-6:
        raise GateAppearanceError("skin QA: donor anatomy body scale is invalid")

    ratios = appearance.get("anatomyTexelRatios")
    if not isinstance(ratios, dict) or set(ratios) != _ANATOMY_REGIONS:
        raise GateAppearanceError("skin QA: donor anatomy texel-region evidence is invalid")
    values = [
        _finite(ratios[name], label=f"{name} texel ratio", minimum=0.0, maximum=1.0)
        for name in sorted(_ANATOMY_REGIONS)
    ]
    if abs(sum(values) - 1.0) > 1e-4:
        raise GateAppearanceError("skin QA: donor anatomy texel-region coverage is invalid")


def _validate_transfer_authority(bodyrig: dict[str, Any]) -> tuple[str, float, float]:
    transfer = bodyrig.get("rigTransfer")
    if not isinstance(transfer, dict):
        raise GateAppearanceError("skin QA: rig transfer metadata is missing")
    method = transfer.get("method")
    if method != legacy.DONOR_RIG_TRANSFER:
        return legacy._validate_transfer_authority(bodyrig)

    nearest_p95 = transfer.get("nearestDistanceP95")
    nearest_max = transfer.get("nearestDistanceMax")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) != 0.0
        for value in (nearest_p95, nearest_max)
    ):
        raise GateAppearanceError("skin QA: direct donor LBS must not claim nearest-transfer distance")

    geometry = bodyrig.get("geometryAuthority")
    if geometry != {
        "method": legacy.DONOR_GEOMETRY_AUTHORITY,
        "sourceMeshGeometryUsed": False,
        "stableTopology": True,
    }:
        raise GateAppearanceError("skin QA: donor geometry authority metadata is invalid")

    appearance = bodyrig.get("appearanceTransfer")
    if not isinstance(appearance, dict):
        raise GateAppearanceError("skin QA: donor appearance transfer metadata is invalid")
    appearance_method = appearance.get("method")
    if appearance_method == legacy.DONOR_APPEARANCE_TRANSFER:
        return legacy._validate_transfer_authority(bodyrig)
    if appearance_method == CANONICAL_APPEARANCE:
        _validate_canonical_fields(appearance)
    elif appearance_method == ANATOMY_APPEARANCE:
        _validate_anatomy_fields(appearance)
    else:
        raise GateAppearanceError("skin QA: donor appearance transfer metadata is invalid")
    return str(method), 0.0, 0.0


def analyze_vrm_skin(*args: Any, **kwargs: Any) -> dict[str, Any]:
    original = legacy._validate_transfer_authority
    legacy._validate_transfer_authority = _validate_transfer_authority
    try:
        return legacy.analyze_vrm_skin(*args, **kwargs)
    finally:
        legacy._validate_transfer_authority = original


def analyze_package(*args: Any, **kwargs: Any) -> dict[str, Any]:
    original = legacy._validate_transfer_authority
    legacy._validate_transfer_authority = _validate_transfer_authority
    try:
        return legacy.analyze_package(*args, **kwargs)
    finally:
        legacy._validate_transfer_authority = original


def main(argv: list[str] | None = None) -> int:
    original_analyze_package = legacy.analyze_package
    legacy.analyze_package = analyze_package
    try:
        return legacy.main(argv)
    finally:
        legacy.analyze_package = original_analyze_package


if __name__ == "__main__":
    raise SystemExit(main())
