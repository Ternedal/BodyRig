from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(encoding="utf-8")


def test_update_defaults_normal_authority_to_main() -> None:
    assert '[string]$Branch = "main"' in SCRIPT
    assert '[string]$Revision = ""' in SCRIPT
    assert "agent/person-studio-photoreal-20260902" not in SCRIPT


def test_update_never_reuses_powershell_pid_constant_as_loop_variable() -> None:
    assert "foreach ($pid " not in SCRIPT.lower()
    assert "foreach ($ownerprocessid in $listenerpids)" in SCRIPT.lower()


def test_update_preserves_listener_results_as_arrays_under_strict_mode() -> None:
    assert "$listenerPids = @(Get-BodyRigListeners)" in SCRIPT
    assert "$remainingListenerPids = @(Get-BodyRigListeners)" in SCRIPT
    assert "if ($listenerPids.Count -eq 0)" in SCRIPT
    assert "if ($remainingListenerPids.Count -eq 0)" in SCRIPT
    assert "if ((Get-BodyRigListeners).Count -eq 0)" not in SCRIPT


def test_update_verifies_service_before_stopping_listener() -> None:
    assert '[string]$health.service -ne "bodyrig"' in SCRIPT
    assert "Refuserer at stoppe en ukendt proces" in SCRIPT
    assert "Stop-Process -Id ([int]$ownerProcessId)" in SCRIPT


def test_update_fetches_target_branch_explicitly_before_checkout() -> None:
    assert '$sourceRef = "refs/heads/$Branch"' in SCRIPT
    assert '$remoteRef = "refs/remotes/$Remote/$Branch"' in SCRIPT
    assert '& git fetch $Remote "$sourceRef`:$remoteRef"' in SCRIPT
    assert '& git checkout --detach $target' in SCRIPT


def test_exact_historical_revision_must_be_reachable_from_fetched_branch() -> None:
    assert "[ValidatePattern('^$|^[0-9a-fA-F]{40}$')]" in SCRIPT
    assert '& git cat-file -e "$requested^{commit}"' in SCRIPT
    assert '& git fetch --no-tags $Remote $requested' in SCRIPT
    assert '& git merge-base --is-ancestor $requested $branchTarget' in SCRIPT
    assert "Refuserer historisk evidence-checkout" in SCRIPT
    assert '$targetMode = "historical-revision"' in SCRIPT


def test_historical_target_is_preflighted_before_service_stop() -> None:
    required = SCRIPT.index("$requiredTargetFiles = @(")
    preflight = SCRIPT.index('& git cat-file -e "$target`:$relativePath"')
    stop_call = SCRIPT.index("\nStop-VerifiedBodyRigService\n")
    checkout = SCRIPT.index("& git checkout --detach $target")
    assert required < preflight < stop_call < checkout
    assert '"requirements/windows-python.lock.txt"' in SCRIPT
    assert '"bodyrig/runtime_lock.py"' in SCRIPT
    assert '"start-windows.ps1"' in SCRIPT
    assert '"physical-acceptance-status.ps1"' in SCRIPT


def test_update_installs_only_after_old_service_has_been_stopped() -> None:
    stop_index = SCRIPT.index("\nStop-VerifiedBodyRigService\n")
    install_index = SCRIPT.index(' -m pip install --disable-pip-version-check -c $runtimeLock -e ".[test]"')
    assert stop_index < install_index


def test_update_installs_and_verifies_exact_windows_runtime_lock() -> None:
    lock_index = SCRIPT.index('Join-Path $RepoRoot "requirements\\windows-python.lock.txt"')
    install_index = SCRIPT.index(' -m pip install --disable-pip-version-check -c $runtimeLock -e ".[test]"')
    verify_index = SCRIPT.index(' -m bodyrig.runtime_lock --lock $runtimeLock')
    configure_index = SCRIPT.index('Join-Path $RepoRoot "configure-stash-path-map.ps1"')
    assert lock_index < install_index < verify_index < configure_index


def test_update_auto_configures_verified_stash_paths_before_launch() -> None:
    configure_index = SCRIPT.index('Join-Path $RepoRoot "configure-stash-path-map.ps1"')
    start_index = SCRIPT.index('Join-Path $RepoRoot "start-windows.ps1"')
    assert '& $stashPathConfig' in SCRIPT
    assert configure_index < start_index


