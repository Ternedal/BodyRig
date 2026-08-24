from __future__ import annotations

import json
from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.acceptance_status_cli import _operator_command
from bodyrig.reference_acceptance_policy import _load_contract, apply_reference_policy


QUALITY_FIELDS = {
    "revision",
    "full_deformation_sequence_reviewed",
    "source_identity_texture_acceptable",
    "geometry_proportions_acceptable",
    "upper_body_deformation_acceptable",
    "lower_body_deformation_acceptable",
    "cross_limb_leakage_absent",
    "skin_qa_considered",
}


def _status(gate: str, acceptance_dir: str) -> AcceptanceStatus:
    return AcceptanceStatus(
        state="human-review" if "attestation" in gate else "ready",
        gate=gate,
        acceptance_dir=acceptance_dir,
        body_id="fixture-body",
        bodyrig_revision="a" * 40,
        message="fixture",
        next_command=None,
    )


def test_status_next_commands_require_explicit_quality_checklist() -> None:
    for gate in ("windows-attestation", "quest-attestation"):
        command = _operator_command(_status(gate, r"C:\acceptance")).next_command
        assert command is not None
        assert "record-reference-renderer-acceptance.ps1" in command
        assert "-ConfirmQualityChecklist" in command
        assert "-QualityNote" in command


def test_reference_policy_blocks_attestation_without_structured_quality_review(tmp_path: Path) -> None:
    contract = _load_contract()
    assert contract is not None
    attestation = {
        "renderer_name": contract["renderer_name"],
        "renderer_version": contract["renderer_version"],
        "unity_version": contract["unity_editor_version"],
        "deformation_sequence_revision": contract["deformation_sequence_revision"],
    }
    (tmp_path / "bodyrig-renderer-acceptance-windows.json").write_text(
        json.dumps(attestation) + "\n", encoding="utf-8"
    )

    blocked = apply_reference_policy(_status("quest-probe", str(tmp_path)))
    assert blocked.state == "blocked"
    assert blocked.gate == "reference-contract"
    assert blocked.next_command is None
    assert "structured quality_review" in blocked.message


def test_reference_policy_blocks_false_quality_review_field(tmp_path: Path) -> None:
    contract = _load_contract()
    assert contract is not None
    review = {
        "revision": "bodyrig-human-quality-v1",
        "full_deformation_sequence_reviewed": True,
        "source_identity_texture_acceptable": True,
        "geometry_proportions_acceptable": True,
        "upper_body_deformation_acceptable": True,
        "lower_body_deformation_acceptable": True,
        "cross_limb_leakage_absent": False,
        "skin_qa_considered": True,
    }
    assert set(review) == QUALITY_FIELDS
    attestation = {
        "renderer_name": contract["renderer_name"],
        "renderer_version": contract["renderer_version"],
        "unity_version": contract["unity_editor_version"],
        "deformation_sequence_revision": contract["deformation_sequence_revision"],
        "quality_review": review,
    }
    (tmp_path / "bodyrig-renderer-acceptance-windows.json").write_text(
        json.dumps(attestation) + "\n", encoding="utf-8"
    )

    blocked = apply_reference_policy(_status("quest-probe", str(tmp_path)))
    assert blocked.state == "blocked"
    assert "cross_limb_leakage_absent" in blocked.message


def test_reference_release_script_checks_quality_before_core_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "complete-reference-acceptance.ps1").read_text(encoding="utf-8")
    quality = source.index("Assert-QualityReview -Attestation $attestation")
    core = source.index("& $core @args")
    assert quality < core
    assert '"bodyrig-human-quality-v1"' in source
