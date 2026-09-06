from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profiled_first_physical_wrapper_preserves_doctor_and_rewrites_only_clone_command() -> None:
    source = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")

    assert 'prepare-first-physical-run.ps1' in source
    assert '& $doctor -PerformerId $PerformerId -BodyId $BodyId 6>&1' in source
    assert '$oldPrefix = ".\\clone-body-from-stash-ready.ps1 "' in source
    assert '$newPrefix = ".\\clone-body-from-stash-profiled-ready.ps1 "' in source
    assert ' + " -KeepPrivateWorkspace"' in source
    assert '$rewritten -ne 1' in source
    assert 'No physical evidence' not in source


def test_operator_router_uses_profiled_wrapper_only_for_performer_bound_preflight() -> None:
    source = (ROOT / "bodyrig-status.ps1").read_text(encoding="utf-8")

    assert '$firstPhysicalRun = Join-Path $repoRoot "prepare-first-physical-run.ps1"' in source
    assert '$profiledFirstPhysicalRun = Join-Path $repoRoot "prepare-profiled-first-physical-run.ps1"' in source
    assert 'Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun -Parameters $parameters' in source
    assert '$nextCommand = if ($clean) { "& \'" + $firstPhysicalRun.Replace("\'", "\'\'") + "\'" } else { $null }' in source


def test_profiled_launcher_binds_stash_metadata_and_retained_workspace_policy() -> None:
    source = (ROOT / "clone-body-from-stash-profiled-ready.ps1").read_text(encoding="utf-8")

    assert '-m", "bodyrig.stash_performer_profile"' in source
    assert '$env:BODYRIG_SITH_BODY_MODEL_GENDER = $resolvedGender' in source
    assert 'Stash performer gender metadata is missing/unavailable' in source
    assert 'Private workspace retention' in source
