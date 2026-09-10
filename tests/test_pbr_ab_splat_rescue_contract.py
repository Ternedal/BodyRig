from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rescue-pbr-ab-after-splat-bug.ps1").read_text(encoding="utf-8")


def test_rescue_runs_against_explicit_clean_baseline_repo_without_checkout_mutation() -> None:
    assert "[string]$RepoRoot" in SCRIPT
    assert "[string]$OperatorPatchRevision" in SCRIPT
    assert "Assert-CleanMain -Root $RepoRoot -ExpectedRevision $mainRevision" in SCRIPT
    assert '"status","--porcelain"' in SCRIPT
    assert '"refs/remotes/origin/main"' in SCRIPT
    assert "git checkout" not in SCRIPT.lower()
    assert "git switch" not in SCRIPT.lower()
    assert "update_ref" not in SCRIPT.lower()


def test_rescue_proves_exact_launcher_only_operator_patch() -> None:
    for path in (
        "rescue-pbr-ab-after-splat-bug.ps1",
        "run-pbr-ab-from-body-job.ps1",
        "tests/test_pbr_ab_plan_bound_wrapper.py",
        "tests/test_pbr_ab_splat_rescue_contract.py",
    ):
        assert f'"{path}"' in SCRIPT
    assert '"merge-base",$mainRevision,$OperatorPatchRevision' in SCRIPT
    assert '"diff","--name-only","--no-renames","$mainRevision..$OperatorPatchRevision"' in SCRIPT
    assert '${OperatorPatchRevision}:run-pbr-ab-from-body-job.ps1' in SCRIPT
    assert "reviewed named-splat launcher correction" in SCRIPT


def test_rescue_calls_unchanged_baseline_internal_runner_with_named_splatting() -> None:
    assert 'Join-Path $RepoRoot "run-pbr-ab-from-body-job-internal.ps1"' in SCRIPT
    assert "$internalParams = @{" in SCRIPT
    assert "BaselineJobId = $BaselineJobId" in SCRIPT
    assert "CandidateRef = $pbrRef" in SCRIPT
    assert "OutputDir = $OutputDir" in SCRIPT
    assert "BodyRigPython = $BodyRigPython" in SCRIPT
    assert "& $internal @internalParams" in SCRIPT
    assert "@internalArgs" not in SCRIPT


def test_rescue_revalidates_plan_candidate_and_comparison_only_authority() -> None:
    assert "bodyrig.ab_baseline_candidates" in SCRIPT
    assert "--expected-main-revision" in SCRIPT
    assert "--expected-pbr-revision" in SCRIPT
    assert "--expected-throughput-revision" in SCRIPT
    assert "candidate_contract_sha256 = $contractSha" in SCRIPT
    assert 'format = "bodyrig-pbr-ab-body-job-plan-authority"' in SCRIPT
    assert 'format = "bodyrig-pbr-launcher-splat-rescue-authority"' in SCRIPT
    assert "comparison_only = $true" in SCRIPT
    assert "human_visual_authority_required = $true" in SCRIPT
    assert "physical_acceptance_authority = $false" in SCRIPT
    assert "promotion_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT


def test_rescue_preserves_normal_plan_bound_human_review_continuation() -> None:
    assert '"REVIEW-NEXT.txt"' in SCRIPT
    assert ".\\record-pbr-ab-human-review-from-plan.ps1" in SCRIPT
    assert "<left|right|tie|reject-both>" in SCRIPT
    assert "-ConfirmVisualReview" in SCRIPT
