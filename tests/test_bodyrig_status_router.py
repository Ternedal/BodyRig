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
    assert '"prepare-profiled-first-physical-run.ps1"' in source
    assert '"photoreal-v2-status.ps1"' in source
    assert '"photoreal-digital-twin-status.ps1"' in source
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
        "$hasPerformer",
        "$hasBodyId",
        "$hasPhotorealP0",
        "$hasPhotorealCompanion",
        "$hasPhotorealPersonBinding",
        "$hasPhotorealP3PhysicalReview",
        "$hasPhotorealDigitalTwin",
    ):
        assert selector in source
    assert "-CompositionAuthorityDir requires -AcceptanceDir" in source
    assert "High-fidelity preview mode cannot be combined" in source
    assert "Physical session mode accepts only -SessionReport" in source
    assert "Physical acceptance mode accepts only -AcceptanceDir" in source
    assert "Physical preflight requires -PerformerId and -BodyId together" in source
    assert "Physical preflight mode cannot be combined" in source


def test_router_routes_performer_bound_preflight_to_profiled_canonical_doctor() -> None:
    source = _source()
    assert "[string]$PerformerId" in source
    assert "[string]$BodyId" in source
    assert "^[a-z0-9æøå_-]{1,160}$" in source
    assert "$hasPerformer -xor $hasBodyId" in source
    assert "PerformerId = $PerformerId" in source
    assert "BodyId = $BodyId" in source
    assert "Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun -Parameters $parameters" in source
    assert "Physical preflight performer mode does not support -Json" in source


def test_router_routes_photoreal_v2_through_canonical_status_wrapper() -> None:
    source = _source()
    assert "[string]$PhotorealP0Root" in source
    assert "[string]$PhotorealTeacherWorkRoot" in source
    assert "[string]$PhotorealAssetRoot" in source
    assert "[string]$PhotorealReferenceModelRoot" in source
    assert "[string]$PhotorealP3TargetProfile" in source
    assert "$hasPhotorealCompanion -and -not $hasPhotorealP0" in source
    assert "-PhotorealP0Root is required when any other Photoreal V2 option is supplied." in source
    assert "Photoreal V2 mode cannot be combined with physical" in source
    assert "$parameters = @{ P0Root = $PhotorealP0Root }" in source
    assert "$parameters.TeacherWorkRoot = $PhotorealTeacherWorkRoot" in source
    assert "$parameters.P2MotionConfig = $PhotorealP2MotionConfig" in source
    assert "$parameters.SingleMotionDriverSourceRef = $PhotorealSingleMotionDriverSourceRef" in source
    assert "$parameters.P3MachineProbe = $PhotorealP3MachineProbe" in source
    assert "Invoke-CanonicalStatus -Script $photorealStatus -Parameters $parameters" in source


def test_router_routes_photoreal_post_p3_digital_twin_status() -> None:
    source = _source()
    assert "[string]$PhotorealPersonBinding" in source
    assert "[string]$PhotorealP3PhysicalReview" in source
    assert "$hasPhotorealPersonBinding -xor $hasPhotorealP3PhysicalReview" in source
    assert "Photoreal digital-twin mode requires -PhotorealPersonBinding and -PhotorealP3PhysicalReview together." in source
    assert "$hasPhotorealDigitalTwin -and ($hasPhotorealP0 -or $hasPhotorealCompanion)" in source
    assert "Photoreal digital-twin mode cannot be combined with Photoreal P0-to-P3 status inputs." in source
    assert "Photoreal digital-twin mode requires -CompositionAuthorityDir and -AcceptanceDir." in source
    assert "$parameters = @{" in source
    assert "PhotorealPersonBinding = $PhotorealPersonBinding" in source
    assert "P3PhysicalReview = $PhotorealP3PhysicalReview" in source
    assert "$parameters.LibraryRoot = $LibraryRoot" in source
    assert "Invoke-CanonicalStatus -Script $photorealDigitalTwinStatus -Parameters $parameters" in source


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
