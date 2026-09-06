from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "bodyrig-status.ps1").read_text(encoding="utf-8")


def test_router_delegates_to_existing_canonical_status_wrappers() -> None:
    source = _source()
    assert '"physical-acceptance-status.ps1"' in source
    assert '"high-fidelity-physical-status.ps1"' in source
    assert '"digital-twin-status.ps1"' in source
    assert '"prepare-first-physical-run.ps1"' in source
    assert "Invoke-CanonicalStatus" in source
    assert "[hashtable]$Parameters" in source
    assert "& $Script @Parameters" in source


def test_router_has_explicit_non_ambiguous_stage_selectors() -> None:
    source = _source()
    for selector in (
        "$hasSession",
        "$hasAcceptance",
        "$hasPreview",
        "$hasComposition",
        "$hasLibrary",
        "$hasSerial",
    ):
        assert selector in source
    assert "-CompositionAuthorityDir requires -AcceptanceDir" in source
    assert "High-fidelity preview mode cannot be combined" in source
    assert "Physical session mode accepts only -SessionReport" in source
    assert "Physical acceptance mode accepts only -AcceptanceDir" in source


def test_router_preserves_stage_specific_operator_inputs() -> None:
    source = _source()
    assert "$parameters.LibraryRoot = $LibraryRoot" in source
    assert "$parameters.Serial = $Serial" in source
    assert "$parameters.Json = $true" in source


def test_router_no_selector_is_read_only_preflight_handoff() -> None:
    source = _source()
    assert 'format = "bodyrig-operator-status-router"' in source
    assert 'stage = "physical-preflight"' in source
    assert "read_only = $true" in source
    assert "$firstPhysicalRun.Replace" in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert "git -C $repoRoot status --porcelain" in source
    assert 'state = $(if ($clean) { "required" } else { "blocked" })' in source
    assert "$nextCommand = if ($clean)" in source


def test_router_itself_never_mutates_evidence() -> None:
    source = _source()
    for mutation in (
        "Set-Content",
        "Out-File",
        "New-Item",
        "Move-Item",
        "Remove-Item",
        "Copy-Item",
        "Add-Content",
    ):
        assert mutation not in source
