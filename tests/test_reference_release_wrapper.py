from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_reference_release_wrapper_validates_contract_before_core_gate() -> None:
    source = (REPO / "complete-reference-acceptance.ps1").read_text(encoding="utf-8")

    assert "reference-renderer\\renderer-contract.json" in source
    assert '"bodyrig-reference-renderer-contract"' in source
    assert "univrm_version" in source
    assert "univrm_revision" in source
    assert "Reference renderer contract fields are not canonical." in source
    assert "Reference renderer contract contains an invalid UniVRM revision." in source
    assert '"windows-evidence\\windows-probe.json"' in source
    assert '"windows-evidence\\windows-deformation-probe.json"' in source
    assert '"quest-evidence\\quest-probe.json"' in source
    assert '"quest-evidence\\quest-deformation-probe.json"' in source
    assert "Canonical reference release refuses legacy root renderer evidence" in source

    renderer_check = source.index("$probe.active_renderer.name")
    attestation_check = source.index("$attestation.renderer_name")
    unity_check = source.index("$probe.unity_version")
    sequence_check = source.index("$deformation.sequence_revision")
    quality_check = source.index("Assert-QualityReview -Attestation $attestation")
    core_call = source.index('& $core @args')

    assert renderer_check < core_call
    assert attestation_check < core_call
    assert unity_check < core_call
    assert sequence_check < core_call
    assert quality_check < core_call
    assert '$probe.active_renderer.version -ne [string]$contract.renderer_version' in source
    assert '$attestation.renderer_version -ne [string]$contract.renderer_version' in source
    assert '$probe.unity_version -ne [string]$contract.unity_editor_version' in source
    assert '$deformation.unity_version -ne [string]$contract.unity_editor_version' in source
    assert '$attestation.unity_version -ne [string]$contract.unity_editor_version' in source
    assert '$attestation.deformation_sequence_revision -ne [string]$contract.deformation_sequence_revision' in source
    assert '"bodyrig-human-quality-v1"' in source
    assert "cross_limb_leakage_absent" in source
    assert "skin_qa_considered" in source


def test_reference_release_wrapper_delegates_full_byte_binding_to_core_gate() -> None:
    source = (REPO / "complete-reference-acceptance.ps1").read_text(encoding="utf-8")
    assert '"complete-acceptance.ps1"' in source
    for binding in (
        "AcceptanceReport = $acceptanceReport",
        "WindowsRendererReport = $windowsAttestation",
        "WindowsProbeReport = $windowsProbe",
        "WindowsDeformationReport = $windowsDeformation",
        "QuestRendererReport = $questAttestation",
        "QuestProbeReport = $questProbe",
        "QuestDeformationReport = $questDeformation",
    ):
        assert binding in source
