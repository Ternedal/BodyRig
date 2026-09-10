from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "record-ab-candidate-promotion-review.ps1").read_text(encoding="utf-8")

BASELINE = "6e10351e4eba929062960ac46ec1582a467db259"
PBR = "fe2db94b8ae3be51938a7b302361bcf5fdec5f48"
FAILED_THROUGHPUT = "ec743446d98809d693d01e51830f435fc3c09535"
FIXED_THROUGHPUT = "5fa01deb08399fda64e83db1329d4d2e83ad1bc2"
FAILED_JOB = "job-164250c1d8e04f66a8f8f6cf646c1a31"
CANDIDATE_JOB = "job-56248d1b57164ce9b68ea8e5478b7f9d"


def test_promotion_is_explicit_create_only_and_non_production() -> None:
    assert "[switch]$PromotePbr" in SCRIPT
    assert "[switch]$PromoteThroughput" in SCRIPT
    assert "[switch]$ConfirmPromotion" in SCRIPT
    assert "if (-not $PromotePbr -or -not $PromoteThroughput -or -not $ConfirmPromotion)" in SCRIPT
    assert "format = 'bodyrig-dual-candidate-explicit-promotion-review'" in SCRIPT
    assert "candidate_promotion_authority = $true" in SCRIPT
    assert "promotion_authority = $true" in SCRIPT
    assert "physical_acceptance_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT
    assert "release_authority = $false" in SCRIPT
    assert "Refusing to overwrite candidate promotion review" in SCRIPT


def test_promotion_is_bound_to_exact_reviewed_lineage() -> None:
    for value in (BASELINE, PBR, FAILED_THROUGHPUT, FIXED_THROUGHPUT, FAILED_JOB, CANDIDATE_JOB):
        assert value in SCRIPT
    assert "candidate/skin-pbr-v3-linear-light-20260909" in SCRIPT
    assert "candidate/recovery-throughput-v3-current-main-20260908" in SCRIPT
    assert "fix/throughput-v3-resume-signature-20260910" in SCRIPT
    assert "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'" in SCRIPT
    assert "Assert-Ancestor -Ancestor $ExpectedFailedThroughputRevision -Descendant $ExpectedFixedThroughputRevision" in SCRIPT


def test_pbr_promotion_requires_the_real_human_right_decision() -> None:
    assert "Join-Path $PbrRunDir 'human-review.json'" in SCRIPT
    assert "Join-Path $PbrRunDir 'plan-bound-human-review-authority.json'" in SCRIPT
    assert "[string]$pbrReview.decision -ne 'right'" in SCRIPT
    assert "[string]$pbrReview.preferred_side -ne 'right'" in SCRIPT
    assert "[string]$retry.pbr_decision -ne 'right'" in SCRIPT
    assert "retry.pbr_human_review_authority_sha256" in SCRIPT
    assert "retry.pbr_human_review_sha256" in SCRIPT


def test_throughput_promotion_requires_real_no_regression_human_review() -> None:
    assert '"$ThroughputRunDir.human-review.json"' in SCRIPT
    assert '"$ThroughputRunDir.retry-human-review-authority.json"' in SCRIPT
    assert "human_visual_review_passed -ne $true" in SCRIPT
    assert "[string]$throughputReview.decision -ne 'no-material-regression'" in SCRIPT
    assert "[string]$throughputReview.next_gate -ne 'eligible-for-explicit-promotion-review'" in SCRIPT
    for criterion in ("identity_shape", "face_identity", "skin_texture_alignment", "gross_anatomy"):
        assert criterion in SCRIPT
    assert "continuation_authority_sha256" in SCRIPT
    assert "human_review_sha256" in SCRIPT
    assert "retry_authority_sha256" in SCRIPT


def test_candidate_diffs_are_closed_to_reviewed_file_sets() -> None:
    pbr_files = {
        "bodyrig/bridges/sith_pbr_material.py",
        "tests/test_sith_basecolor_detail.py",
        "tests/test_sith_pbr_material.py",
    }
    throughput_files = {
        "bodyrig/bridges/hmr2_checkpoint_bridge.py",
        "bodyrig/bridges/hmr2_config.py",
        "bodyrig/bridges/hmr2_resume_bridge.py",
        "bodyrig/recovery_throughput_human_review.py",
        "bodyrig/recovery_throughput_review_bundle.py",
        "bodyrig/recovery_throughput_sampling_audit.py",
        "build-recovery-throughput-review-bundle.ps1",
        "compare-recovery-throughput.ps1",
        "docs/RECOVERY_THROUGHPUT_AB.md",
        "record-recovery-throughput-human-review.ps1",
        "tests/test_compare_recovery_throughput_script.py",
        "tests/test_hmr2_cross_job_resume.py",
        "tests/test_hmr2_recovery_checkpoints.py",
        "tests/test_hmr2_resume_signature_regression.py",
        "tests/test_observation_throughput.py",
        "tests/test_recovery_throughput_ab_docs.py",
        "tests/test_recovery_throughput_review_chain.py",
        "tests/test_recovery_throughput_review_wrappers.py",
        "tests/test_recovery_throughput_sampling_audit.py",
    }
    for path in pbr_files | throughput_files:
        assert repr(path) in SCRIPT
    assert "Assert-ExactFileSet -Base $ExpectedBaselineRevision -Head $ExpectedPbrRevision" in SCRIPT
    assert "Assert-ExactFileSet -Base $ExpectedBaselineRevision -Head $ExpectedFixedThroughputRevision" in SCRIPT


def test_promotion_refreshes_exact_remote_refs_and_rechecks_job_bytes() -> None:
    assert "git -C $RepoRoot fetch --no-tags origin @fetchSpecs" in SCRIPT
    assert "Assert-RemoteRef -Ref 'main' -Expected $ExpectedBaselineRevision" in SCRIPT
    assert "Assert-RemoteRef -Ref $ExpectedPbrRef -Expected $ExpectedPbrRevision" in SCRIPT
    assert "Assert-RemoteRef -Ref $ExpectedFailedThroughputRef -Expected $ExpectedFailedThroughputRevision" in SCRIPT
    assert "Assert-RemoteRef -Ref $ExpectedFixedThroughputRef -Expected $ExpectedFixedThroughputRevision" in SCRIPT
    assert "continuation.baseline_job_json_sha256" in SCRIPT
    assert "continuation.candidate_job_json_sha256" in SCRIPT
