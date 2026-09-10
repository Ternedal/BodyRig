from __future__ import annotations

import pytest

from bodyrig.bridges.phalp_target_isolation import (
    PhalpTargetIsolationError,
    canonicalize_target_isolation,
)


def _frames() -> dict[int, dict]:
    rows: dict[int, dict] = {}
    for index in range(5):
        target = [10.0 + index, 20.0, 100.0, 160.0]
        other = [300.0, 20.0, 80.0, 160.0]
        if index == 2:
            other = [60.0 + index, 20.0, 100.0, 160.0]
        rows[index] = {
            "time": index,
            "tid": [7, 8],
            "tracked_time": [0, 0],
            "bbox": [target, other],
            "conf": [0.95, 0.8],
        }
    return rows


def test_target_isolation_follows_explicit_human_track_and_measures_overlap() -> None:
    result = canonicalize_target_isolation(
        _frames(),
        fps=1.0,
        source_index=0,
        selected_track_id="s00-t7",
        max_samples=5,
    )
    assert result["selected_track_id"] == "s00-t7"
    assert result["identity_authority"] == "human-track-attestation"
    assert result["canonical_review_track"]["track_id"] == "s00-t7"
    assert result["observed_state_count"] == 5
    assert len(result["isolation_samples"]) == 5
    assert result["max_other_overlap_fraction"] == pytest.approx(0.52)
    assert result["severe_overlap_state_count"] == 1
    assert result["machine_identity_selection"] is False
    assert result["biometric_identity_inference_used"] is False
    assert result["target_isolated_source_authority"] is False
    assert result["photoidentity_source_evidence_authority"] is False
    assert result["reconstruction_permitted"] is False
    assert result["production_activation"] is False


def test_target_isolation_uses_only_observed_not_predicted_target_states() -> None:
    frames = _frames()
    frames[2]["tracked_time"][0] = 1
    result = canonicalize_target_isolation(
        frames,
        fps=1.0,
        source_index=0,
        selected_track_id="s00-t7",
        max_samples=4,
    )
    assert result["observed_state_count"] == 4
    assert all(sample["timestamp_ms"] != 2000 for sample in result["isolation_samples"])
    assert result["max_other_overlap_fraction"] == 0.0


def test_target_isolation_never_guesses_missing_or_other_source_track() -> None:
    with pytest.raises(PhalpTargetIsolationError, match="requested source"):
        canonicalize_target_isolation(
            _frames(), fps=1.0, source_index=0, selected_track_id="s01-t7"
        )
    with pytest.raises(PhalpTargetIsolationError, match="not uniquely reproducible"):
        canonicalize_target_isolation(
            _frames(), fps=1.0, source_index=0, selected_track_id="s00-t999"
        )


def test_target_isolation_requires_enough_observed_target_states() -> None:
    frames = _frames()
    for index in (0, 1, 2):
        frames[index]["tracked_time"][0] = 1
    with pytest.raises(PhalpTargetIsolationError, match="need at least"):
        canonicalize_target_isolation(
            frames, fps=1.0, source_index=0, selected_track_id="s00-t7"
        )


def test_target_isolation_samples_represent_full_track_not_best_only() -> None:
    frames = {}
    for index in range(100):
        frames[index] = {
            "time": index,
            "tid": [7],
            "tracked_time": [0],
            "bbox": [[float(index), 0.0, 100.0, 200.0]],
            "conf": [0.9],
        }
    result = canonicalize_target_isolation(
        frames,
        fps=10.0,
        source_index=0,
        selected_track_id="s00-t7",
        max_samples=5,
    )
    timestamps = [row["timestamp_ms"] for row in result["isolation_samples"]]
    assert timestamps[0] == 0
    assert timestamps[-1] == 9900
    assert 4500 <= timestamps[2] <= 5500
