from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_AB.md").read_text(encoding="utf-8")
BASELINE = "76c64a9546238663dedf750a1da4a230cc1e7fa4"


def test_ab_requires_two_succeeded_runs_and_rejects_failed_historical_job_as_baseline() -> None:
    assert "Two **succeeded** Person Studio `body-build` jobs" in DOC
    assert "job-8a5bece5df0f4707a1186b53e01eb4db" in DOC
    assert "it is not an A/B baseline" in DOC
    assert "Do not start the candidate until the baseline has succeeded" in DOC


def test_ab_binds_baseline_and_candidate_to_exact_software_authority() -> None:
    assert BASELINE in DOC
    assert "job.bodyrig_revision" in DOC
    assert "git rev-parse HEAD" in DOC
    assert "current clean comparator checkout HEAD" in DOC
    assert "A dirty comparator checkout is refused" in DOC


def test_runbook_uses_safe_updater_for_both_switches_and_requires_restore() -> None:
    assert '-Branch "agent/person-studio-photoreal-20260902"' in DOC
    assert '-Branch "agent/recovery-throughput-v2-20260903"' in DOC
    assert "Always restore canonical Person Studio authority" in DOC
    assert "Do not leave normal BodyRig runtime on the performance-candidate branch" in DOC


def test_machine_gate_never_grants_promotion_or_production() -> None:
    assert "promotion_authority = false" in DOC
    assert "production_activation = false" in DOC
    assert "human_visual_review_required = true" in DOC
    assert "eligible-for-human-ab-review" in DOC


def test_ab_preserves_native_observation_bytes_and_requires_exact_evidence() -> None:
    assert "must not rewrite or spatially downscale" in DOC
    assert "same exact source-file SHA evidence" in DOC
    assert "same native observation segment identities and SHA-256 bytes" in DOC
    assert "same selected recovery track" in DOC


def test_ci_or_speed_alone_can_never_promote_candidate() -> None:
    assert "Never merge PR #58 or move PR #1/physical authority solely because CI is green" in DOC
    assert "because the candidate is faster" in DOC
