from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "run-pbr-ab-physical-review.ps1").read_text(encoding="utf-8")
LATEST = (ROOT / "run-latest-pbr-ab-physical-review.ps1").read_text(encoding="utf-8")
REVIEW = (ROOT / "record-fidelity-ab-review.ps1").read_text(encoding="utf-8")
POLICY = json.loads((ROOT / "contracts" / "pbr-ab-source-policy-v1.json").read_text(encoding="utf-8"))


def test_runner_requires_current_clean_main_and_freezes_remote_refs() -> None:
    assert '"branch","--show-current"' in RUNNER
    assert 'if ($branchRaw.Trim() -ne "main")' in RUNNER
    assert 'refs/remotes/origin/main' in RUNNER
    assert 'Local main is not current origin/main' in RUNNER
    assert 'refs/remotes/origin/$CandidateRef' in RUNNER
    assert 'Recheck remote refs after A/B' in RUNNER
    assert 'Baseline or candidate remote ref moved during the A/B run' in RUNNER
    assert 'Assert-CleanCheckout -Root $repoRoot' in RUNNER
    assert 'Assert-CleanCheckout -Root $candidateWorktree' in RUNNER


def test_runner_locks_current_pbr_candidate_to_reviewed_three_file_delta() -> None:
    assert '"rev-list","--count","$baselineRevision..$candidateRevision"' in RUNNER
    assert 'PBR candidate must be exactly one commit ahead of current main' in RUNNER
    for path in (
        "bodyrig/bridges/sith_pbr_material.py",
        "tests/test_sith_basecolor_detail.py",
        "tests/test_sith_pbr_material.py",
    ):
        assert f'"{path}"' in RUNNER
    assert 'PBR candidate diff boundary changed' in RUNNER


def test_checkout_python_executes_from_exact_bound_checkout_and_restores_location() -> None:
    assert '$checkoutPath = Need-Directory -Path $CheckoutRoot -Label "$Step checkout"' in RUNNER
    assert '$locationPushed = $false' in RUNNER
    assert 'Push-Location -LiteralPath $checkoutPath' in RUNNER
    assert '$locationPushed = $true' in RUNNER
    assert '"$checkoutPath$([IO.Path]::PathSeparator)$oldPythonPath"' in RUNNER
    assert 'Join-Path $checkoutPath "bodyrig\\__init__.py"' in RUNNER
    assert 'if ($locationPushed) { Pop-Location }' in RUNNER
    assert RUNNER.index('Push-Location -LiteralPath $checkoutPath') < RUNNER.index('import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())')


def test_runner_reuses_one_reconstruction_and_proves_workspace_immutability() -> None:
    assert 'bodyrig.fidelity_checkpoint_verify_cli' in RUNNER
    assert 'reconstruction.json' in RUNNER
    assert 'reconstruction-authority.json' in RUNNER
    assert 'bodyrig.sith_reconstruction_authority' in RUNNER
    assert 'Get-TreeDigest -Root $stage' in RUNNER
    assert 'Retained SiTH tree changed during baseline package build' in RUNNER
    assert 'Retained SiTH tree changed during candidate package build' in RUNNER
    assert 'reconstruction.json changed during PBR A/B' in RUNNER
    assert 'reconstruction-authority.json changed during PBR A/B' in RUNNER
    assert 'retained_reconstruction_reused = $true' in RUNNER
    assert 'retained_reconstruction_unchanged = $true' in RUNNER


def test_runner_builds_exact_revision_bound_packages_then_machine_ab() -> None:
    assert RUNNER.count('"-m","bodyrig.external_fitter_cli"') == 2
    assert 'BODYRIG_SITH_RECON_CHECKPOINT_SHA256' in RUNNER
    assert 'BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256' in RUNNER
    assert 'BODYRIG_SITH_BODY_MODEL_GENDER' in RUNNER
    assert 'Baseline package is not builder-bound to exact baseline revision' in RUNNER
    assert 'Candidate package is not builder-bound to exact candidate revision' in RUNNER
    assert 'compare-fidelity-ab.ps1' in RUNNER
    assert '-ExpectedLeftBuilderRevision $baselineRevision' in RUNNER
    assert '-ExpectedRightBuilderRevision $candidateRevision' in RUNNER
    assert 'clean_appearance_ab_passed = $true' in RUNNER


