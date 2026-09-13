from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import high_fidelity_continuation_status as current
from .high_fidelity_hfn_migration import HighFidelityHfnMigrationError, read_migration


class HighFidelityHfnMigratedStatusError(RuntimeError):
    pass


def _required_migration(
    base: Mapping[str, Any],
    *,
    preview_job_id: str,
    package_path: Path,
    package_sha: str,
    source_revision: str,
) -> dict[str, Any]:
    gates = list(base.get("gates") or [])
    gates.append(
        current._gate(
            current.CANDIDATE_GATE,
            "required",
            reason=(
                "Historical anatomy/hair/eyes/face-secondary continuation is complete, but HFN application must be "
                "explicitly rebound to a current HFN-safe integration revision before detail candidate creation."
            ),
            evidence={
                "source_bodyrig_revision": source_revision,
                "source_package_sha256": package_sha,
            },
        )
    )
    result = dict(base)
    result.update(
        {
            "state": "incomplete",
            "gates": gates,
            "next_gate": {
                "gate": current.CANDIDATE_GATE,
                "command": f".\\prepare-high-fidelity-hfn-migration.ps1 -PreviewJobId '{preview_job_id}'",
                "operator_input_required": False,
                "reason": "Create a review-only migration receipt before current-main HFN application.",
            },
            "current_package_path": str(package_path),
            "current_package_sha256": package_sha,
            "high_fidelity_complete": False,
            "high_fidelity_human_review_required": False,
            "physical_windows_acceptance_required": True,
            "quest_acceptance_required": True,
            "final_release_required": True,
            "production_ready": False,
            "production_activation": False,
            "final_audit": None,
            "legacy_bodyrig_revision": source_revision,
            "hfn_bodyrig_revision": None,
            "hfn_migration_active": False,
        }
    )
    return result


