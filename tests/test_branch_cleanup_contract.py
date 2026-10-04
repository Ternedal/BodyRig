from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_branch_cleanup_workflow_requires_non_interpolated_confirmation() -> None:
    workflow = (ROOT / ".github" / "workflows" / "branch-cleanup.yml").read_text(encoding="utf-8")
    assert "BODYRIG_BRANCH_CLEANUP_CONFIRM: ${{ inputs.confirm }}" in workflow
    assert 'if ($env:BODYRIG_BRANCH_CLEANUP_CONFIRM -cne "DELETE")' in workflow
    assert 'if ("${{ inputs.confirm }}"' not in workflow


def test_branch_cleanup_all_mode_deduplicates_superseded_from_merged() -> None:
    script = (ROOT / "tools" / "cleanup-merged-remote-branches.ps1").read_text(encoding="utf-8")
    assert "$mergedCandidateSet" in script
    assert "$mergedCandidateSet.Contains($branch)" in script
    assert "if (-not $mergedCandidateSet.Contains($branch))" in script


def test_branch_cleanup_is_dry_run_by_default() -> None:
    workflow = (ROOT / ".github" / "workflows" / "branch-cleanup.yml").read_text(encoding="utf-8")
    assert 'default: "dry-run"' in workflow
    assert "./tools/cleanup-merged-remote-branches.ps1 -Apply" in workflow
    assert "./tools/cleanup-merged-remote-branches.ps1 -ApplySuperseded" in workflow
