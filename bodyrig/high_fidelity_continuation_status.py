from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import high_fidelity_continuation_status_legacy as _legacy
from .fine_identity_application import (
    FineIdentityApplicationError,
    validate_requirement as validate_fine_identity_requirement,
)
from .high_fidelity_hfn_continuation import (
    CANDIDATE_GATE,
    HUMAN_GATE,
    RENDER_GATE,
    inspect_hfn_continuation,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError
from .photoidentity_fine_identity_package import (
    PhotoIdentityFineIdentityPackageError,
    read_application_output,
)
from .physical_handoff_floor import MINIMUM_PHYSICAL_HANDOFF_REVISION
from .storage import person_library

FORMAT = _legacy.FORMAT
VERSION = _legacy.VERSION
JOB_RE = _legacy.JOB_RE
SHA_RE = _legacy.SHA_RE
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
MINIMUM_HFN_INTEGRATION_REVISION = MINIMUM_PHYSICAL_HANDOFF_REVISION
HighFidelityContinuationStatusError = _legacy.HighFidelityContinuationStatusError

FINE_IDENTITY_GATE = "fine_identity_application"
GATE_ORDER = (*_legacy.GATE_ORDER, CANDIDATE_GATE, RENDER_GATE, HUMAN_GATE, FINE_IDENTITY_GATE)
GATE_LABELS = {
    **_legacy.GATE_LABELS,
    CANDIDATE_GATE: "Source-grounded hands/feet/nails detail candidate",
    RENDER_GATE: "Hands/feet/nails canonical four-view render",
    HUMAN_GATE: "Hands/feet/nails package-bound human review",
    FINE_IDENTITY_GATE: "Terminal source-grounded fine-identity application",
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


def _integration_checkout_state() -> tuple[str, bool, bool]:
    root = _repo_root().expanduser().resolve()
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        floor = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                MINIMUM_HFN_INTEGRATION_REVISION,
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HighFidelityContinuationStatusError(
            "Git executable is unavailable for HFN integration revision validation"
        ) from exc
    revision = head.stdout.strip().lower()
    if head.returncode != 0 or not GIT_RE.fullmatch(revision):
        raise HighFidelityContinuationStatusError(
            "could not resolve the current BodyRig revision for HFN integration"
        )
    if dirty.returncode != 0:
        raise HighFidelityContinuationStatusError(
            "could not inspect BodyRig checkout cleanliness for HFN integration"
        )
    return revision, not bool(dirty.stdout.strip()), floor.returncode == 0


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
        "fine_identity": continuation / "fine-identity-application",
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
    if gate == FINE_IDENTITY_GATE:
        action = ctx.get("fine_identity_action")
        if isinstance(action, Mapping) and action.get("gate") == gate:
            return dict(action)
        return {
            "gate": gate,
            "command": (
                f".\\apply-photoidentity-fine-identity.ps1 -PreviewJobId {_quote(job_id)} "
                "-SweepRoot <SWEEP_ROOT> -AdapterConfig <ADAPTER_CONFIG>"
            ),
            "operator_input_required": True,
            "reason": (
                "Run the terminal source-grounded fine-identity application from the exact private "
                "PhotoIdentity sweep and one pinned local adapter config. Replace both placeholders "
                "with real paths; no generic or generative fallback is permitted."
            ),
        }
    _sync_legacy_seams()
    return _legacy._next_action(job_id, gate, paths, ctx)


def _fine_identity_pending_audit(
    audit: Mapping[str, Any],
    *,
    expected_authority_sha256: str | None = None,
    expected_attestation_sha256: str | None = None,
    expected_bodyrig_revision: str | None = None,
) -> dict[str, Any] | None:
    components = audit.get("components")
    blockers = audit.get("top_level_blockers")
    fine = audit.get("fine_identity")
    if (
        audit.get("fine_identity_required") is not True
        or audit.get("fine_identity_ready") is not False
        or audit.get("high_fidelity_ready") is not False
        or audit.get("production_ready") is not False
        or not isinstance(components, Mapping)
        or not components
        or any(value != "complete" for value in components.values())
        or blockers != ["fine_identity"]
        or not isinstance(fine, Mapping)
        or fine.get("application") is not None
    ):
        return None
    try:
        requirement = validate_fine_identity_requirement(fine.get("requirement"))
    except FineIdentityApplicationError:
        return None
    if (
        expected_authority_sha256 is not None
        and requirement["fineIdentityAuthoritySha256"] != expected_authority_sha256
    ):
        return None
    if (
        expected_attestation_sha256 is not None
        and requirement["fineIdentityAttestationSha256"] != expected_attestation_sha256
    ):
        return None
    if (
        expected_bodyrig_revision is not None
        and requirement["bodyrigRevision"] != expected_bodyrig_revision
    ):
        return None
    return {
        "components": dict(components),
        "requirement": requirement,
    }


def _fine_identity_hfn_handoff(
    base: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if base.get("high_fidelity_complete") is True or base.get("state") != "blocked":
        return None
    next_gate = base.get("next_gate")
    gates_raw = base.get("gates")
    if (
        not isinstance(next_gate, Mapping)
        or next_gate.get("gate") != "face_secondary_promotion"
        or not isinstance(gates_raw, list)
        or len(gates_raw) != len(_legacy.GATE_ORDER)
        or [item.get("id") for item in gates_raw if isinstance(item, Mapping)] != list(_legacy.GATE_ORDER)
        or any(
            not isinstance(item, Mapping) or item.get("state") != "pass"
            for item in gates_raw[:-1]
        )
        or not isinstance(gates_raw[-1], Mapping)
        or gates_raw[-1].get("state") != "invalid"
    ):
        return None

    package_value = str(base.get("current_package_path") or "").strip()
    package_sha = str(base.get("current_package_sha256") or "").strip().lower()
    authority_sha = str(base.get("fine_identity_authority_sha256") or "").strip().lower()
    attestation_sha = str(base.get("fine_identity_attestation_sha256") or "").strip().lower()
    if (
        not package_value
        or not SHA_RE.fullmatch(package_sha)
        or not SHA_RE.fullmatch(authority_sha)
        or not SHA_RE.fullmatch(attestation_sha)
    ):
        return None
    package = Path(package_value).expanduser().resolve()
    try:
        if not package.is_file() or _sha256(package) != package_sha:
            return None
        audit = audit_high_fidelity_package(package)
        if audit.get("package_sha256") != package_sha or _sha256(package) != package_sha:
            return None
    except (OSError, HighFidelityPackageAuditError):
        return None

    pending = _fine_identity_pending_audit(
        audit,
        expected_authority_sha256=authority_sha,
        expected_attestation_sha256=attestation_sha,
    )
    if pending is None:
        return None

    normalized_gates = [dict(item) for item in gates_raw]
    normalized_gates[-1] = _gate(
        "face_secondary_promotion",
        "pass",
        evidence={
            "promoted_package_sha256": package_sha,
            "fine_identity_pending": True,
        },
    )
    result = dict(base)
    result.update(
        {
            "state": "incomplete",
            "gates": normalized_gates,
            "next_gate": None,
            "components": dict(pending["components"]),
            "high_fidelity_complete": False,
            "high_fidelity_human_review_required": False,
            "production_ready": False,
            "production_activation": False,
            "final_audit": audit,
        }
    )
    return result, dict(pending["requirement"])


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
        "fine_identity_authority_sha256": str((context or {}).get("fine_identity_authority_sha256") or "") or None,
        "fine_identity_attestation_sha256": str((context or {}).get("fine_identity_attestation_sha256") or "") or None,
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


def _migration_required_result(
    base: Mapping[str, Any],
    *,
    job_id: str,
    package_path: Path,
    package_sha: str,
    source_bodyrig_revision: str,
) -> dict[str, Any]:
    reason = (
        "Legacy anatomy/hair/eyes/face-secondary continuation is complete, but HFN must be applied by a clean "
        "current integration checkout. Preserve the exact legacy promoted package and return to current main before "
        "creating any HFN receipt."
    )
    gates = list(base.get("gates") or [])
    gates.append(_gate(CANDIDATE_GATE, "required", reason=reason))
    quoted_job = _quote(job_id)
    result = dict(base)
    result.update({
        "state": "incomplete",
        "gates": gates,
        "next_gate": {
            "gate": CANDIDATE_GATE,
            "command": (
                ".\\update-windows.ps1 -NoBrowser -SkipPlan; "
                f"if ($?) {{ & .\\high-fidelity-physical-status.ps1 -PreviewJobId {quoted_job} }}"
            ),
            "operator_input_required": False,
            "reason": reason,
        },
        "current_package_path": str(package_path),
        "current_package_sha256": package_sha,
        "source_bodyrig_revision": source_bodyrig_revision,
        "hfn_bodyrig_revision": None,
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
    fine_identity_handoff_requirement: dict[str, Any] | None = None
    if base.get("high_fidelity_complete") is not True:
        handoff = _fine_identity_hfn_handoff(base)
        if handoff is None:
            return base
        base, fine_identity_handoff_requirement = handoff

    job_id = _legacy._job(preview_job_id)
    paths = continuation_paths(job_id)
    try:
        preview = _legacy.preview_manager.get(job_id)
    except Exception as exc:
        raise HighFidelityContinuationStatusError(str(exc)) from exc

    person_id = str(preview.get("person_id") or "").strip().lower()
    body_revision = str(preview.get("body_revision") or "").strip().lower()
    source_bodyrig_revision = str(preview.get("bodyrig_revision") or "").strip().lower()
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
    if not GIT_RE.fullmatch(source_bodyrig_revision):
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
    if (
        fine_identity_handoff_requirement is not None
        and fine_identity_handoff_requirement["bodyrigRevision"] != source_bodyrig_revision
    ):
        source = Path(package_value).expanduser().resolve()
        return _blocked_hfn_result(
            base,
            gates=list(base.get("gates") or []),
            package_path=source,
            package_sha=package_sha,
            gate_id=CANDIDATE_GATE,
            reason="fine-identity requirement BodyRig revision differs from the originating preview authority",
        )

    source_package = Path(package_value).expanduser().resolve()
    try:
        hfn_bodyrig_revision, checkout_clean, hfn_floor_present = _integration_checkout_state()
    except HighFidelityContinuationStatusError as exc:
        blocked = _blocked_hfn_result(
            base,
            gates=list(base.get("gates") or []),
            package_path=source_package,
            package_sha=package_sha,
            gate_id=CANDIDATE_GATE,
            reason=str(exc),
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = None
        return blocked
    if not checkout_clean:
        blocked = _blocked_hfn_result(
            base,
            gates=list(base.get("gates") or []),
            package_path=source_package,
            package_sha=package_sha,
            gate_id=CANDIDATE_GATE,
            reason="BodyRig checkout is dirty; HFN continuation requires exact clean integration authority",
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = None
        return blocked
    if not hfn_floor_present:
        return _migration_required_result(
            base,
            job_id=job_id,
            package_path=source_package,
            package_sha=package_sha,
            source_bodyrig_revision=source_bodyrig_revision,
        )

    hfn = inspect_hfn_continuation(
        root=person_library(),
        person_id=person_id,
        body_revision=body_revision,
        bodyrig_revision=hfn_bodyrig_revision,
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
            "source_bodyrig_revision": source_bodyrig_revision,
            "hfn_bodyrig_revision": hfn_bodyrig_revision,
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
    except (OSError, HighFidelityPackageAuditError) as exc:
        blocked = _blocked_hfn_result(
            base,
            gates=combined,
            package_path=current_package,
            package_sha=current_sha,
            gate_id=CANDIDATE_GATE,
            reason=f"final HFN candidate audit failed: {exc}",
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = hfn_bodyrig_revision
        return blocked

    components = dict(audit.get("components") or {})
    expected_fine_authority = (
        str(base.get("fine_identity_authority_sha256") or "").strip().lower() or None
    )
    expected_fine_attestation = (
        str(base.get("fine_identity_attestation_sha256") or "").strip().lower() or None
    )
    fine_pending = _fine_identity_pending_audit(
        audit,
        expected_authority_sha256=expected_fine_authority,
        expected_attestation_sha256=expected_fine_attestation,
        expected_bodyrig_revision=(
            source_bodyrig_revision if fine_identity_handoff_requirement is not None else None
        ),
    )
    if fine_pending is not None and (
        expected_fine_authority is None or expected_fine_attestation is None
    ):
        blocked = _blocked_hfn_result(
            base,
            gates=combined,
            package_path=current_package,
            package_sha=current_sha,
            gate_id=CANDIDATE_GATE,
            reason="final HFN candidate introduced fine-identity requirements without originating lineage authority",
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = hfn_bodyrig_revision
        return blocked
    if fine_pending is not None:
        application_root = paths["fine_identity"]
        application_output = application_root / "package"
        if application_root.exists():
            try:
                applied = read_application_output(
                    application_output,
                    expected_source_package_sha256=current_sha,
                    expected_fine_identity_authority_sha256=fine_pending["requirement"][
                        "fineIdentityAuthoritySha256"
                    ],
                    expected_fine_identity_attestation_sha256=fine_pending["requirement"][
                        "fineIdentityAttestationSha256"
                    ],
                )
            except (OSError, PhotoIdentityFineIdentityPackageError) as exc:
                reason = f"terminal fine-identity application output is invalid: {exc}"
                combined.append(
                    _gate(
                        FINE_IDENTITY_GATE,
                        "invalid",
                        reason=reason,
                        evidence={
                            "fine_identity_authority_sha256": fine_pending["requirement"][
                                "fineIdentityAuthoritySha256"
                            ],
                            "fine_identity_attestation_sha256": fine_pending["requirement"][
                                "fineIdentityAttestationSha256"
                            ],
                            "hfn_package_sha256": current_sha,
                        },
                    )
                )
                result = dict(base)
                result.update(
                    {
                        "state": "blocked",
                        "gates": combined,
                        "next_gate": {
                            "gate": FINE_IDENTITY_GATE,
                            "command": None,
                            "operator_input_required": False,
                            "reason": reason,
                        },
                        "current_package_path": str(current_package),
                        "current_package_sha256": current_sha,
                        "components": components,
                        "source_bodyrig_revision": source_bodyrig_revision,
                        "hfn_bodyrig_revision": hfn_bodyrig_revision,
                        "high_fidelity_complete": False,
                        "high_fidelity_human_review_required": False,
                        "physical_windows_acceptance_required": True,
                        "quest_acceptance_required": True,
                        "final_release_required": True,
                        "production_ready": False,
                        "production_activation": False,
                        "final_audit": audit,
                    }
                )
                return result

            applied_package = Path(str(applied["package_path"])).expanduser().resolve()
            applied_sha = str(applied["applied_package_sha256"])
            applied_audit = dict(applied["audit"])
            applied_components = dict(applied_audit.get("components") or {})
            combined.append(
                _gate(
                    FINE_IDENTITY_GATE,
                    "pass",
                    evidence={
                        "fine_identity_authority_sha256": fine_pending["requirement"][
                            "fineIdentityAuthoritySha256"
                        ],
                        "fine_identity_attestation_sha256": fine_pending["requirement"][
                            "fineIdentityAttestationSha256"
                        ],
                        "hfn_package_sha256": current_sha,
                        "applied_package_sha256": applied_sha,
                        "application_receipt_sha256": _sha256(
                            Path(str(applied["receipt_path"])).expanduser().resolve()
                        ),
                    },
                )
            )
            result = dict(base)
            result.update(
                {
                    "state": "complete",
                    "gates": combined,
                    "next_gate": None,
                    "current_package_path": str(applied_package),
                    "current_package_sha256": applied_sha,
                    "components": applied_components,
                    "source_bodyrig_revision": source_bodyrig_revision,
                    "hfn_bodyrig_revision": hfn_bodyrig_revision,
                    "high_fidelity_complete": True,
                    "high_fidelity_human_review_required": True,
                    "physical_windows_acceptance_required": True,
                    "quest_acceptance_required": True,
                    "final_release_required": True,
                    "production_ready": False,
                    "production_activation": False,
                    "final_audit": applied_audit,
                }
            )
            return result

        reason = (
            "HFN review is complete, but photoidentical readiness still requires the exact "
            "source-grounded terminal fine-identity application on these final avatar bytes."
        )
        combined.append(
            _gate(
                FINE_IDENTITY_GATE,
                "required",
                reason=reason,
                evidence={
                    "fine_identity_authority_sha256": fine_pending["requirement"]["fineIdentityAuthoritySha256"],
                    "fine_identity_attestation_sha256": fine_pending["requirement"]["fineIdentityAttestationSha256"],
                    "source_package_sha256": package_sha,
                    "hfn_package_sha256": current_sha,
                },
            )
        )
        action = _next_action(
            job_id,
            FINE_IDENTITY_GATE,
            paths,
            {
                "fine_identity_authority_sha256": fine_pending["requirement"]["fineIdentityAuthoritySha256"],
                "fine_identity_attestation_sha256": fine_pending["requirement"]["fineIdentityAttestationSha256"],
            },
        )
        result = dict(base)
        result.update(
            {
                "state": "incomplete",
                "gates": combined,
                "next_gate": action,
                "current_package_path": str(current_package),
                "current_package_sha256": current_sha,
                "components": components,
                "source_bodyrig_revision": source_bodyrig_revision,
                "hfn_bodyrig_revision": hfn_bodyrig_revision,
                "high_fidelity_complete": False,
                "high_fidelity_human_review_required": False,
                "physical_windows_acceptance_required": True,
                "quest_acceptance_required": True,
                "final_release_required": True,
                "production_ready": False,
                "production_activation": False,
                "final_audit": audit,
            }
        )
        return result

    if not (
        audit.get("high_fidelity_ready") is True
        and components
        and all(value == "complete" for value in components.values())
    ):
        blocked = _blocked_hfn_result(
            base,
            gates=combined,
            package_path=current_package,
            package_sha=current_sha,
            gate_id=CANDIDATE_GATE,
            reason="final HFN candidate audit failed: HFN-reviewed candidate is no longer high-fidelity component complete",
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = hfn_bodyrig_revision
        return blocked

    fine_required = audit.get("fine_identity_required")
    fine_ready = audit.get("fine_identity_ready")
    if fine_required not in {True, False} or fine_ready is not True:
        blocked = _blocked_hfn_result(
            base,
            gates=combined,
            package_path=current_package,
            package_sha=current_sha,
            gate_id=CANDIDATE_GATE,
            reason="final HFN candidate audit failed: fine-identity readiness state is not canonical",
        )
        blocked["source_bodyrig_revision"] = source_bodyrig_revision
        blocked["hfn_bodyrig_revision"] = hfn_bodyrig_revision
        return blocked

    combined.append(
        _gate(
            FINE_IDENTITY_GATE,
            "pass",
            evidence={"required": fine_required, "ready": True},
        )
    )
    result = dict(base)
    result.update({
        "state": "complete",
        "gates": combined,
        "next_gate": None,
        "current_package_path": str(current_package),
        "current_package_sha256": current_sha,
        "components": components,
        "source_bodyrig_revision": source_bodyrig_revision,
        "hfn_bodyrig_revision": hfn_bodyrig_revision,
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