def _blocked(
    base: Mapping[str, Any],
    *,
    package_path: Path,
    package_sha: str,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    result = current._blocked_hfn_result(
        base,
        gates=list(base.get("gates") or []),
        package_path=package_path,
        package_sha=package_sha,
        gate_id=current.CANDIDATE_GATE,
        reason=reason,
    )
    result["legacy_bodyrig_revision"] = source_revision
    result["hfn_bodyrig_revision"] = None
    result["hfn_migration_active"] = False
    return result


def inspect_migrated_continuation(preview_job_id: str) -> dict[str, Any]:
    current._sync_legacy_seams()
    try:
        base = current._legacy.inspect_continuation(preview_job_id)
    except Exception as exc:
        raise HighFidelityHfnMigratedStatusError(str(exc)) from exc

    # The historical producer remains authoritative until anatomy/hair/eyes/
    # face-secondary are all complete. No migration can skip those gates.
    if base.get("high_fidelity_complete") is not True:
        return base

    try:
        job_id = current._legacy._job(preview_job_id)
        paths = current.continuation_paths(job_id)
        preview = current._legacy.preview_manager.get(job_id)
    except Exception as exc:
        raise HighFidelityHfnMigratedStatusError(str(exc)) from exc

    person_id = str(preview.get("person_id") or "").strip().lower()
    body_revision = str(preview.get("body_revision") or "").strip().lower()
    source_revision = str(preview.get("bodyrig_revision") or "").strip().lower()
    package_value = str(base.get("current_package_path") or "").strip()
    package_sha = str(base.get("current_package_sha256") or "").strip().lower()
    package_path = Path(package_value).expanduser().resolve() if package_value else paths["face_promotion"]

    if (
        not person_id
        or not body_revision
        or not current.GIT_RE.fullmatch(source_revision)
        or not package_value
        or not current.SHA_RE.fullmatch(package_sha)
        or not package_path.is_file()
        or current._sha256(package_path) != package_sha
    ):
        return _blocked(
            base,
            package_path=package_path,
            package_sha=package_sha,
            source_revision=source_revision,
            reason="legacy face-secondary completion lacks exact Person/revision/package authority for HFN migration",
        )

    try:
        migration = read_migration(
            preview_job_id,
            source_bodyrig_revision=source_revision,
            source_package_sha256=package_sha,
        )
    except HighFidelityHfnMigrationError as exc:
        return _blocked(
            base,
            package_path=package_path,
            package_sha=package_sha,
            source_revision=source_revision,
            reason=f"HFN migration authority is invalid: {exc}",
        )

    if migration is None:
        return _required_migration(
            base,
            preview_job_id=preview_job_id,
            package_path=package_path,
            package_sha=package_sha,
            source_revision=source_revision,
        )

    integration_revision = str(migration.get("integration_bodyrig_revision") or "").strip().lower()
    if not current.GIT_RE.fullmatch(integration_revision):
        return _blocked(
            base,
            package_path=package_path,
            package_sha=package_sha,
            source_revision=source_revision,
            reason="HFN migration integration revision is not canonical",
        )

    try:
        hfn = current.inspect_hfn_continuation(
            root=current.person_library(),
            person_id=person_id,
            body_revision=body_revision,
            bodyrig_revision=integration_revision,
            source_package_path=package_path,
            source_package_sha256=package_sha,
            render_dir=paths["hfn_render"],
            human_review_dir=paths["hfn_review"],
        )
    except Exception as exc:
        return _blocked(
            base,
            package_path=package_path,
            package_sha=package_sha,
            source_revision=source_revision,
            reason=f"current-integration HFN continuation failed: {exc}",
        )

    combined = list(base.get("gates") or [])
    for item in hfn.get("gates") or []:
        combined.append(
            current._gate(
                str(item.get("id") or ""),
                str(item.get("state") or "blocked"),
                reason=str(item.get("reason") or ""),
                evidence=dict(item.get("evidence") or {}),
            )
        )

    current_package = Path(hfn.get("package_path") or package_path).expanduser().resolve()
    current_sha = str(hfn.get("package_sha256") or package_sha).strip().lower()
    first_unpassed = next((item for item in hfn.get("gates") or [] if item.get("state") != "pass"), None)
    if first_unpassed is not None:
        gate_id = str(first_unpassed.get("id") or current.CANDIDATE_GATE)
        blocked = first_unpassed.get("state") in {"blocked", "invalid"}
        action = (hfn.get("actions") or {}).get(gate_id)
        if blocked or not isinstance(action, Mapping):
            action = {
                "gate": gate_id,
                "command": None,
                "operator_input_required": False,
                "reason": str(first_unpassed.get("reason") or "HFN continuation authority is unavailable"),
            }
        result = dict(base)
        result.update(
            {
                "state": "blocked" if blocked else "incomplete",
                "gates": combined,
                "next_gate": dict(action),
                "current_package_path": str(current_package),
                "current_package_sha256": current_sha,
                "high_fidelity_complete": False,
                "high_fidelity_human_review_required": False,
                "production_ready": False,
                "production_activation": False,
                "final_audit": None,
                "legacy_bodyrig_revision": source_revision,
                "hfn_bodyrig_revision": integration_revision,
                "hfn_migration_active": True,
                "hfn_migration_sha256": migration.get("sha256"),
            }
        )
        return result

    try:
        if not current_package.is_file() or current._sha256(current_package) != current_sha:
            raise current.HighFidelityPackageAuditError("HFN-reviewed candidate bytes changed before final audit")
        audit = current.audit_high_fidelity_package(current_package)
        if audit.get("package_sha256") != current_sha or current._sha256(current_package) != current_sha:
            raise current.HighFidelityPackageAuditError("HFN-reviewed candidate changed during final audit")
        components = dict(audit.get("components") or {})
        if not (
            audit.get("high_fidelity_ready") is True
            and components
            and all(value == "complete" for value in components.values())
        ):
            raise current.HighFidelityPackageAuditError("HFN-reviewed candidate is not component complete")
    except (OSError, current.HighFidelityPackageAuditError) as exc:
        return _blocked(
            base,
            package_path=current_package,
            package_sha=current_sha,
            source_revision=source_revision,
            reason=f"final migrated HFN candidate audit failed: {exc}",
        )

    result = dict(base)
    result.update(
        {
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
            "legacy_bodyrig_revision": source_revision,
            "hfn_bodyrig_revision": integration_revision,
            "hfn_migration_active": True,
            "hfn_migration_sha256": migration.get("sha256"),
        }
    )
    return result
