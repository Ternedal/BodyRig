from __future__ import annotations

from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, _validate_gate_a, inspect_acceptance_dir
from .high_fidelity_human_review import HighFidelityHumanReviewError
from .high_fidelity_physical_acceptance import (
    FORMAT,
    VERSION,
    RECEIPT_NAME,
    HighFidelityPhysicalAcceptanceError,
    _assert_release_compatible_gate_report,
    _hash,
    _json,
    _sha,
    _source_gate,
    human_review_path,
    physical_acceptance_dir,
    physical_acceptance_status,
    read_human_review,
)
from .high_fidelity_release_gate import HighFidelityReleaseGateError, validate_promoted_release_lineage
from .reference_acceptance_policy import apply_reference_policy


class HighFidelityPhysicalAcceptanceAuditError(RuntimeError):
    pass


def _invalid(base: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "state": "invalid",
        "gate": "physical-gate-a",
        "acceptance_dir": base.get("acceptance_dir"),
        "body_id": base.get("body_id"),
        "bodyrig_revision": base.get("bodyrig_revision"),
        "message": reason,
        "next_command": None,
        "production_activation": False,
    }


def _need_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise HighFidelityPhysicalAcceptanceAuditError(f"{label} no longer matches handoff authority")


def _need_file_hash(path: Path, expected: Any, label: str) -> str:
    canonical = _sha(expected, label)
    if not path.is_file():
        raise HighFidelityPhysicalAcceptanceAuditError(f"{label} is missing: {path}")
    actual = _hash(path)
    if actual != canonical:
        raise HighFidelityPhysicalAcceptanceAuditError(f"{label} bytes no longer match handoff authority")
    return actual


