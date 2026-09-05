from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_AB.md").read_text(encoding="utf-8")
BASELINE = "0b8f61b6f369e0d63ed006d808e316798121f79f"


def test_ab_requires_two_succeeded_runs_and_rejects_failed_historical_job_as_baseline() -> None:
    assert "Two **succeeded** Person Studio `body-build` jobs" in DOC
    assert "job-8a5bece5df0f4707a1186b53e01eb4db" in DOC
    assert "it is not an A/B baseline" in DOC
    assert "Do not start the candidate until the baseline has succeeded" in DOC


def test_current_running_authority_can_be_reused_as_baseline_only_after_success() -> None:
    assert BASELINE in DOC
    assert "may be used as the baseline **if and only if it succeeds**" in DOC
    assert "There is no reason to start a second uncapped run" in DOC


def test_ab_binds_baseline_and_candidate_to_exact_software_authority() -> None:
    assert BASELINE in DOC
    assert "job.bodyrig_revision" in DOC
    assert "git rev-parse HEAD" in DOC
    assert "current clean comparator checkout HEAD" in DOC
    assert "dirty comparator checkout is refused" in DOC


def test_runbook_uses_v3_candidate_and_requires_restore() -> None:
    assert '-Branch "agent/recovery-throughput-v3-20260903"' in DOC
    assert '-Branch "agent/person-studio-photoreal-20260902"' in DOC
    assert "restore canonical Person Studio runtime" in DOC
    assert "Do not leave normal BodyRig runtime on the performance-candidate branch" in DOC


def test_runbook_uses_fail_closed_baseline_and_candidate_runners() -> None:
    assert "run-recovery-throughput-baseline.ps1" in DOC
    assert "run-recovery-throughput-candidate.ps1" in DOC
    assert "starts **only** `/body/build`" in DOC
    assert "RECOVERY_TEMPORAL_SAMPLING_REVISION == 15fps-v1" in DOC
    assert "canonical `watch-body-build.ps1` monitor" in DOC


def test_no_watch_never_means_skip_authority_or_readiness_gates() -> None:
    assert "`-NoWatch` may be used" in DOC
    assert "it does not skip any pre-start authority/readiness gate" in DOC
    assert "it does not stop the physical job" in DOC


def test_machine_gate_never_grants_promotion_or_production() -> None:
    assert "promotion_authority = false" in DOC
    assert "production_activation = false" in DOC
    assert "human_visual_review_required = true" in DOC
    assert "eligible-for-human-ab-review" in DOC


def test_review_bundle_is_hash_bound_create_only_and_non_authoritative() -> None:
    assert "build-recovery-throughput-review-bundle.ps1" in DOC
    assert "machine A/B gate passes" in DOC
    assert "no bundle is created" in DOC
    assert "index.html" in DOC
    assert "machine-audit.json" in DOC
    assert "review-bundle.json" in DOC
    assert "persisted SHA-256 values are revalidated" in DOC
    assert "immutable review aid" in DOC
    assert "does not record an approval" in DOC


def test_human_review_uses_exact_four_canonical_views_and_structured_receipt() -> None:
    for view in ("front-full", "three-quarter-full", "side-full", "face-front"):
        assert f"`{view}`" in DOC
    assert "record-recovery-throughput-human-review.ps1" in DOC
    assert "Each criterion must be explicitly `pass` or `fail`" in DOC
    assert "review-bundle.json` and `machine-audit.json` SHA-256" in DOC
    assert "blocked-material-regression" in DOC
    assert "eligible-for-explicit-promotion-review" in DOC
    assert "structured human evidence, not an authority mutation" in DOC


def test_human_receipt_cannot_mutate_bundle_or_grant_authority() -> None:
    assert "separate create-only receipt outside the immutable bundle" in DOC
    assert "cannot mutate the hash-manifested bundle" in DOC
    assert "promotion_authority = false" in DOC
    assert "production_activation = false" in DOC


def test_ab_preserves_native_observation_bytes_and_requires_exact_evidence() -> None:
    assert "must not rewrite or spatially downscale" in DOC
    assert "same exact source-file SHA evidence" in DOC
    assert "same native observation segment identities and SHA-256 bytes" in DOC
    assert "same selected recovery track" in DOC


def test_ci_or_speed_alone_can_never_promote_candidate() -> None:
    assert "Never merge PR #60 or move physical authority solely because CI is green" in DOC
    assert "because the candidate is faster" in DOC
