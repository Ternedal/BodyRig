from __future__ import annotations

from pathlib import Path

from bodyrig.recovery_throughput_audit import (
    RunEvidence,
    _clone_pipeline_seconds,
    _numeric_deltas,
    _total_seconds,
    compare_runs,
)


def _binding(*, performer_id: str = "42", source_sha: str = "a" * 64) -> dict:
    return {
        "source": {
            "kind": "stash-performer",
            "performer_id": performer_id,
            "performer_name": "Fixture Person",
            "disambiguation": "",
        },
        "evidence": {
            "source_files": [
                {"scene_id": "100", "name": "source.mp4", "sha256": source_sha},
            ]
        },
    }


def _selection(*, start: float = 3.0) -> dict:
    return {
        "adapter": "opencv-hog-haar",
        "revision": "1",
        "selected": [
            {
                "source_id": "s001",
                "scene_id": "100",
                "start_seconds": start,
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


def _segments(*, start: float = 3.0, sha: str = "b" * 64) -> dict:
    return {
        "segments": [
            {
                "source_id": "s001",
                "scene_id": "100",
                "start_seconds": start,
                "duration_seconds": 12.0,
                "sha256": sha,
            }
        ]
    }


def _identity(*, sharpness: float = 0.8) -> dict:
    return {
        "capture": {
            "sample_count": 20,
            "face_sample_count": 12,
            "full_body_sample_count": 10,
        },
        "coverage": {
            "face": 0.9,
            "hair_or_scalp": 0.9,
            "skin": 0.8,
            "clothing": 0.7,
            "full_body": 0.8,
            "back": 0.2,
            "side": 0.5,
        },
        "quality": {
            "mean_sharpness": sharpness,
            "mean_lighting": 0.7,
            "mean_visibility": 0.8,
        },
    }


def _run(
    *,
    job_id: str,
    frames: int,
    track_id: str = "track-1",
    binding: dict | None = None,
    selection: dict | None = None,
    segments: dict | None = None,
    identity: dict | None = None,
    total_seconds: float = 7200.0,
    clone_seconds: float = 6000.0,
) -> RunEvidence:
    return RunEvidence(
        job={"job_id": job_id, "person_id": "person-" + "1" * 32},
        source_binding=binding or _binding(),
        selection=selection or _selection(),
        segments=segments or _segments(),
        recovery={
            "adapter": "4d-humans-phalp",
            "revision": "pinned-r1",
            "track_id": track_id,
            "observed_frames": frames,
            "bodyprint": {"shape": [1.0, 2.0], "height": 1.70},
        },
        identity=identity or _identity(),
        acceptance={"automated_pass": True},
        fidelity={"views": ["front-full", "three-quarter-full", "side-full", "face-front"]},
        review={"semantics": "visual-fidelity-not-identity-verification"},
        total_seconds=total_seconds,
        clone_pipeline_seconds=clone_seconds,
    )


def test_matching_candidate_with_real_frame_reduction_is_only_eligible_for_human_review() -> None:
    baseline = _run(job_id="baseline", frames=3600, total_seconds=10000, clone_seconds=9000)
    candidate = _run(job_id="candidate", frames=1800, total_seconds=6000, clone_seconds=5000)

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is True
    assert result["decision"] == "eligible-for-human-ab-review"
    assert result["frames"]["reduction_observed"] is True
    assert result["frames"]["ratio"] == 0.5
    assert result["timing"]["clone_pipeline_ratio"] == 5000 / 9000
    assert result["human_visual_review_required"] is True
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
    assert result["blockers"] == []


def test_candidate_cannot_pass_by_being_faster_on_different_source_authority() -> None:
    baseline = _run(job_id="baseline", frames=3600)
    candidate = _run(job_id="candidate", frames=1200, binding=_binding(source_sha="c" * 64))

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is False
    assert result["source_authority_equal"] is False
    assert "baseline and candidate exact source-file SHA evidence differ" in result["blockers"]
    assert result["promotion_authority"] is False


def test_candidate_cannot_pass_if_observation_window_or_segment_identity_changes() -> None:
    baseline = _run(job_id="baseline", frames=3600)
    candidate = _run(
        job_id="candidate",
        frames=1800,
        selection=_selection(start=8.0),
        segments=_segments(start=8.0, sha="d" * 64),
    )

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is False
    assert result["observation_selection_equal"] is False
    assert result["segment_windows_equal"] is False
    assert "observation selection windows/quality evidence differ" in result["blockers"]
    assert "materialized segment source/start/duration identity differs" in result["blockers"]


def test_candidate_cannot_pass_if_recovery_track_changes() -> None:
    baseline = _run(job_id="baseline", frames=3600, track_id="track-1")
    candidate = _run(job_id="candidate", frames=1800, track_id="track-2")

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is False
    assert result["recovery_authority_equal"] is False
    assert "recovery track_id differs" in result["blockers"]


def test_candidate_must_demonstrate_actual_recovery_frame_reduction() -> None:
    baseline = _run(job_id="baseline", frames=1800)
    candidate = _run(job_id="candidate", frames=1800)

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is False
    assert result["frames"]["reduction_observed"] is False
    assert "candidate did not reduce recovery observed_frames" in result["blockers"]


def test_identity_and_bodyprint_deltas_are_reported_not_silently_thresholded() -> None:
    baseline = _run(job_id="baseline", frames=3600, identity=_identity(sharpness=0.8))
    candidate = _run(job_id="candidate", frames=1800, identity=_identity(sharpness=0.7))
    candidate.recovery["bodyprint"]["height"] = 1.68

    result = compare_runs(baseline, candidate)

    assert result["machine_evidence_pass"] is True
    assert result["identity_metric_deltas_candidate_minus_baseline"]["quality.mean_sharpness"] < 0
    assert result["bodyprint_numeric_deltas_candidate_minus_baseline"]["bodyprint.height"] < 0
    assert result["human_visual_review_required"] is True


def test_job_timing_and_clone_pipeline_timing_are_separate_semantics(tmp_path: Path) -> None:
    job = {
        "started_utc": "2026-09-02T10:00:00Z",
        "completed_utc": "2026-09-02T12:30:00Z",
    }
    log = tmp_path / "job.log"
    log.write_text(
        "noise\n"
        "[2026-09-02T10:05:00Z] RUN\n"
        "clone output\n"
        "[2026-09-02T12:00:00Z] RUN\n"
        "[2026-09-02T12:10:00Z] RUN\n",
        encoding="utf-8",
    )

    assert _total_seconds(job) == 9000.0
    assert _clone_pipeline_seconds(log) == 6900.0


def test_numeric_delta_walk_ignores_booleans_and_reports_nested_numbers() -> None:
    result = _numeric_deltas(
        {"a": {"x": 1.0, "flag": True}, "b": 2},
        {"a": {"x": 1.25, "flag": False}, "b": 1},
    )
    assert result == {"a.x": 0.25, "b": -1.0}
