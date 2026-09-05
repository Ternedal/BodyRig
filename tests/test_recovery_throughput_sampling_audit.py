from __future__ import annotations

import json
from pathlib import Path

from bodyrig.bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_POLICY, RECOVERY_TEMPORAL_SAMPLING_REVISION
from bodyrig.recovery_throughput_sampling_audit import (
    BASELINE_BODYRIG_REVISION,
    RunEvidence,
    _load_job,
    compare_runs,
    expected_candidate_revision,
)


BASELINE_REVISION = "4dh:" + "1" * 40 + ";phalp:" + "2" * 40 + ";nmr:" + "3" * 40
CANDIDATE_REVISION = f"{BASELINE_REVISION};s:{RECOVERY_TEMPORAL_SAMPLING_REVISION}"
CANDIDATE_BODYRIG_REVISION = "9" * 40


def _run(
    *,
    job_id: str,
    revision: str,
    frames: int,
    track_id: str = "s00-t1",
    source_sha: str = "a" * 64,
    segment_sha: str = "b" * 64,
    bodyrig_revision: str | None = None,
) -> RunEvidence:
    if bodyrig_revision is None:
        bodyrig_revision = CANDIDATE_BODYRIG_REVISION if revision == CANDIDATE_REVISION else BASELINE_BODYRIG_REVISION
    binding = {
        "source": {
            "kind": "stash-performer",
            "performer_id": "42",
            "performer_name": "Fixture Person",
            "disambiguation": "",
        },
        "component": {
            "kind": "body",
            "revision_id": "body-r0001",
            "artifact_sha256": "c" * 64,
        },
        "evidence": {
            "source_files": [
                {"scene_id": "100", "name": "source.mp4", "sha256": source_sha},
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
                "sha256": segment_sha,
            }
        ]
    }
    return RunEvidence(
        job={
            "job_id": job_id,
            "person_id": "person-" + "1" * 32,
            "bodyrig_revision": bodyrig_revision,
        },
        binding=binding,
        selection=selection,
        segments=segments,
        recovery={
            "adapter": "4dhumans-hmr2-phalp",
            "revision": revision,
            "track_id": track_id,
            "observed_frames": frames,
            "bodyprint": {"shape": {"shoulder_width_ratio": 0.25}},
        },
        identity={
            "capture": {"sample_count": 20},
            "coverage": {"face": 0.9, "full_body": 0.8},
            "quality": {"mean_sharpness": 0.8},
        },
        acceptance={"automated_pass": True},
        fidelity={"views": ["front-full", "three-quarter-full", "side-full", "face-front"]},
        review={"semantics": "visual-fidelity-not-identity-verification"},
        package_sha256="c" * 64,
        total_seconds=6000.0,
        clone_pipeline_seconds=5000.0,
    )


def _compare(baseline: RunEvidence, candidate: RunEvidence) -> dict:
    return compare_runs(
        baseline,
        candidate,
        expected_candidate_bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
    )


def test_expected_candidate_revision_keeps_exact_upstream_revision_and_compact_sampling_suffix() -> None:
    assert expected_candidate_revision(BASELINE_REVISION) == CANDIDATE_REVISION
    assert len(CANDIDATE_REVISION) <= 160


def test_machine_gate_accepts_only_exact_source_segment_track_sampling_and_software_authority() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800),
    )

    assert result["machine_evidence_pass"] is True
    assert result["software_authority_bound"] is True
    assert result["baseline_bodyrig_revision"] == BASELINE_BODYRIG_REVISION
    assert result["candidate_bodyrig_revision"] == CANDIDATE_BODYRIG_REVISION
    assert result["source_authority_equal"] is True
    assert result["native_observation_segment_bytes_equal"] is True
    assert result["recovery_track_equal"] is True
    assert result["frames"]["ratio"] == 0.5
    assert result["sampling_policy"] == RECOVERY_TEMPORAL_SAMPLING_POLICY
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
    assert result["human_visual_review_required"] is True
    assert result["decision"] == "eligible-for-human-ab-review"


def test_old_baseline_software_authority_is_blocked() -> None:
    result = _compare(
        _run(
            job_id="baseline",
            revision=BASELINE_REVISION,
            frames=3600,
            bodyrig_revision="8" * 40,
        ),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800),
    )
    assert result["machine_evidence_pass"] is False
    assert result["software_authority_bound"] is False
    assert "baseline BodyRig revision is not the exact uncapped Person Studio authority" in result["blockers"]


def test_candidate_must_match_exact_comparator_checkout_authority() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(
            job_id="candidate",
            revision=CANDIDATE_REVISION,
            frames=1800,
            bodyrig_revision="7" * 40,
        ),
    )
    assert result["machine_evidence_pass"] is False
    assert result["software_authority_bound"] is False
    assert "candidate BodyRig revision does not match the exact comparator checkout authority" in result["blockers"]


def test_arbitrary_recovery_change_is_blocked_even_when_faster() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(
            job_id="candidate",
            revision=BASELINE_REVISION + ";x:other",
            frames=900,
            bodyrig_revision=CANDIDATE_BODYRIG_REVISION,
        ),
    )
    assert result["machine_evidence_pass"] is False
    assert "candidate recovery revision is not the exact versioned sampling derivative of baseline" in result["blockers"]
    assert result["promotion_authority"] is False


def test_source_file_sha_change_is_blocked() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600, source_sha="a" * 64),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800, source_sha="d" * 64),
    )
    assert result["machine_evidence_pass"] is False
    assert "baseline and candidate exact source-file SHA evidence differ" in result["blockers"]


def test_native_segment_byte_change_is_blocked() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600, segment_sha="b" * 64),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800, segment_sha="e" * 64),
    )
    assert result["machine_evidence_pass"] is False
    assert "native observation segment identity/bytes differ" in result["blockers"]


def test_track_change_is_blocked() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600, track_id="s00-t1"),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=1800, track_id="s00-t2"),
    )
    assert result["machine_evidence_pass"] is False
    assert "recovery track_id differs" in result["blockers"]


def test_no_frame_reduction_is_blocked() -> None:
    result = _compare(
        _run(job_id="baseline", revision=BASELINE_REVISION, frames=3600),
        _run(job_id="candidate", revision=CANDIDATE_REVISION, frames=3600),
    )
    assert result["machine_evidence_pass"] is False
    assert "candidate did not reduce recovery observed_frames" in result["blockers"]


def test_current_succeeded_ui_job_schema_requires_exact_bodyrig_revision_not_legacy_performer_fields(tmp_path: Path) -> None:
    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": "job-" + "1" * 32,
        "kind": "body-build",
        "person_id": "person-" + "1" * 32,
        "status": "succeeded",
        "bodyrig_revision": BASELINE_BODYRIG_REVISION,
        "body_revision": "body-r0001",
        "canonical_body_id": "bodyid-" + "1" * 24,
        "clone_output": str(tmp_path / "clone-output"),
        "acceptance_dir": str(tmp_path / "acceptance"),
        "fidelity_dir": str(tmp_path / "fidelity-review"),
        "source_binding_sha256": "a" * 64,
        "body_review_sha256": "b" * 64,
        "log_path": str(tmp_path / "job.log"),
        "started_utc": "2026-09-03T00:00:00Z",
        "completed_utc": "2026-09-03T01:00:00Z",
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")

    loaded = _load_job(path)
    assert loaded["bodyrig_revision"] == BASELINE_BODYRIG_REVISION
    assert loaded["body_revision"] == "body-r0001"
    assert "performer_id" not in loaded
    assert "package_sha256" not in loaded
