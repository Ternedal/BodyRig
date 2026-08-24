from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_renderer_attestation_requires_and_hash_binds_deformation_probe() -> None:
    source = (ROOT / "record-renderer-acceptance.ps1").read_text(encoding="utf-8")
    assert '[Parameter(Mandatory = $true)][string]$DeformationReport' in source
    assert 'Read-JsonFile $DeformationReport "Deformation machine probe"' in source
    assert '$deformationHash = Sha256 $DeformationReport' in source
    assert 'deformation_report_sha256=$deformationHash' in source
    assert 'deformation_sequence_revision=[string]$deformation.sequence_revision' in source
    assert 'deformation_probe=$true' in source
    assert 'same physical build/device as renderer probe' in source


def test_renderer_attestation_schema_requires_direct_deformation_binding() -> None:
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
    } <= required
    props = schema["properties"]
    assert props["deformation_report_sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert props["deformation_sequence_revision"]["const"] == "humanoid-muscle-sweep-v1"
    assert props["deformation_probe"]["const"] is True


def test_final_release_rechecks_attestation_against_exact_deformation_file() -> None:
    source = (ROOT / "complete-acceptance.ps1").read_text(encoding="utf-8")
    assert "function Read-Att([string]$Path,[string]$Platform,$Probe,$Deformation)" in source
    assert "'att deformation'" in source
    assert "-ne$Deformation.Hash" in source
    assert "deformation_sequence_revision-ne[string]$Deformation.Value.sequence_revision" in source
    assert "$v.deformation_probe-ne$true" in source
    assert "Read-Att $WindowsRendererReport 'windows-unity-univrm' $wp $wd" in source
    assert "Read-Att $QuestRendererReport 'android-quest-class' $qp $qd" in source
