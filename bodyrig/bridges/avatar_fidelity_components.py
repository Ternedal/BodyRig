from __future__ import annotations

from typing import Any, Mapping


FORMAT = "bodyrig-avatar-fidelity-components"
VERSION = 1
STATUSES = {"complete", "partial", "missing", "not-evaluated"}
REQUIRED_COMPONENTS = (
    "body_anatomy",
    "skin_appearance",
    "hair",
    "eyes",
    "face_secondary",
)


class FidelityComponentError(ValueError):
    pass


def _status(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise FidelityComponentError(f"{label} status is invalid")
    return value


def current_pipeline_receipt() -> dict[str, Any]:
    components = {
        "body_anatomy": "not-evaluated",
        "skin_appearance": "partial",
        "hair": "missing",
        "eyes": "missing",
        "face_secondary": "missing",
    }
    blockers = [name for name in REQUIRED_COMPONENTS if components[name] != "complete"]
    return {
        "format": FORMAT,
        "version": VERSION,
        "components": components,
        "highFidelityReady": False,
        "blockers": blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def validate_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise FidelityComponentError("fidelity component receipt format is invalid")
    raw_components = value.get("components")
    if not isinstance(raw_components, Mapping) or set(raw_components) != set(REQUIRED_COMPONENTS):
        raise FidelityComponentError("fidelity component set is invalid")
    components = {
        name: _status(raw_components[name], label=name)
        for name in REQUIRED_COMPONENTS
    }
    expected_blockers = [name for name in REQUIRED_COMPONENTS if components[name] != "complete"]
    blockers = value.get("blockers")
    if blockers != expected_blockers:
        raise FidelityComponentError("fidelity blocker list is inconsistent")
    ready = len(expected_blockers) == 0
    if value.get("highFidelityReady") is not ready:
        raise FidelityComponentError("high-fidelity readiness is inconsistent")
    if value.get("productionReady") is not False:
        raise FidelityComponentError("component receipt cannot independently authorize production")
    if value.get("humanReviewRequired") is not True:
        raise FidelityComponentError("human fidelity review must remain required")
    return {
        "format": FORMAT,
        "version": VERSION,
        "components": components,
        "highFidelityReady": ready,
        "blockers": expected_blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def with_component_status(
    value: Mapping[str, Any],
    *,
    component: str,
    status: str,
) -> dict[str, Any]:
    receipt = validate_receipt(value)
    if component not in REQUIRED_COMPONENTS:
        raise FidelityComponentError("unknown fidelity component")
    next_status = _status(status, label=component)
    components = dict(receipt["components"])
    components[component] = next_status
    blockers = [name for name in REQUIRED_COMPONENTS if components[name] != "complete"]
    return {
        **receipt,
        "components": components,
        "highFidelityReady": len(blockers) == 0,
        "blockers": blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }
