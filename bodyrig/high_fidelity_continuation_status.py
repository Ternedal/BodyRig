from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from . import high_fidelity_continuation_status_legacy as _legacy
from .high_fidelity_hfn_continuation import (
    CANDIDATE_GATE,
    HUMAN_GATE,
    RENDER_GATE,
    inspect_hfn_continuation,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError
from .storage import person_library

FORMAT = _legacy.FORMAT
VERSION = _legacy.VERSION
JOB_RE = _legacy.JOB_RE
SHA_RE = _legacy.SHA_RE
HighFidelityContinuationStatusError = _legacy.HighFidelityContinuationStatusError

GATE_ORDER = (*_legacy.GATE_ORDER, CANDIDATE_GATE, RENDER_GATE, HUMAN_GATE)
GATE_LABELS = {
    **_legacy.GATE_LABELS,
    CANDIDATE_GATE: "Source-grounded hands/feet/nails detail candidate",
    RENDER_GATE: "Hands/feet/nails canonical four-view render",
    HUMAN_GATE: "Hands/feet/nails package-bound human review",
}

_preview_root = _legacy._preview_root
_repo_root = _legacy._repo_root
_candidate_package = _legacy._candidate_package
_candidate_workspace = _legacy._candidate_workspace
component_review_status = _legacy.component_review_status
anatomy_promotion_status = _legacy.anatomy_promotion_status
hair_deformation_review_status = _legacy.hair_deformation_review_status
hair_promotion_status = _legacy.hair_promotion_status
audit_high_fidelity_package = _legacy.audit_high_fidelity_package
preview_manager = _legacy.preview_manager

_SYNC_SEAMS = (
    "_preview_root",
    "_repo_root",
    "_candidate_package",
    "_candidate_workspace",
    "component_review_status",
    "anatomy_promotion_status",
    "hair_deformation_review_status",
    "hair_promotion_status",
    "audit_high_fidelity_package",
    "preview_manager",
    "read_hair_promotion",
    "read_iris_candidate",
    "read_iris_review",
    "read_reviewed_runtime",
    "read_eligibility",
    "read_fingerprint",
    "read_rebuild",
    "read_eye_promotion",
    "read_face_runtime",
    "read_preview",
    "read_face_review",
    "read_face_promotion",
)


def _sync_legacy_seams() -> None:
    namespace = globals()
    for name in _SYNC_SEAMS:
        if name in namespace:
            setattr(_legacy, name, namespace[name])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def continuation_paths(preview_job_id: str) -> dict[str, Path]:
    job_id = _legacy._job(preview_job_id)
    root = _preview_root(job_id)
    continuation = root / "continuation"
    face = continuation / "face-secondary"
    face_preview = face / "windows-preview"
    hfn = continuation / "hands-feet-nails"
    return {
        "preview_root": root,
        "component_root": root / "components",
        "eye_geometry": root / "components" / "eyes",
        "source_eye_appearance": root / "components" / "eye-appearance",
        "base_runtime": root / "components" / "runtime",
        "continuation_root": continuation,
        "iris_candidate": continuation / "iris-candidate",
        "iris_reviewed_runtime": continuation / "iris-reviewed-runtime",
        "eye_only_runtime": continuation / "eye-only-runtime",
        "face_runtime": face / "runtime",
        "face_preview_root": face_preview,
        "face_preparation": face_preview / "preparation",
        "face_render": face_preview / "render",
        "face_review": face / "human-review",
        "face_promotion": face / "promotion",
        "hfn_root": hfn,
        "hfn_render": hfn / "render",
        "hfn_review": hfn / "human-review",
    }


def _gate(
    name: str,
    state: str,
    *,
    reason: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if name not in GATE_LABELS:
        raise HighFidelityContinuationStatusError(f"unknown high-fidelity continuation gate: {name}")
    if state not in {"pass", "required", "blocked", "invalid"}:
        state = "blocked"
    return {
        "id": name,
        "label": GATE_LABELS[name],
        "state": state,
        "passed": state == "pass",
        "reason": reason,
        "evidence": evidence or {},
    }


def _quote(value: Any) -> str:
    return _legacy._quote(value)


def _simple_state(value: Mapping[str, Any]) -> str:
    return _legacy._simple_state(value)


def _missing_or_invalid(exc: Exception, path: Path | None = None) -> str:
    return _legacy._missing_or_invalid(exc, path)


def _next_action(
    job_id: str,
    gate: str,
    paths: dict[str, Path],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    if gate in {CANDIDATE_GATE, RENDER_GATE, HUMAN_GATE}:
        action = ctx.get("hfn_action")
        if isinstance(action, Mapping) and action.get("gate") == gate:
            return dict(action)
        return {
            "gate": gate,
            "command": None,
            "operator_input_required": gate in {CANDIDATE_GATE, HUMAN_GATE},
            "reason": "Exact HFN continuation authority is unavailable; continuation remains fail-closed.",
        }
    _sync_legacy_seams()
    return _legacy._next_action(job_id, gate, paths, ctx)


def _replace_gate(
    gates: list[dict[str, Any]],
    gate_id: str,
    *,
    state: str,
    reason: str,
) -> None:
    for index, gate in enumerate(gates):
        if gate.get("id") == gate_id:
            gates[index] = _gate(
                gate_id,
                state,
                reason=reason,
                evidence=dict(gate.get("evidence") or {}),
            )
            return
    gates.append(_gate(gate_id, state, reason=reason))


def _result(
    job_id: str,
    gates: list[dict[str, Any]],
    paths: dict[str, Path],
    package_path: Path | None,
    package_sha: str | None,
    components: dict[str, str],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    passed = {item["id"] for item in gates if item.get("state") == "pass"}
    next_gate = next((name for name in GATE_ORDER if name not in passed), None)
    high_fidelity_complete = False
    audit: dict[str, Any] | None = None
    audit_gate = CANDIDATE_GATE if CANDIDATE_GATE in {item.get("id") for item in gates} else "face_secondary_promotion"

    if next_gate is None:
        try:
            if package_path is None or not package_path.is_file():
                raise HighFidelityPackageAuditError("final promoted package is missing")
            if not SHA_RE.fullmatch(str(package_sha or "")) or _sha256(package_path) != package_sha:
                raise HighFidelityPackageAuditError("final package bytes no longer match promotion SHA")
            audit = audit_high_fidelity_package(package_path)
            if audit.get("package_sha256") != package_sha or _sha256(package_path) != package_sha:
                raise HighFidelityPackageAuditError("final package changed during its component audit")
        except (OSError, HighFidelityPackageAuditError) as exc:
            audit = None
            components = {}
            _replace_gate(gates, audit_gate, state="invalid", reason=f"final package audit failed: {exc}")
            next_gate = audit_gate
        else:
            components = dict(audit["components"])
            high_fidelity_complete = bool(
                audit["high_fidelity_ready"] is True
                and components
                and all(value == "complete" for value in components.values())
            )
            if not high_fidelity_complete:
                _replace_gate(
                    gates,
                    audit_gate,
                    state="invalid",
                    reason="all continuation gates passed but final package is not high-fidelity component complete",
                )
                next_gate = audit_gate

    next_gate_state = next((
        str(item.get("state") or "") for item in gates if item.get("id") == next_gate
    ), "") if next_gate else ""
    state = "complete" if high_fidelity_complete else (
        "blocked" if next_gate_state in {"blocked", "invalid"} else "incomplete"
    )
    action = _next_action(job_id, next_gate, paths, context) if next_gate else None
    if action is not None and state == "blocked":
        action = {**action, "command": None, "reason": next((
            str(item.get("reason") or "") for item in gates if item.get("id") == next_gate
        ), "continuation authority is invalid")}
    return {
        "format": FORMAT,
        "version": VERSION,
        "preview_job_id": job_id,
        "state": state,
        "gates": gates,
        "next_gate": None if high_fidelity_complete else action,
        "current_package_path": str(package_path) if package_path is not None else None,
        "current_package_sha256": package_sha,
        "components": components,
        "high_fidelity_complete": high_fidelity_complete,
        "high_fidelity_human_review_required": high_fidelity_complete,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": audit,
    }


def _blocked_hfn_result(
    base: Mapping[str, Any],
    *,
    gates: list[dict[str, Any]],
    package_path: Path,
    package_sha: str,
    gate_id: str,
    reason: str,
) -> dict[str, Any]:
    result = dict(base)
    _replace_gate(gates, gate_id, state="invalid", reason=reason)
    result.update({
        "state": "blocked",
        "gates": gates,
        "next_gate": {
            "gate": gate_id,
            "command": None,
            "operator_input_required": False,
            "reason": reason,
        },
        "current_package_path": str(package_path),
        "current_package_sha256": package_sha,
        "components": {},
        "high_fidelity_complete": False,
        "high_fidelity_human_review_required": False,
        "production_ready": False,
        "production_activation": False,
        "final_audit": None,
    })
    return result


def inspect_continuation(preview_job_id: str) -> dict[str, Any]:
    _sync_legacy_seams()
    base = _legacy.inspect_continuation(preview_job_id)
    if base.get("high_fidelity_complete") is not True:
        return base

    job_id = _legacy._job(preview_job_id)
    paths = continuation_paths(job_id)
    try:
        preview = _legacy.preview_manager.get(job_id)
    except Exception as exc:
        raise HighFidelityContinuationStatusError(str(exc)) from exc

    person_id = str(preview.get("person_id") or "").strip().lower()
    body_revision = str(preview.get("body_revision") or "").strip().lower()
    bodyrig_revision = str(preview.get("bodyrig_revision") or "").strip().lower()
    package_value = str(base.get("current_package_path") or "").strip()
    package_sha = str(base.get("current_package_sha256") or "").strip().lower()
    if not person_id or not body_revision or not package_value or not SHA_RE.fullmatch(package_sha):
        source = Path(package_value).expanduser().resolve() if package_value else paths["face_promotion"]
        gates = list(base.get("gates") or [])
        reason = "face-secondary completion lacks canonical Person/body/package authority for HFN continuation"
        return _blocked_hfn_result(
            base,
            gates=gates,
            package_path=source,
            package_sha=package_sha,
            gate_id=CANDIDATE_GATE,
            reason=reason,
        )
    if not _legacy.SHA_RE.fullmatch(bodyrig_revision):
        source = Path(package_value).expanduser().resolve()
        gates = list(base.get("gates") or [])
        return _blocked_hfn_result(
            base,
            gates=gates,
            package_path=source,
            package_sha=package_sha,
            gate_id=CANDIDATE_GATE,
            reason="preview BodyRig revision is not canonical for HFN continuation",
        )

    source_package = Path(package_value).expanduser().resolve()
    hfn = inspect_hfn_continuation(
        root=person_library(),
        person_id=person_id,
        body_revision=body_revision,
        bodyrig_revision=bodyrig_revision,
        source_package_path=source_package,
        source_package_sha256=package_sha,
        render_dir=paths["hfn_render"],
        human_review_dir=paths["hfn_review"],
    )

    combined = list(base.get("gates") or [])
    for item in hfn.get("gates") or []:
        combined.append(_gate(
            str(item.get("id") or ""),
            str(item.get("state") or "blocked"),
            reason=str(item.get("reason") or ""),
            evidence=dict(item.get("evidence") or {}),
        ))

    current_package = Path(hfn.get("package_path") or source_package).expanduser().resolve()
    current_sha = str(hfn.get("package_sha256") or package_sha).lower()
    first_unpassed = next((
        item for item in hfn.get("gates") or [] if item.get("state") != "pass"
    ), None)
    if first_unpassed is not None:
        gate_id = str(first_unpassed["id"])
        state = "blocked" if first_unpassed.get("state") in {"blocked", "invalid"} else "incomplete"
        action = (hfn.get("actions") or {}).get(gate_id)
        if state == "blocked":
            action = {
                "gate": gate_id,
                "command": None,
                "operator_input_required": False,
                "reason": str(first_unpassed.get("reason") or "HFN continuation is invalid"),
            }
        elif not isinstance(action, Mapping):
            action = {
                "gate": gate_id,
                "command": None,
                "operator_input_required": False,
                "reason": str(first_unpassed.get("reason") or "HFN continuation authority is missing"),
            }
        result = dict(base)
        result.update({
            "state": state,
            "gates": combined,
            "next_gate": dict(action),
            "current_package_path": str(current_package),
            "current_package_sha256": current_sha,
            "high_fidelity_complete": False,
            "high_fidelity_human_review_required": False,
            "production_ready": False,
            "production_activation": False,
            "final_audit": None,
        })
        return result

    try:
        if not current_package.is_file() or _sha256(current_package) != current_sha:
            raise HighFidelityPackageAuditError("HFN-reviewed candidate package bytes changed before final audit")
        audit = audit_high_fidelity_package(current_package)
        if audit.get("package_sha256") != current_sha or _sha256(current_package) != current_sha:
            raise HighFidelityPackageAuditError("HFN-reviewed candidate changed during final component audit")
        components = dict(audit.get("components") or {})
        if not (
            audit.get("high_fidelity_ready") is True
            and components
            and all(value == "complete" for value in components.values())
        ):
            raise HighFidelityPackageAuditError(
                "HFN-reviewed candidate is no longer high-fidelity component complete"
            )
    except (OSError, HighFidelityPackageAuditError) as exc:
        return _blocked_hfn_result(
            base,
            gates=combined,
            package_path=current_package,
            package_sha=current_sha,
            gate_id=CANDIDATE_GATE,
            reason=f"final HFN candidate audit failed: {exc}",
        )

    result = dict(base)
    result.update({
        "state": "complete",
        "gates": combined,
        "next_gate": None,
        "current_package_path": str(current_package),
        "current_package_sha256": current_sha,
        "components": components,
        "high_fidelity_complete": True,
        "high_fidelity_human_review_required": True,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": audit,
    })
    return result


def __getattr__(name: str) -> Any:
    return getattr(_legacy, name)
