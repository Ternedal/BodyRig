from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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


def test_renderer_attestation_requires_and_hash_binds_deformation_probe() -> None:
    source = (ROOT / "record-renderer-acceptance.ps1").read_text(encoding="utf-8")
    assert '[Parameter(Mandatory = $true)][string]$DeformationReport' in source
    assert 'Read-JsonFile $DeformationReport "Deformation machine probe"' in source
    assert '$deformationHash = Sha256 $DeformationReport' in source
    assert 'deformation_report_sha256=$deformationHash' in source
    assert 'deformation_sequence_revision=[string]$deformation.sequence_revision' in source
    assert 'deformation_probe=$true' in source
    assert 'same physical build/device as renderer probe' in source


def test_renderer_attestation_requires_structured_human_quality_confirmation() -> None:
    source = (ROOT / "record-renderer-acceptance.ps1").read_text(encoding="utf-8")
    assert '[Parameter(Mandatory = $true)][switch]$ConfirmQualityChecklist' in source
    assert 'if (-not $ConfirmQualityChecklist)' in source
    assert 'revision = "bodyrig-human-quality-v1"' in source
    for field in QUALITY_FIELDS - {"revision"}:
        assert f"{field} = $true" in source
    assert "quality_review=$qualityReview" in source


def test_renderer_attestation_schema_requires_direct_deformation_and_quality_binding() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "bodyrig-renderer-acceptance-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    required = set(schema["required"])
    assert {
        "deformation_report_sha256",
        "deformation_sequence_revision",
        "deformation_probe",
        "quality_review",
    } <= required
    props = schema["properties"]
    assert props["deformation_report_sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert props["deformation_sequence_revision"]["const"] == "humanoid-muscle-sweep-v1"
    assert props["deformation_probe"]["const"] is True
    review = props["quality_review"]
    assert review["additionalProperties"] is False
    assert set(review["required"]) == QUALITY_FIELDS
    assert review["properties"]["revision"]["const"] == "bodyrig-human-quality-v1"
    for field in QUALITY_FIELDS - {"revision"}:
        assert review["properties"][field]["const"] is True


def test_reference_release_rechecks_structured_quality_before_core_release() -> None:
    source = (ROOT / "complete-reference-acceptance.ps1").read_text(encoding="utf-8")
    assert "function Assert-QualityReview" in source
    quality_check = source.index("Assert-QualityReview -Attestation $attestation")
    core_call = source.index("& $core @args")
    assert quality_check < core_call
    assert '"bodyrig-human-quality-v1"' in source
    for field in QUALITY_FIELDS - {"revision"}:
        assert field in source


def test_final_release_core_still_rechecks_attestation_against_exact_deformation_file() -> None:
    source = (ROOT / "complete-acceptance.ps1").read_text(encoding="utf-8")
    assert "function Read-Att([string]$Path,[string]$Platform,$Probe,$Deformation)" in source
    assert "'att deformation'" in source
    assert "-ne$Deformation.Hash" in source
    assert "deformation_sequence_revision-ne[string]$Deformation.Value.sequence_revision" in source
    assert "$v.deformation_probe-ne$true" in source
    assert "Read-Att $WindowsRendererReport 'windows-unity-univrm' $wp $wd" in source
    assert "Read-Att $QuestRendererReport 'android-quest-class' $qp $qd" in source
