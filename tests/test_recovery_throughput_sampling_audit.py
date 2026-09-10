from __future__ import annotations

from bodyrig.bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_POLICY, RECOVERY_TEMPORAL_SAMPLING_REVISION
from bodyrig.recovery_throughput_sampling_audit import RunEvidence, compare_runs, expected_candidate_revision


BASELINE_RECOVERY_REVISION = "4dh:" + "1" * 40 + ";phalp:" + "2" * 40 + ";nmr:" + "3" * 40
CANDIDATE_RECOVERY_REVISION = f"{BASELINE_RECOVERY_REVISION};s:{RECOVERY_TEMPORAL_SAMPLING_REVISION}"
BASELINE_BODYRIG_REVISION = "8" * 40
CANDIDATE_BODYRIG_REVISION = "9" * 40


def _run(*, job_id: str, recovery_revision: str, frames: int, bodyrig_revision: str) -> RunEvidence:
    return RunEvidence(
        job={
            "job_id": job_id,
            "person_id": "person-" + "1" * 32,
            "bodyrig_revision": bodyrig_revision,
        },
        binding={
            "source": {"kind": "stash-performer", "performer_id": "42"},
            "evidence": {"source_files": [{"scene_id": "100", "name": "source.mp4", "sha256": "a" * 64}]},
        },
        selection={
            "adapter": "opencv-hog-haar",
            "revision": "1",
            "selected": [{"source_id": "s001", "scene_id": "100", "start_seconds": 3.0, "duration_seconds": 12.0}],
        },
        segments={
            "segments": [{
                "source_id": "s001",
                "scene_id": "100",
                "start_seconds": 3.0,
                "duration_seconds": 12.0,
                "sha256": "b" * 64,
            }]
        },
        recovery={
            "adapter": "4dhumans-hmr2-phalp",
            "revision": recovery_revision,
            "track_id": "s00-t1",
            "observed_frames": frames,
            "bodyprint": {"shape": {"shoulder_width_ratio": 0.25}},
        },
        identity={
            "capture": {"sample_count": 20},
            "coverage": {"face": 0.9},
            "quality": {"mean_sharpness": 0.8},
        },
        acceptance={"automated_pass": True},
        fidelity={"views": ["front-full"]},
        review={"semantics": "visual-fidelity-not-identity-verification"},
        package_sha256="c" * 64,
        total_seconds=6000.0 if job_id == "baseline" else 3600.0,
        clone_pipeline_seconds=5000.0 if job_id == "baseline" else 3000.0,
    )


def _compare(baseline: RunEvidence, candidate: RunEvidence) -> dict:
    return compare_runs(
        baseline,
        candidate,
        expected_baseline_bodyrig_revision=BASELINE_BODYRIG_REVISION,
        expected_candidate_bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
    )


def test_expected_candidate_revision_is_versioned_sampling_derivative() -> None:
    assert expected_candidate_revision(BASELINE_RECOVERY_REVISION) == CANDIDATE_RECOVERY_REVISION
    assert len(CANDIDATE_RECOVERY_REVISION) <= 160


def test_machine_gate_binds_explicit_baseline_and_candidate_revisions() -> None:
    result = _compare(
        _run(
            job_id="baseline",
            recovery_revision=BASELINE_RECOVERY_REVISION,
            frames=3600,
            bodyrig_revision=BASELINE_BODYRIG_REVISION,
        ),
        _run(
            job_id="candidate",
            recovery_revision=CANDIDATE_RECOVERY_REVISION,
            frames=1800,
            bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
        ),
    )

    assert result["machine_evidence_pass"] is True
    assert result["software_authority_bound"] is True
    assert result["expected_baseline_bodyrig_revision"] == BASELINE_BODYRIG_REVISION
    assert result["expected_candidate_bodyrig_revision"] == CANDIDATE_BODYRIG_REVISION
    assert result["sampling_policy"] == RECOVERY_TEMPORAL_SAMPLING_POLICY
    assert result["native_observation_segment_bytes_equal"] is True
    assert result["frames"]["ratio"] == 0.5
    assert result["human_visual_review_required"] is True
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
    assert result["decision"] == "eligible-for-human-ab-review"


def test_wrong_explicit_baseline_revision_fails_closed() -> None:
    result = _compare(
        _run(
            job_id="baseline",
            recovery_revision=BASELINE_RECOVERY_REVISION,
            frames=3600,
            bodyrig_revision="7" * 40,
        ),
        _run(
            job_id="candidate",
            recovery_revision=CANDIDATE_RECOVERY_REVISION,
            frames=1800,
            bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
        ),
    )
    assert result["machine_evidence_pass"] is False
    assert result["software_authority_bound"] is False
    assert "baseline BodyRig revision does not match the explicitly selected baseline authority" in result["blockers"]


def test_candidate_must_match_exact_comparator_checkout_revision() -> None:
    result = _compare(
        _run(
            job_id="baseline",
            recovery_revision=BASELINE_RECOVERY_REVISION,
            frames=3600,
            bodyrig_revision=BASELINE_BODYRIG_REVISION,
        ),
        _run(
            job_id="candidate",
            recovery_revision=CANDIDATE_RECOVERY_REVISION,
            frames=1800,
            bodyrig_revision="6" * 40,
        ),
    )
    assert result["machine_evidence_pass"] is False
    assert result["software_authority_bound"] is False
    assert "candidate BodyRig revision does not match the exact comparator checkout authority" in result["blockers"]


def test_faster_arbitrary_recovery_revision_is_not_accepted() -> None:
    result = _compare(
        _run(
            job_id="baseline",
            recovery_revision=BASELINE_RECOVERY_REVISION,
            frames=3600,
            bodyrig_revision=BASELINE_BODYRIG_REVISION,
        ),
        _run(
            job_id="candidate",
            recovery_revision=BASELINE_RECOVERY_REVISION + ";x:other",
            frames=900,
            bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
        ),
    )
    assert result["machine_evidence_pass"] is False
    assert "candidate recovery revision is not the exact versioned sampling derivative of baseline" in result["blockers"]
