from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .high_fidelity_continuation_status import (
    HighFidelityContinuationStatusError,
    inspect_continuation,
)
from .high_fidelity_human_review import (
    HighFidelityHumanReviewError,
    invalid_review_recovery_status,
    review_status as high_fidelity_human_review_status,
)
from .high_fidelity_physical_acceptance import (
    HighFidelityPhysicalAcceptanceError,
    physical_acceptance_dir,
)
from .high_fidelity_physical_acceptance_audit import audited_physical_acceptance_status

# Preserve the established integration seam for tests/callers while routing the
# default implementation through the transitive authority audit.
physical_acceptance_status = audited_physical_acceptance_status

FORMAT = "bodyrig-high-fidelity-release-readiness"
VERSION = 1
FINAL_REVIEW_GATE = "high_fidelity_human_review"
FINAL_REVIEW_RECOVERY_GATE = "high_fidelity_human_review_recovery"
PHYSICAL_GATE_A = "physical_gate_a"
WINDOWS_GATE = "physical_windows_acceptance"
QUEST_GATE = "physical_quest_acceptance"
FINAL_RELEASE_GATE = "final_release"


class HighFidelityReleaseReadinessError(RuntimeError):
    pass


def _gate(
    gate_id: str,
    label: str,
    state: str,
    *,
    reason: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "label": label,
        "state": state,
        "passed": state == "pass",
        "reason": reason,
        "evidence": evidence or {},
    }


