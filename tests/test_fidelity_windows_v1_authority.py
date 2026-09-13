from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-fidelity-windows-render-probe.ps1").read_text(encoding="utf-8")


def test_fidelity_renderer_uses_bool_safe_numeric_v1_guard() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT


def test_persisted_v1_authorities_use_the_bool_safe_guard() -> None:
    for authority in (
        "$acceptance.version",
        "$reviewAuthority.version",
        "$runtime.version",
        "$probe.version",
        "$deformation.version",
        "$hairDeformation.version",
        "$manifest.version",
    ):
        assert f"Test-V1Version {authority}" in SCRIPT, authority

    for legacy_cast in (
        "[int]$acceptance.version",
        "[int]$reviewAuthority.version",
        "[int]$runtime.version",
        "[int]$probe.version",
        "[int]$deformation.version",
        "[int]$hairDeformation.version",
        "[int]$manifest.version",
    ):
        assert legacy_cast not in SCRIPT, legacy_cast


def test_renderer_contract_uses_repository_wide_bool_safe_v1_seam() -> None:
    assert "$contractVersion = $contract.version" in SCRIPT
    assert "$null -eq $contractVersion" in SCRIPT
    assert "$contractVersion -is [bool]" in SCRIPT
    assert "$contractVersion -isnot [ValueType]" in SCRIPT
    assert "[decimal]$contractVersion -ne [decimal]1" in SCRIPT
    assert "[int]$contract.version" not in SCRIPT


def test_machine_and_deformation_probe_v1_are_checked_before_comparison_authority() -> None:
    probe_read = SCRIPT.index('$probe = Read-Json $probePath "Fidelity renderer machine probe"')
    probe_version = SCRIPT.index("Test-V1Version $probe.version", probe_read)
    deformation_version = SCRIPT.index("Test-V1Version $deformation.version", probe_read)
    comparison_write = SCRIPT.index('$comparison = [ordered]@{', probe_read)

    assert probe_read < probe_version < comparison_write
    assert probe_read < deformation_version < comparison_write
    assert '[string]$probe.format -ne "bodyrig-renderer-probe"' in SCRIPT[probe_read:comparison_write]
    assert '[string]$deformation.format -ne "bodyrig-deformation-probe"' in SCRIPT[probe_read:comparison_write]
    assert '[string]$deformation.platform -ne "windows-unity-univrm"' in SCRIPT[probe_read:comparison_write]


def test_comparison_output_remains_review_only_and_non_activating() -> None:
    comparison = SCRIPT[SCRIPT.index('$comparison = [ordered]@{'):]
    assert "physical_acceptance_authority = $usingAcceptance" in comparison
    assert "comparison_only = $true" in comparison
    assert "production_activation = $false" in comparison
    assert "no renderer/human/release acceptance was written" in comparison
