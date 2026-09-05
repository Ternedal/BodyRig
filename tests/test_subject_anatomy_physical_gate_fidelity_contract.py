from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-subject-anatomy-physical-gate.ps1"


def test_physical_gate_revalidates_package_fidelity_result_before_render() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '$packageResult.high_fidelity_ready -ne $false' in source
    assert '$packageResult.face_secondary_ready -ne $false' in source
    assert '$packageResult.face_secondary_blockers' in source
    assert 'Subject anatomy package result violates the high-fidelity fail-closed authority boundary.' in source
    assert '$packageResult.production_activation -ne $false' in source


def test_physical_gate_summary_preserves_nested_face_secondary_blockers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    summary_start = source.index('$summary = [ordered]@{')
    summary_end = source.index('Write-Summary -Path $summaryPath -Value $summary')
    summary = source[summary_start:summary_end]

    assert 'high_fidelity_ready = $false' in summary
    assert 'face_secondary_ready = $false' in summary
    assert 'face_secondary_blockers = @($packageResult.face_secondary_blockers)' in summary
    assert 'human_review_required = $true' in summary
    assert 'production_activation = $false' in summary


def test_physical_gate_requires_external_run_root_and_terminal_checkout_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Assert-CheckoutAuthority" in source
    assert "$headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)" in source
    assert "status --porcelain" in source
    assert "$head = Assert-CheckoutAuthority -RepoRoot $repoRoot" in source
    assert "must be outside the BodyRig Git checkout" in source
    assert "function Assert-TerminalCheckoutAuthority" in source
    assert "Remove-Item -LiteralPath $RunRoot -Recurse -Force" in source
    assert "removed non-authoritative subject anatomy run root" in source

    initial = source.index("$head = Assert-CheckoutAuthority -RepoRoot $repoRoot")
    run_root_boundary = source.index("must be outside the BodyRig Git checkout")
    run_root_creation = source.index("New-Item -ItemType Directory -Path $RunRoot")
    renderer = source.index('Label "Canonical Windows comparison render"')
    pre_summary = source.index(
        'Assert-TerminalCheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head -RunRoot $RunRoot -Phase "Pre-success-summary"'
    )
    summary = source.index('$summary = [ordered]@{', pre_summary)
    write_summary = source.index('Write-Summary -Path $summaryPath -Value $summary', summary)
    post_summary = source.index(
        'Assert-TerminalCheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head -RunRoot $RunRoot -Phase "Post-success-summary"',
        write_summary,
    )
    success = source.index('Write-Host "BodyRig subject anatomy physical gate: MACHINE PASS"')

    assert initial < run_root_boundary < run_root_creation < renderer < pre_summary < summary
    assert summary < write_summary < post_summary < success


def test_physical_gate_failure_summaries_are_checkout_bound_too() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    refit_result = source.index('subject_refit = "regressed"')
    refit_pre = source.rindex('Phase "Pre-regression-summary"', 0, refit_result)
    refit_write = source.index('Write-Summary -Path $summaryPath -Value ([ordered]@{', refit_pre)
    refit_post = source.index('Phase "Post-regression-summary"', refit_result)
    refit_exit = source.index('exit 2', refit_post)

    mismatch_result = source.index('candidate_anatomy = "gross-mismatch"')
    mismatch_pre = source.rindex('Phase "Pre-mismatch-summary"', 0, mismatch_result)
    mismatch_write = source.index('Write-Summary -Path $summaryPath -Value ([ordered]@{', mismatch_pre)
    mismatch_post = source.index('Phase "Post-mismatch-summary"', mismatch_result)
    mismatch_exit = source.index('exit 2', mismatch_post)

    assert refit_pre < refit_write < refit_result < refit_post < refit_exit
    assert mismatch_pre < mismatch_write < mismatch_result < mismatch_post < mismatch_exit
