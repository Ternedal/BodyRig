from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(encoding="utf-8")


def test_branch_mode_reattaches_exact_fetched_branch_after_detached_checkout() -> None:
    detach = SCRIPT.index('& git checkout --detach $target')
    branch_guard = SCRIPT.index('if ($targetMode -eq "branch")', detach)
    force_branch = SCRIPT.index('& git branch --force $Branch $target', branch_guard)
    switch_branch = SCRIPT.index('& git switch $Branch', force_branch)
    branch_probe = SCRIPT.index('$currentBranchOutput = @(& git branch --show-current)', switch_branch)
    normalize_branch = SCRIPT.index('$currentBranch = if ($currentBranchOutput.Count -eq 0)', branch_probe)
    assert detach < branch_guard < force_branch < switch_branch < branch_probe < normalize_branch
    assert 'Branch-mode update er ikke attached til expected branch $Branch.' in SCRIPT


def test_historical_revision_accepts_empty_branch_probe_as_detached() -> None:
    branch_probe = SCRIPT.index('$currentBranchOutput = @(& git branch --show-current)')
    exit_guard = SCRIPT.index('if ($LASTEXITCODE -ne 0)', branch_probe)
    normalize_branch = SCRIPT.index('$currentBranch = if ($currentBranchOutput.Count -eq 0)', exit_guard)
    historical_guard = SCRIPT.index('if ($targetMode -eq "historical-revision"', normalize_branch)
    assert '{ "" } else { ([string]$currentBranchOutput[0]).Trim() }' in SCRIPT[normalize_branch:historical_guard]
    assert 'Historical revision update skal forblive detached' in SCRIPT[historical_guard:]


def test_historical_revision_branch_probe_does_not_trim_null_command_output() -> None:
    assert '$currentBranch = (& git branch --show-current).Trim()' not in SCRIPT
