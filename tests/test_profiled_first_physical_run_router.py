from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profiled_first_physical_wrapper_preserves_doctor_and_rewrites_only_clone_command() -> None:
    source = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")

    assert 'prepare-first-physical-run.ps1' in source
    assert '"-File", $doctor' in source
    assert '"-PerformerId", $PerformerId' in source
    assert '"-BodyId", $BodyId' in source
    assert '$oldPrefix = ".\\clone-body-from-stash-ready.ps1 "' in source
    assert '$newPrefix = ".\\clone-body-from-stash-profiled-ready.ps1 "' in source
    assert ' + " -KeepPrivateWorkspace"' in source
    assert '$rewritten -ne 1' in source
    assert 'No physical evidence' not in source


def test_profiled_first_physical_wrapper_isolates_exit_based_doctor_in_child_pwsh() -> None:
    source = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")

    assert '$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue' in source
    assert 'function Invoke-CanonicalDoctorProcess' in source
    assert '$output = @(& $pwsh.Source @doctorArgs 2>&1)' in source
    assert '$exitCode = $LASTEXITCODE' in source
    assert 'Run it in an isolated pwsh process' in source
    assert '& $doctor -PerformerId $PerformerId -BodyId $BodyId' not in source


def test_profiled_first_physical_wrapper_scopes_stash_path_map_before_doctor() -> None:
    source = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")

    configure = source.index('$pathMapConfig = Join-Path $repoRoot "configure-stash-path-map.ps1"')
    initial_map = source.index('& $pathMapConfig -PerformerId $PerformerId')
    doctor = source.index('$attempt = Invoke-CanonicalDoctorProcess')
    assert configure < initial_map < doctor


def test_profiled_first_physical_wrapper_retries_only_selected_source_map_failures_once() -> None:
    source = (ROOT / "prepare-profiled-first-physical-run.ps1").read_text(encoding="utf-8")

    assert 'Selected Stash performer/source decode probe failed' in source
    assert 'Selected Stash performer/source decode probe did not prove at least one decodable local video' in source
    assert '$sourceMapRetryEligible' in source
    assert '& $pathMapConfig -PerformerId $PerformerId -ForceRefresh' in source
    assert 'forcing one performer-scoped Stash path-map refresh before retry' in source
    assert source.count('Invoke-CanonicalDoctorProcess') == 3  # definition + first attempt + one retry
    assert source.count('-ForceRefresh') == 1
    assert 'BodyRig live readiness failed' not in source
    assert 'BodyRig reference-renderer toolchain readiness failed' not in source


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
