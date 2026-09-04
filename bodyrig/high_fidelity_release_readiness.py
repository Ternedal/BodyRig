from __future__ import annotations

from pathlib import Path
from typing import Any

from .high_fidelity_continuation_status import (
    HighFidelityContinuationStatusError,
    inspect_continuation,
)
from .high_fidelity_human_review import (
    HighFidelityHumanReviewError,
    review_status as high_fidelity_human_review_status,
)

FORMAT = "bodyrig-high-fidelity-release-readiness"
VERSION = 1
FINAL_REVIEW_GATE = "high_fidelity_human_review"


class HighFidelityReleaseReadinessError(RuntimeError):
    pass


def _final_review_gate(state: str, *, reason: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": FINAL_REVIEW_GATE,
        "label": "Package-bound high-fidelity human review",
        "state": state,
        "passed": state == "pass",
        "reason": reason,
        "evidence": evidence or {},
    }


def _review_command(package_path: Path) -> str:
    quoted = '"' + str(package_path).replace('"', '`"') + '"'
    return (
        ".\\record-high-fidelity-human-review.ps1 "
        f"-PackagePath {quoted} -ConfirmQualityChecklist -QualityNote <QUALITY_NOTE>"
    )


def inspect_release_readiness(preview_job_id: str) -> dict[str, Any]:
    try:
        base = inspect_continuation(preview_job_id)
    except HighFidelityContinuationStatusError as exc:
        raise HighFidelityReleaseReadinessError(str(exc)) from exc

    result = dict(base)
    result["format"] = FORMAT
    result["version"] = VERSION
    result["component_package_complete"] = bool(base.get("high_fidelity_complete"))
    result["high_fidelity_human_review_complete"] = False
    result["software_ready_for_physical_acceptance"] = False
    result["production_ready"] = False
    result["production_activation"] = False

    if not result["component_package_complete"]:
        return result

    package_value = str(base.get("current_package_path") or "").strip()
    if not package_value:
        result["state"] = "blocked"
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate("invalid", reason="component-complete continuation has no exact promoted package path"),
        ]
        result["next_gate"] = None
        return result
    package = Path(package_value).expanduser().resolve()
    if not package.is_file():
        result["state"] = "blocked"
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate("invalid", reason=f"component-complete promoted package is missing: {package}"),
        ]
        result["next_gate"] = None
        return result

    try:
        review = high_fidelity_human_review_status(package)
    except HighFidelityHumanReviewError as exc:
        result["state"] = "blocked"
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate("invalid", reason=str(exc)),
        ]
        result["next_gate"] = None
        return result

    review_state = str(review.get("state") or "blocked")
    if review_state == "pass" and review.get("passed") is True:
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate(
                "pass",
                evidence={
                    "reviewed_utc": review.get("reviewed_utc"),
                    "policy_revision": review.get("policy_revision"),
                },
            ),
        ]
        result["high_fidelity_human_review_complete"] = True
        result["software_ready_for_physical_acceptance"] = True
        result["state"] = "software-ready-for-physical-acceptance"
        result["next_gate"] = {
            "gate": "physical_windows_acceptance",
            "command": None,
            "operator_input_required": True,
            "reason": (
                "High-fidelity package and package-bound human review are complete. "
                "Real Windows acceptance remains required before Quest acceptance and final release."
            ),
        }
        return result

    if review_state == "required":
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate("required", reason=str(review.get("reason") or "explicit package-bound high-fidelity human review is required")),
        ]
        result["state"] = "human-review-required"
        result["next_gate"] = {
            "gate": FINAL_REVIEW_GATE,
            "command": _review_command(package),
            "operator_input_required": True,
            "reason": (
                "Review source identity, anatomy, skin, hair, eyes, face-secondary, "
                "full-body multiview and face close-up evidence for these exact package bytes."
            ),
        }
        return result

    result["gates"] = [
        *list(base.get("gates") or []),
        _final_review_gate("invalid" if review_state == "unavailable" else "blocked", reason=str(review.get("reason") or "high-fidelity human review is not valid")),
    ]
    result["state"] = "blocked"
    result["next_gate"] = None
    return result