def _final_review_gate(state: str, *, reason: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return _gate(
        FINAL_REVIEW_GATE,
        "Package-bound high-fidelity human review",
        state,
        reason=reason,
        evidence=evidence,
    )


def _review_command(package_path: Path) -> str:
    quoted = "'" + str(package_path).replace("'", "''") + "'"
    return (
        ".\\record-high-fidelity-human-review.ps1 "
        f"-PackagePath {quoted} -ConfirmQualityChecklist -QualityNote '<QUALITY_NOTE>'"
    )


def _review_recovery_command(package_path: Path) -> str:
    quoted = "'" + str(package_path).replace("'", "''") + "'"
    return f".\\archive-invalid-high-fidelity-human-review.ps1 -PackagePath {quoted}"


def _require_package_bytes(package: Path, expected_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise HighFidelityReleaseReadinessError("promoted package SHA is missing or not canonical")
    with package.open("rb") as handle:
        actual_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual_sha != expected_sha:
        raise HighFidelityReleaseReadinessError("promoted package bytes no longer match continuation SHA")


def _blocked(result: dict[str, Any], reason: str, *, package_invalid: bool = False) -> dict[str, Any]:
    result["state"] = "blocked"
    result["gates"] = [*list(result.get("gates") or []), _final_review_gate("invalid", reason=reason)]
    result["next_gate"] = None
    if package_invalid:
        result["component_package_complete"] = False
        result["high_fidelity_complete"] = False
        result["components"] = {}
        result["final_audit"] = None
    return result


def _review_recovery_required(
    result: dict[str, Any],
    package: Path,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    reason = str(recovery.get("reason") or "current high-fidelity human-review receipt is invalid")
    result["gates"] = [
        *list(result.get("gates") or []),
        _final_review_gate(
            "invalid",
            reason=reason,
            evidence={
                "review_path": recovery.get("review_path"),
                "receipt_sha256": recovery.get("receipt_sha256"),
                "archive_path": recovery.get("archive_path"),
            },
        ),
    ]
    result["state"] = "human-review-recovery-required"
    result["next_gate"] = {
        "gate": FINAL_REVIEW_RECOVERY_GATE,
        "command": _review_recovery_command(package),
        "operator_input_required": True,
        "reason": (
            "Preserve the invalid create-only human-review receipt under its content-addressed archive name, "
            "then rerun status and perform a new explicit review of the exact package."
        ),
    }
    return result


def _physical_required(
    result: dict[str, Any],
    *,
    gate_id: str,
    label: str,
    reason: str,
    command: str | None,
    state: str,
) -> dict[str, Any]:
    result["gates"] = [
        *list(result.get("gates") or []),
        _gate(gate_id, label, "required", reason=reason),
    ]
    result["state"] = state
    result["next_gate"] = {
        "gate": gate_id,
        "command": command,
        "operator_input_required": True,
        "reason": reason,
    }
    return result


def _apply_physical_status(
    result: dict[str, Any],
    *,
    physical: dict[str, Any],
) -> dict[str, Any]:
    state = str(physical.get("state") or "invalid")
    physical_gate = str(physical.get("gate") or "")
    reason = str(physical.get("message") or "")
    command = physical.get("next_command")
    acceptance_dir = str(physical.get("acceptance_dir") or "")
    result["physical_acceptance_dir"] = acceptance_dir or None

    if state == "invalid":
        result["gates"] = [
            *list(result.get("gates") or []),
            _gate(PHYSICAL_GATE_A, "Fresh promoted-package Gate A", "invalid", reason=reason),
        ]
        result["state"] = "blocked"
        result["next_gate"] = None
        return result

    if physical_gate == "physical-gate-a":
        return _physical_required(
            result,
            gate_id=PHYSICAL_GATE_A,
            label="Fresh promoted-package Gate A",
            reason=reason,
            command=str(command) if command else None,
            state="physical-gate-a-required",
        )

    result["gates"] = [
        *list(result.get("gates") or []),
        _gate(
            PHYSICAL_GATE_A,
            "Fresh promoted-package Gate A",
            "pass",
            reason="Fresh QA/runtime authority exists for the exact final promoted package.",
            evidence={
                "acceptance_dir": acceptance_dir,
                "bodyrig_revision": physical.get("bodyrig_revision"),
            },
        ),
    ]

    if physical_gate in {"windows-probe", "windows-attestation"}:
        return _physical_required(
            result,
            gate_id=WINDOWS_GATE,
            label="WindowsPlayer physical acceptance",
            reason=reason,
            command=str(command) if command else None,
            state="physical-windows-acceptance-required",
        )

    result["gates"] = [
        *list(result.get("gates") or []),
        _gate(
            WINDOWS_GATE,
            "WindowsPlayer physical acceptance",
            "pass",
            reason="Exact promoted runtime has passed Windows machine/deformation + human review.",
        ),
    ]
    result["physical_windows_acceptance_required"] = False

    if physical_gate in {"quest-probe", "quest-attestation"}:
        return _physical_required(
            result,
            gate_id=QUEST_GATE,
            label="Quest-class physical acceptance",
            reason=reason,
            command=str(command) if command else None,
            state="physical-quest-acceptance-required",
        )

    result["gates"] = [
        *list(result.get("gates") or []),
        _gate(
            QUEST_GATE,
            "Quest-class physical acceptance",
            "pass",
            reason="The same exact promoted runtime has passed Quest machine/deformation + human review.",
        ),
    ]
    result["quest_acceptance_required"] = False

    if physical_gate == "release" and state != "complete":
        return _physical_required(
            result,
            gate_id=FINAL_RELEASE_GATE,
            label="Canonical final release",
            reason=reason,
            command=str(command) if command else None,
            state="final-release-required",
        )

    if physical_gate == "release" and state == "complete" and physical.get("production_activation") is True:
        result["gates"] = [
            *list(result.get("gates") or []),
            _gate(
                FINAL_RELEASE_GATE,
                "Canonical final release",
                "pass",
                reason=reason,
                evidence={"acceptance_dir": acceptance_dir},
            ),
        ]
        result["final_release_required"] = False
        result["state"] = "production-ready"
        result["next_gate"] = None
        result["production_ready"] = True
        result["production_activation"] = True
        return result

    result["gates"] = [
        *list(result.get("gates") or []),
        _gate(
            FINAL_RELEASE_GATE,
            "Canonical final release",
            "invalid",
            reason=f"Unsupported physical acceptance state: {state}/{physical_gate}",
        ),
    ]
    result["state"] = "blocked"
    result["next_gate"] = None
    return result


def _frozen_gate_a_review_status(
    result: dict[str, Any],
    *,
    base: dict[str, Any],
    preview_job_id: str,
    package: Path,
    expected_sha: str,
) -> dict[str, Any] | None:
    try:
        acceptance = physical_acceptance_dir(preview_job_id)
    except HighFidelityPhysicalAcceptanceError as exc:
        return _blocked(result, str(exc))
    if not acceptance.is_dir():
        return None

    try:
        _require_package_bytes(package, expected_sha)
    except (OSError, HighFidelityReleaseReadinessError) as exc:
        return _blocked(result, str(exc), package_invalid=True)

    result["gates"] = [
        *list(base.get("gates") or []),
        _final_review_gate(
            "pass",
            reason="Package-bound human review is frozen and revalidated through fresh Gate A authority.",
            evidence={
                "package_sha256": expected_sha,
                "frozen_by_gate_a": True,
                "acceptance_dir": str(acceptance),
            },
        ),
    ]
    result["high_fidelity_human_review_complete"] = True
    result["high_fidelity_human_review_required"] = False
    result["software_ready_for_physical_acceptance"] = True
    try:
        physical = physical_acceptance_status(
            preview_job_id,
            package_path=package,
            package_sha256=expected_sha,
        )
    except (OSError, HighFidelityPhysicalAcceptanceError) as exc:
        physical = {
            "state": "invalid",
            "gate": "physical-gate-a",
            "message": str(exc),
            "next_command": None,
            "acceptance_dir": str(acceptance),
            "production_activation": False,
        }
    return _apply_physical_status(result, physical=physical)


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
        return _blocked(result, "component-complete continuation has no exact promoted package path", package_invalid=True)
    package = Path(package_value).expanduser().resolve()
    expected_sha = str(base.get("current_package_sha256") or "")
    try:
        _require_package_bytes(package, expected_sha)
    except (OSError, HighFidelityReleaseReadinessError) as exc:
        return _blocked(result, str(exc), package_invalid=True)

    frozen = _frozen_gate_a_review_status(
        result,
        base=base,
        preview_job_id=preview_job_id,
        package=package,
        expected_sha=expected_sha,
    )
    if frozen is not None:
        return frozen

    try:
        review = high_fidelity_human_review_status(package)
    except (OSError, HighFidelityHumanReviewError) as exc:
        frozen = _frozen_gate_a_review_status(
            result,
            base=base,
            preview_job_id=preview_job_id,
            package=package,
            expected_sha=expected_sha,
        )
        if frozen is not None:
            return frozen
        try:
            recovery = invalid_review_recovery_status(package)
        except (OSError, HighFidelityHumanReviewError) as recovery_exc:
            return _blocked(result, f"{exc}; human-review recovery inspection failed: {recovery_exc}")
        if recovery.get("available") is True:
            frozen = _frozen_gate_a_review_status(
                result,
                base=base,
                preview_job_id=preview_job_id,
                package=package,
                expected_sha=expected_sha,
            )
            if frozen is not None:
                return frozen
            try:
                _require_package_bytes(package, expected_sha)
            except (OSError, HighFidelityReleaseReadinessError) as package_exc:
                return _blocked(result, str(package_exc), package_invalid=True)
            if str(recovery.get("package_sha256") or "") != expected_sha:
                return _blocked(
                    result,
                    "human-review recovery inspected package bytes that do not match continuation authority",
                    package_invalid=True,
                )
            return _review_recovery_required(result, package, recovery)
        return _blocked(result, str(exc))
    try:
        _require_package_bytes(package, expected_sha)
    except (OSError, HighFidelityReleaseReadinessError) as exc:
        return _blocked(result, str(exc), package_invalid=True)

    review_state = str(review.get("state") or "blocked")
    if review_state == "pass" and review.get("passed") is True:
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate(
                "pass",
                evidence={
                    "package_sha256": expected_sha,
                    "reviewed_utc": review.get("reviewed_utc"),
                    "policy_revision": review.get("policy_revision"),
                },
            ),
        ]
        result["high_fidelity_human_review_complete"] = True
        result["high_fidelity_human_review_required"] = False
        result["software_ready_for_physical_acceptance"] = True
        try:
            physical = physical_acceptance_status(
                preview_job_id,
                package_path=package,
                package_sha256=expected_sha,
            )
        except (OSError, HighFidelityPhysicalAcceptanceError) as exc:
            physical = {
                "state": "invalid",
                "gate": "physical-gate-a",
                "message": str(exc),
                "next_command": None,
                "acceptance_dir": None,
                "production_activation": False,
            }
        return _apply_physical_status(result, physical=physical)

    if review_state == "required":
        frozen = _frozen_gate_a_review_status(
            result,
            base=base,
            preview_job_id=preview_job_id,
            package=package,
            expected_sha=expected_sha,
        )
        if frozen is not None:
            return frozen
        result["gates"] = [
            *list(base.get("gates") or []),
            _final_review_gate(
                "required",
                reason=str(review.get("reason") or "explicit package-bound high-fidelity human review is required"),
            ),
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
        _final_review_gate(
            "invalid" if review_state == "unavailable" else "blocked",
            reason=str(review.get("reason") or "high-fidelity human review is not valid"),
        ),
    ]
    result["state"] = "blocked"
    result["next_gate"] = None
    return result