def test_update_probes_latest_failed_recovery_read_only_without_blocking_launch() -> None:
    probe_index = SCRIPT.index('Join-Path $RepoRoot "diagnose-failed-body-build.ps1"')
    start_index = SCRIPT.index('Join-Path $RepoRoot "start-windows.ps1"')
    assert '& $rescueProbe -RepoRoot $RepoRoot' in SCRIPT
    assert 'Write-Warning "Recovery rescue probe' in SCRIPT
    assert 'Update fortsætter' in SCRIPT
    assert probe_index < start_index


def test_update_can_bootstrap_from_temp_against_explicit_repo_root() -> None:
    assert '[string]$RepoRoot = ""' in SCRIPT
    assert '$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)' in SCRIPT
    assert 'Join-Path $RepoRoot ".git"' in SCRIPT
    assert 'Join-Path $RepoRoot ".venv\\Scripts\\python.exe"' in SCRIPT
    assert 'Join-Path $RepoRoot "start-windows.ps1"' in SCRIPT


def test_update_verifies_running_revision_after_restart() -> None:
    assert '[string]$state.revision -ne $target' in SCRIPT
    assert 'Write-Host "BodyRig update: READY"' in SCRIPT
    assert 'Write-Host "Authority mode: $targetMode"' in SCRIPT
    assert 'Write-Host "Branch authority: $Remote/$Branch @ $branchTarget"' in SCRIPT


def test_update_accepts_explicit_planner_scope_and_rejects_partial_source_scope_early() -> None:
    assert '[string]$PreferredJobId = ""' in SCRIPT
    assert '[string]$PersonId = ""' in SCRIPT
    assert '[string]$PerformerId = ""' in SCRIPT
    assert '[string]$BodyId = ""' in SCRIPT
    validation = SCRIPT.index("$hasPerformer -xor $hasBodyId")
    dirty_check = SCRIPT.index("$dirtyBefore = @(& git status --porcelain)")
    assert validation < dirty_check
    assert 'throw "Pass -PerformerId and -BodyId together, or omit both."' in SCRIPT


def test_normal_update_runs_read_only_planner_only_after_service_authority_is_verified() -> None:
    health_verify = SCRIPT.rindex('if (-not $health -or $health.ok -ne $true -or [string]$health.service -ne "bodyrig")')
    ready = SCRIPT.index('Write-Host "BodyRig update: READY"')
    planner = SCRIPT.index('$planner = Join-Path $RepoRoot "plan-rig-window.ps1"')
    assert health_verify < ready < planner
    assert 'Get-Command pwsh -ErrorAction SilentlyContinue' in SCRIPT
    assert '"-File", $planner' in SCRIPT
    assert '& $pwsh.Source @plannerArgs' in SCRIPT
    assert 'BodyRig rig-window auto-plan (read-only)' in SCRIPT


def test_auto_plan_forwards_person_performer_body_and_preferred_job_scope() -> None:
    assert '$plannerArgs += @("-PreferredJobId", $PreferredJobId)' in SCRIPT
    assert '$plannerArgs += @("-PersonId", $PersonId)' in SCRIPT
    assert '$plannerArgs += @("-PerformerId", $PerformerId, "-BodyId", $BodyId)' in SCRIPT


def test_planner_failure_does_not_reclassify_successful_update_as_failed() -> None:
    assert '$plannerExit = $LASTEXITCODE' in SCRIPT
    assert 'if ($plannerExit -ne 0)' in SCRIPT
    assert 'BodyRig update er READY, men rig-window auto-plan kunne ikke resolve en sikker næste handling' in SCRIPT
    assert 'throw "BodyRig update er READY' not in SCRIPT


def test_historical_revision_skips_auto_plan_and_preserves_revision_bound_status_flow() -> None:
    historical = SCRIPT.index('if ($targetMode -eq "historical-revision")')
    skip = SCRIPT.index('} elseif ($SkipPlan) {', historical)
    planner = SCRIPT.index('$planner = Join-Path $RepoRoot "plan-rig-window.ps1"', skip)
    assert historical < skip < planner
    assert "Auto-planning is skipped in historical-revision mode" in SCRIPT
    assert "physical-acceptance-status command that selected this checkout" in SCRIPT


def test_operator_can_skip_auto_plan_explicitly() -> None:
    assert '[switch]$SkipPlan' in SCRIPT
    assert 'Rig-window auto-plan: skipped by -SkipPlan.' in SCRIPT