def test_runner_uses_one_common_renderer_revision_for_both_sides() -> None:
    assert 'run-fidelity-windows-render-probe.ps1' in RUNNER
    assert 'PackagePath = $baselinePackage' in RUNNER
    assert 'PackagePath = $candidatePackage' in RUNNER
    assert 'SkipBuild = $true' in RUNNER
    assert 'renderer_revision = $baselineRevision' in RUNNER
    assert 'baseline-render' in RUNNER
    assert 'candidate-render' in RUNNER


def test_pbr_ab_runners_share_one_safe_source_policy_contract() -> None:
    assert POLICY == {
        "format": "bodyrig-pbr-ab-source-policy",
        "version": 1,
        "safe_source_floor_revision": "905fb0e9e9b67ad009fb707164474caf827a93a6",
    }
    for source in (LATEST, RUNNER):
        assert 'contracts\\pbr-ab-source-policy-v1.json' in source
        assert 'bodyrig-pbr-ab-source-policy' in source
        assert 'safe_source_floor_revision' in source
        assert 'PBR A/B retained-source policy fields/format/version do not match v1.' in source


def test_latest_runner_rejects_pre_safe_source_checkpoints_by_git_ancestry() -> None:
    assert 'git -C $repoRoot cat-file -e $spec' in LATEST
    assert 'git -C $repoRoot merge-base --is-ancestor $Ancestor $Descendant' in LATEST
    assert 'checkpoint.bodyrig_revision' in LATEST
    assert 'predates or is outside safe-source floor' in LATEST
    assert 'Historical/pre-projection-safety evidence remains historical and cannot be rebound.' in LATEST
    assert 'LastWriteTimeUtc' in LATEST  # ordering only, never safety authority


def test_strict_convergence_runner_enforces_same_safe_source_floor() -> None:
    assert '$checkpointRevision = Need-Revision -Value ([string]$checkpoint.bodyrig_revision)' in RUNNER
    assert 'Test-CommitExists -Root $repoRoot -Revision $checkpointRevision' in RUNNER
    assert 'Test-IsAncestor -Root $repoRoot -Ancestor $safeSourceFloorRevision -Descendant $checkpointRevision' in RUNNER
    assert 'historical/pre-projection-safety evidence cannot be rebound.' in RUNNER
    assert 'retained_source_mode = $(if ($usingConvergence) { "verified-safe-convergence" } else { "explicit-expert-recovery" })' in RUNNER
    assert 'retained_source_policy_sha256' in RUNNER
    assert 'safe_source_floor_revision' in RUNNER
    assert 'retained_checkpoint_revision' in RUNNER


def test_latest_runner_keeps_byte_verification_and_exact_body_binding() -> None:
    assert 'bodyrig.fidelity_checkpoint_verify_cli' in LATEST
    assert 'checkpoint body alias mismatch' in LATEST
    assert 'newest byte-verified convergence whose BodyRig revision descends from the safe-source floor' in LATEST


def test_runner_stops_before_human_or_physical_acceptance() -> None:
    assert 'human_visual_review_required = $true' in RUNNER
    assert 'comparison_only = $true' in RUNNER
    assert 'physical_acceptance_authority = $false' in RUNNER
    assert 'production_activation = $false' in RUNNER
    assert 'REVIEW-NEXT.txt' in RUNNER
    assert 'review.html' in RUNNER
    assert '& $review' not in RUNNER
    assert 'accept-physical-clone.ps1' not in RUNNER
    assert 'record-renderer-acceptance.ps1' not in RUNNER
    assert 'complete-acceptance.ps1' not in RUNNER


def test_review_wrapper_requires_explicit_human_confirmation_clean_checkout_and_renderer_match() -> None:
    assert '[ValidateSet("left", "right", "tie", "reject-both")]' in REVIEW
    assert '[Parameter(Mandatory = $true)][switch]$ConfirmVisualReview' in REVIEW
    assert 'Pass -ConfirmVisualReview only after visually comparing all four canonical left/right snapshots.' in REVIEW
    assert 'git -C $repoRoot status --porcelain' in REVIEW
    assert 'bodyrig.fidelity_ab_review' in REVIEW
    assert '--expected-renderer-revision $head' in REVIEW
    assert '--confirm-visual-review' in REVIEW
    assert 'removed non-authoritative receipt' in REVIEW
    assert 'production activation=false' in REVIEW
