from __future__ import annotations

import json
from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.reference_acceptance_policy import apply_reference_policy, reference_policy_violation


def _complete_status(tmp_path: Path) -> AcceptanceStatus:
    return AcceptanceStatus(
        state="complete",
        gate="release",
        acceptance_dir=str(tmp_path),
        body_id="body-1",
        bodyrig_revision="a" * 40,
        message="historical release remains readable",
        next_command=None,
    )


def _quality_review() -> dict[str, object]:
    return {
        "revision": "bodyrig-human-quality-v1",
        "full_deformation_sequence_reviewed": True,
        "source_identity_texture_acceptable": True,
        "geometry_proportions_acceptable": True,
        "upper_body_deformation_acceptable": True,
        "lower_body_deformation_acceptable": True,
        "cross_limb_leakage_absent": True,
        "skin_qa_considered": True,
    }


def test_historical_complete_status_keeps_v1_compatibility_but_strict_helper_detects_legacy_layout(tmp_path: Path) -> None:
    (tmp_path / "windows-probe.json").write_text("{}\n", encoding="utf-8")
    status = _complete_status(tmp_path)

    assert apply_reference_policy(status) == status
    violation = reference_policy_violation(tmp_path)
    assert violation is not None
    gate, message = violation
    assert gate == "reference-layout"
    assert "Legacy root renderer evidence" in message


def test_historical_complete_status_stays_readable_but_strict_helper_rejects_placeholder_human_note(tmp_path: Path) -> None:
    attestation = {
        "attestation": "operator-supplied",
        "renderer_name": "BodyRig Reference Renderer",
        "renderer_version": "reference-v1/univrm-0.131.2",
        "unity_version": "6000.3.13f1",
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "quality_review": _quality_review(),
        "quality_note": "<your physical review>",
    }
    (tmp_path / "bodyrig-renderer-acceptance-windows.json").write_text(
        json.dumps(attestation),
        encoding="utf-8",
    )
    status = _complete_status(tmp_path)

    assert apply_reference_policy(status) == status
    violation = reference_policy_violation(tmp_path)
    assert violation is not None
    gate, message = violation
    assert gate == "reference-contract"
    assert "quality note is still a generated placeholder" in message


def test_historical_complete_status_stays_readable_but_strict_helper_requires_operator_attestation_provenance(tmp_path: Path) -> None:
    attestation = {
        "attestation": "synthetic",
        "renderer_name": "BodyRig Reference Renderer",
        "renderer_version": "reference-v1/univrm-0.131.2",
        "unity_version": "6000.3.13f1",
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "quality_review": _quality_review(),
        "quality_note": "Reviewed physically on the target device.",
    }
    (tmp_path / "bodyrig-renderer-acceptance-windows.json").write_text(
        json.dumps(attestation),
        encoding="utf-8",
    )
    status = _complete_status(tmp_path)

    assert apply_reference_policy(status) == status
    violation = reference_policy_violation(tmp_path)
    assert violation is not None
    gate, message = violation
    assert gate == "reference-contract"
    assert "attestation provenance is not operator-supplied" in message


def test_high_fidelity_audit_calls_strict_reference_policy_after_generic_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "bodyrig" / "high_fidelity_physical_acceptance_audit.py").read_text(encoding="utf-8")

    generic = source.index("policy_status = apply_reference_policy(generic_status)")
    strict = source.index("violation = reference_policy_violation(acceptance)")
    transitive = source.index('expected_package = _sha(package_sha256, "continuation package SHA")')
    assert generic < strict < transitive
    assert "including after release" in source
