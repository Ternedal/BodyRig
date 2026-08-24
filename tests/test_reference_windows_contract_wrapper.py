from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_reference_windows_wrapper_contract_binds_before_canonical_commit() -> None:
    source = (REPO / "run-reference-windows-renderer-probe.ps1").read_text(encoding="utf-8")

    assert "reference-renderer\\renderer-contract.json" in source
    assert '"bodyrig-reference-renderer-contract"' in source
    assert '"run-windows-renderer-probe.ps1"' in source
    assert '".bodyrig-windows-contract-stage-"' in source
    assert '"windows-evidence"' in source
    assert "ProbeOutput = $stagedProbe" in source
    assert "DeformationOutput = $stagedDeformation" in source

    identity_check = source.index("active_renderer.name")
    unity_probe_check = source.index("$probe.unity_version")
    unity_deformation_check = source.index("$deformation.unity_version")
    sequence_check = source.index("$deformation.sequence_revision")
    commit = source.index("Move-Item -LiteralPath $stageDir -Destination $canonicalDir")

    assert identity_check < commit
    assert unity_probe_check < commit
    assert unity_deformation_check < commit
    assert sequence_check < commit
    assert '$probe.active_renderer.version -ne [string]$contract.renderer_version' in source
    assert '$probe.unity_version -ne [string]$contract.unity_editor_version' in source
    assert '$deformation.unity_version -ne [string]$contract.unity_editor_version' in source
    assert '$deformation.sequence_revision -ne [string]$contract.deformation_sequence_revision' in source
    assert '$probe.bodyrig_revision -ne [string]$deformation.bodyrig_revision' in source
    assert '$probe.build_guid -ne [string]$deformation.build_guid' in source
    assert '$committed = $false' in source
    assert '$committed = $true' in source
    assert 'if (-not $committed -and (Test-Path -LiteralPath $stageDir -PathType Container))' in source
    assert 'Remove-Item -LiteralPath $stageDir -Recurse -Force' in source


def test_reference_windows_wrapper_does_not_expose_renderer_identity_inputs() -> None:
    source = (REPO / "run-reference-windows-renderer-probe.ps1").read_text(encoding="utf-8")
    params = source.split(")\n\n$ErrorActionPreference", 1)[0]
    assert "$RendererName" not in params
    assert "$RendererVersion" not in params


def test_reference_windows_wrapper_is_only_canonical_docs_entrypoint() -> None:
    for path in (REPO / "README.md", REPO / "docs" / "RIG_ACCEPTANCE.md"):
        text = path.read_text(encoding="utf-8")
        assert ".\\run-reference-windows-renderer-probe.ps1" in text
        assert ".\\run-windows-renderer-probe.ps1 `" not in text
