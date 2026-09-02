from __future__ import annotations

from typing import Any, Mapping


FORMAT = "bodyrig-face-secondary-fidelity"
VERSION = 1
STATUSES = {"complete", "partial", "missing", "not-evaluated"}
REQUIRED_SUBCOMPONENTS = (
    "eyebrow_appearance",
    "lip_boundary",
    "mouth_interior",
    "teeth",
    "eyelashes",
)


class FaceSecondaryFidelityError(ValueError):
    pass


def _status(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise FaceSecondaryFidelityError(f"{label} status is invalid")
    return value


def current_face_secondary_receipt() -> dict[str, Any]:
    components = {
        "eyebrow_appearance": "not-evaluated",
        "lip_boundary": "not-evaluated",
        "mouth_interior": "missing",
        "teeth": "missing",
        "eyelashes": "missing",
    }
    blockers = [name for name in REQUIRED_SUBCOMPONENTS if components[name] != "complete"]
    return {
        "format": FORMAT,
        "version": VERSION,
        "components": components,
        "faceSecondaryReady": False,
        "blockers": blockers,
        "semanticVertexMapAuthority": "unavailable",
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def validate_face_secondary_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "components",
        "faceSecondaryReady",
        "blockers",
        "semanticVertexMapAuthority",
        "sourceDerivedIdentitySynthesis",
        "generativeIdentitySynthesis",
        "humanReviewRequired",
        "productionReady",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise FaceSecondaryFidelityError("face-secondary receipt fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise FaceSecondaryFidelityError("face-secondary receipt format/version is invalid")

    raw_components = value.get("components")
    if not isinstance(raw_components, Mapping) or set(raw_components) != set(REQUIRED_SUBCOMPONENTS):
        raise FaceSecondaryFidelityError("face-secondary component set is invalid")
    components = {
        name: _status(raw_components[name], label=name)
        for name in REQUIRED_SUBCOMPONENTS
    }
    blockers = [name for name in REQUIRED_SUBCOMPONENTS if components[name] != "complete"]
    if value.get("blockers") != blockers:
        raise FaceSecondaryFidelityError("face-secondary blocker list is inconsistent")
    ready = len(blockers) == 0
    if value.get("faceSecondaryReady") is not ready:
        raise FaceSecondaryFidelityError("face-secondary readiness is inconsistent")

    semantic_authority = value.get("semanticVertexMapAuthority")
    if semantic_authority not in {"unavailable", "licensed-smplx-verified", "source-evidence-verified"}:
        raise FaceSecondaryFidelityError("face-secondary semantic vertex-map authority is invalid")
    if semantic_authority == "unavailable" and any(
        components[name] == "complete" for name in ("lip_boundary", "mouth_interior", "teeth", "eyelashes")
    ):
        raise FaceSecondaryFidelityError(
            "geometry-sensitive face-secondary components cannot be complete without semantic authority"
        )

    if value.get("sourceDerivedIdentitySynthesis") is not False:
        raise FaceSecondaryFidelityError("face-secondary receipt cannot claim hidden identity synthesis")
    if value.get("generativeIdentitySynthesis") is not False:
        raise FaceSecondaryFidelityError("generative face-secondary identity synthesis is forbidden")
    if value.get("humanReviewRequired") is not True:
        raise FaceSecondaryFidelityError("face-secondary human review must remain required")
    if value.get("productionReady") is not False:
        raise FaceSecondaryFidelityError("face-secondary receipt cannot independently authorize production")

    return {
        "format": FORMAT,
        "version": VERSION,
        "components": components,
        "faceSecondaryReady": ready,
        "blockers": blockers,
        "semanticVertexMapAuthority": semantic_authority,
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def with_face_secondary_status(
    value: Mapping[str, Any],
    *,
    component: str,
    status: str,
    semantic_vertex_map_authority: str | None = None,
) -> dict[str, Any]:
    receipt = validate_face_secondary_receipt(value)
    if component not in REQUIRED_SUBCOMPONENTS:
        raise FaceSecondaryFidelityError("unknown face-secondary component")
    components = dict(receipt["components"])
    components[component] = _status(status, label=component)
    authority = receipt["semanticVertexMapAuthority"]
    if semantic_vertex_map_authority is not None:
        authority = semantic_vertex_map_authority
    blockers = [name for name in REQUIRED_SUBCOMPONENTS if components[name] != "complete"]
    candidate = {
        **receipt,
        "components": components,
        "faceSecondaryReady": len(blockers) == 0,
        "blockers": blockers,
        "semanticVertexMapAuthority": authority,
    }
    return validate_face_secondary_receipt(candidate)
