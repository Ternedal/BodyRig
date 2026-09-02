from __future__ import annotations

from bodyrig.bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_POLICY
from bodyrig.recovery_throughput_audit import RunEvidence
from bodyrig.recovery_throughput_sampling_audit import (
    compare_sampling_runs,
    expected_candidate_revision,
)


BASELINE_REVISION = "4dh:base;phalp:base;nmr:base"
CANDIDATE_REVISION = f"{BASELINE_REVISION};sampling:{RECOVERY_TEMPORAL_SAMPLING_POLICY}"


def _run(*, job_id: str, revision: str, frames: int, track_id: str = "track-1") -> RunEvidence:
    binding = {
        "source": {
            "kind": "stash-performer",
            "performer_id": "42",
            "performer_name": "Fixture Person",
            "disambiguation": "",
        },
        "evidence": {
            "source_files": [
                {"scene_id": "100", "name": "source.mp4", "sha256": "a" * 64},
            ]
        },
    }
    selection = {
        "adapter": "opencv-hog-haar",
        "revision": "1",
        "selected": [
            {
                "source_id": "s001",
                "scene_id": "100",
                "start_seconds": 3.0,
                "duration_seconds": 12.0,
                "target_confidence": 0.9,
                "target_screen_fraction": 0.8,
                "face_visibility": 0.9,
                "full_body_visibility": 0.9,
                "sharpness": 0.9,
                "occlusion": 0.0,
                "motion": 0.5,
                "view": "front",
                "base_score": 0.9,
            }
        ],
    }
    segments = {
        "segments": [
            {
                "source_id": "s001",
                "scene_id": "100",
                "start_seconds": 3.0,
                "duration_seconds": 12.0,
                "sha256": "b" * 64,
            }
        ]
    }
    return RunEvidence(
        job={"job_id": job_id, "person_id": "person-" + "1" * 32},
        source_binding=binding,
        selection=selection,
        segments=segments,
        recovery={
            "adapter": "4dhumans-hmr2-phalp",
            "revision": revision,
            "track_id": track_id,
            "observed_frames": frames,
            "bodyprint": {"height": 1.70, "shape": [1.0, 2.0]},
        },
        identity={
            "capture": {"sample_count": 20},
            "coverage": {"face": 0.9, "full_body": 0.8},
            "quality": {"mean_sharpness": 0.8},
        },
        acceptance={"automated_pass": True},
        fidelity={"views": ["front-full", "three-quarter-full", "side-full", "face-front"]},
        review={"semantics": "visual-fidelity-not-identity-verification"},
        total_seconds=6000.0,
        clone_pipeline_seconds=5000.0,
    )


def test_exact_sampling_revision_is_the_only_allowed_recovery_revision_delta() -> None:
    assert expected_candidate_revision(BASELINE_REVISION) == CANDIDATE_REVISION

    result = compare_sampling_runs(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800),
    )

    assert result["machine_evidence_pass"] is True
    assert result["upstream_recovery_authority_equal"] is True
    assert result["recovery_authority_equal"] is True
    assert result["candidate_recovery_revision"] == CANDIDATE_REVISION
    assert result["expected_candidate_recovery_revision"] == CANDIDATE_REVISION
    assert result["sampling_policy"] == RECOVERY_TEMPORAL_SAMPLING_POLICY
    assert result["promotion_authority"] is False
    assert result["human_visual_review_required"] is True


def test_arbitrary_recovery_revision_is_blocked_even_when_faster() -> None:
    result = compare_sampling_runs(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(job_id="candidate", revision=BASELINE_REVISION + ";some-other-change", frames=900),
    )

    assert result["machine_evidence_pass"] is False
    assert result["upstream_recovery_authority_equal"] is False
    assert "candidate recovery revision is not the exact versioned sampling derivative of baseline" in result["blockers"]
    assert result["promotion_authority"] is False


def test_sampled_run_cannot_be_used_as_uncapped_baseline() -> None:
    result = compare_sampling_runs(
        _run(job_id="baseline", revision=CANDIDATE_REVISION, frames=1800),
        _run(
            job_id="candidate",
            revision=f"{CANDIDATE_REVISION};sampling:{RECOVERY_TEMPORAL_SAMPLING_POLICY}",
            frames=900,
        ),
    )

    assert result["machine_evidence_pass"] is False
    assert "baseline already uses the candidate recovery sampling revision" in result["blockers"]


def test_track_change_remains_blocked_under_sampling_policy() -> None:
    result = compare_sampling_runs(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600, track_id="track-1"),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800, track_id="track-2"),
    )

    assert result["machine_evidence_pass"] is False
    assert result["upstream_recovery_authority_equal"] is False
    assert "recovery track_id differs" in result["blockers"]