def audited_physical_acceptance_status(
    preview_job_id: str,
    *,
    package_path: str | Path,
    package_sha256: str,
) -> dict[str, Any]:
    """Return canonical physical status only after transitive high-fidelity authority validation.

    The existing physical acceptance state machine remains the sole Windows/Quest/release
    authority. This layer only fails closed if the high-fidelity handoff receipt, fresh
    Gate A extensions, fresh QA/runtime evidence, canonical reference-renderer policy,
    release invariants, or source-lineage bindings drift.
    """

    try:
        base = physical_acceptance_status(
            preview_job_id,
            package_path=package_path,
            package_sha256=package_sha256,
        )
    except (OSError, HighFidelityPhysicalAcceptanceError) as exc:
        return _invalid({}, str(exc))

    # Missing Gate A is a legitimate required state; pre-existing invalid state remains invalid.
    if base.get("gate") == "physical-gate-a" or base.get("state") == "invalid":
        return base

    acceptance = physical_acceptance_dir(preview_job_id)
    try:
        policy_status = apply_reference_policy(inspect_acceptance_dir(acceptance))
    except (OSError, AcceptanceStatusError) as exc:
        return _invalid(base, f"canonical reference-policy inspection failed: {exc}")
    if policy_status.state == "blocked":
        return _invalid(base, f"{policy_status.gate}: {policy_status.message}")

    try:
        expected_package = _sha(package_sha256, "continuation package SHA")
        receipt_path = acceptance / RECEIPT_NAME
        receipt = _json(receipt_path, "physical handoff receipt")
        if receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
            raise HighFidelityPhysicalAcceptanceAuditError("physical handoff receipt format/version is non-canonical")
        _need_equal(receipt.get("previewJobId"), preview_job_id, "receipt preview job")
        _need_equal(receipt.get("promotedPackageSha256"), expected_package, "receipt promoted package SHA")
        _need_equal(receipt.get("releaseLineageReproved"), True, "receipt release-lineage proof")
        _need_equal(receipt.get("physicalAcceptanceAuthority"), False, "receipt physical authority flag")
        _need_equal(receipt.get("productionActivation"), False, "receipt production activation flag")

        body_id = str(receipt.get("canonicalBodyId") or "")
        body_job_id = str(receipt.get("bodyJobId") or "")
        if not body_id or not body_job_id:
            raise HighFidelityPhysicalAcceptanceAuditError("physical handoff receipt lacks canonical body/job identity")

        receipt_sha = _hash(receipt_path)
        accepted = acceptance / f"{body_id}.mrbody"
        _need_file_hash(accepted, expected_package, "accepted promoted package")

        review_sha = _need_file_hash(
            human_review_path(accepted, package_sha256=expected_package),
            receipt.get("highFidelityHumanReviewSha256"),
            "package-bound high-fidelity human review",
        )
        read_human_review(accepted)

        session_sha = _need_file_hash(
            acceptance / "bodyrig-physical-clone-session.json",
            receipt.get("sourcePhysicalSessionSha256"),
            "physical source session",
        )
        readiness_sha = _need_file_hash(
            acceptance / "bodyrig-rig-readiness.json",
            receipt.get("sourceReadinessSha256"),
            "physical source readiness",
        )
        skin_sha = _need_file_hash(
            acceptance / "bodyrig-skin-qa.json",
            receipt.get("skinQaSha256"),
            "fresh skin QA",
        )
        topology_sha = _need_file_hash(
            acceptance / "bodyrig-mesh-topology-qa.json",
            receipt.get("meshTopologyQaSha256"),
            "fresh mesh-topology QA",
        )
        runtime_sha = _need_file_hash(
            acceptance / "runtime" / "runtime-manifest.json",
            receipt.get("runtimeManifestSha256"),
            "fresh runtime manifest",
        )

        gate_path = acceptance / "bodyrig-acceptance.json"
        gate = _validate_gate_a(gate_path)
        gate_report = _json(gate_path, "fresh promoted-package Gate A")
        _need_equal(gate.package_hash, expected_package, "Gate A promoted package SHA")
        _need_equal(gate.body_id, body_id, "Gate A body id")
        _need_equal(gate.revision, receipt.get("bodyrigRevision"), "Gate A BodyRig revision")
        _need_equal(gate.runtime_hash, runtime_sha, "Gate A runtime hash")
        _assert_release_compatible_gate_report(gate_report)

        physical = gate_report.get("physical_clone")
        skin = gate_report.get("skin_qa")
        topology = gate_report.get("mesh_topology_qa")
        runtime = gate_report.get("runtime")
        extension = gate_report.get("high_fidelity_handoff")
        if not all(isinstance(value, dict) for value in (physical, skin, topology, runtime, extension)):
            raise HighFidelityPhysicalAcceptanceAuditError("fresh Gate A lacks canonical high-fidelity authority sections")

        _need_equal(physical.get("session_sha256"), session_sha, "Gate A physical session hash")
        _need_equal(physical.get("readiness_sha256"), readiness_sha, "Gate A physical readiness hash")
        _need_equal(skin.get("report_sha256"), skin_sha, "Gate A skin QA hash")
        _need_equal(topology.get("report_sha256"), topology_sha, "Gate A topology QA hash")
        _need_equal(runtime.get("manifest_sha256"), runtime_sha, "Gate A runtime manifest hash")
        _need_equal(extension.get("receipt_sha256"), receipt_sha, "Gate A handoff receipt hash")
        _need_equal(extension.get("source_gate_a_sha256"), receipt.get("sourceGateASha256"), "Gate A source lineage hash")
        _need_equal(extension.get("package_sha256"), expected_package, "Gate A handoff package hash")
        _need_equal(extension.get("human_review_sha256"), review_sha, "Gate A human-review hash")
        _need_equal(extension.get("preview_job_id"), preview_job_id, "Gate A preview job")
        _need_equal(extension.get("body_job_id"), body_job_id, "Gate A body job")
        _need_equal(extension.get("release_lineage_reproved"), True, "Gate A release-lineage proof")

        preview, body_job, source_dir, source_gate, source_report = _source_gate(preview_job_id)
        _need_equal(str(body_job.get("job_id") or ""), body_job_id, "source body job")
        _need_equal(str(preview.get("canonical_body_id") or ""), body_id, "source preview body identity")
        _need_equal(source_gate.body_id, body_id, "source Gate A body identity")
        _need_equal(source_gate.revision, receipt.get("sourceGateABodyRigRevision"), "source Gate A BodyRig revision")
        _need_equal(source_gate.package_hash, receipt.get("sourcePackageSha256"), "source Gate A package hash")
        _need_equal(_hash(source_gate.path), receipt.get("sourceGateASha256"), "source Gate A bytes")

        source_physical = source_report.get("physical_clone")
        if not isinstance(source_physical, dict):
            raise HighFidelityPhysicalAcceptanceAuditError("source Gate A lacks physical lineage section")
        _need_equal(source_physical.get("session_sha256"), session_sha, "source Gate A physical session hash")
        _need_equal(source_physical.get("readiness_sha256"), readiness_sha, "source Gate A readiness hash")
        _need_file_hash(source_dir / "bodyrig-physical-clone-session.json", session_sha, "source physical session")
        _need_file_hash(source_dir / "bodyrig-rig-readiness.json", readiness_sha, "source physical readiness")

        release_lineage = validate_promoted_release_lineage(
            accepted,
            source_dir=source_dir,
            source_gate=source_gate,
            source_report=source_report,
        )
        _need_equal(receipt.get("sourceBodyprintSha256"), release_lineage["source_bodyprint_sha256"], "receipt source BodyPrint")
        _need_equal(receipt.get("promotedBodyprintSha256"), release_lineage["bodyprint_sha256"], "receipt promoted BodyPrint")
        _need_equal(gate_report.get("source_count"), release_lineage["source_count"], "Gate A source count")
        _need_equal(gate_report.get("recovery"), release_lineage["recovery"], "Gate A recovery authority")
        package_section = gate_report.get("package")
        if not isinstance(package_section, dict):
            raise HighFidelityPhysicalAcceptanceAuditError("Gate A package release section is missing")
        _need_equal(package_section.get("vrm_spec_version"), release_lineage["vrm_spec_version"], "Gate A VRM release version")
        _need_equal(extension.get("source_bodyprint_sha256"), release_lineage["source_bodyprint_sha256"], "Gate A source BodyPrint")
        _need_equal(extension.get("promoted_bodyprint_sha256"), release_lineage["bodyprint_sha256"], "Gate A promoted BodyPrint")
    except (
        OSError,
        AcceptanceStatusError,
        HighFidelityHumanReviewError,
        HighFidelityPhysicalAcceptanceError,
        HighFidelityPhysicalAcceptanceAuditError,
        HighFidelityReleaseGateError,
        ValueError,
    ) as exc:
        return _invalid(base, str(exc))

    return base
