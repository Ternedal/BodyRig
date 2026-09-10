from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(encoding="utf-8")


def test_branch_mode_reattaches_exact_fetched_branch_after_detached_checkout() -> None:
    detach = SCRIPT.index('& git checkout --detach $target')
    branch_guard = SCRIPT.index('if ($targetMode -eq "branch")', detach)
    force_branch = SCRIPT.index('& git branch --force $Branch $target', branch_guard)
    switch_branch = SCRIPT.index('& git switch $Branch', force_branch)
    verify_branch = SCRIPT.index('$currentBranch = (& git branch --show-current).Trim()', switch_branch)
    assert detach < branch_guard < force_branch < switch_branch < verify_branch
    assert 'Branch-mode update er ikke attached til expected branch $Branch.' in SCRIPT


def test_historical_revision_remains_detached() -> None:
    verify_branch = SCRIPT.index('$currentBranch = (& git branch --show-current).Trim()')
    historical_guard = SCRIPT.index('if ($targetMode -eq "historical-revision"', verify_branch)
    assert 'Historical revision update skal forblive detached' in SCRIPT[historical_guard:]
