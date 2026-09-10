from __future__ import annotations

import pytest

from bodyrig.bridges.phalp_track_mask import (
    PhalpTrackMaskError,
    canonicalize_attested_track_masks,
    mask_sha256,
)


def _mask(height: int = 4, width: int = 5) -> list[list[int]]:
    # Deliberately asymmetric so row/column-order bugs are visible.
    rows = [[0 for _ in range(width)] for _ in range(height)]
    rows[1][1] = 1
    rows[2][1] = 1
    rows[2][2] = 1
    return rows


def _frame(time: int, *, tid: int = 7, age: int = 0, mask_token: str = "m") -> dict:
    return {
        "time": time,
        "tid": [tid],
        "tracked_time": [age],
        "bbox": [[1.0, 1.0, 3.0, 3.0]],
        "mask": [mask_token],
        "conf": [0.91],
        "size": [[4, 5]],
    }


def test_attested_mask_exports_only_requested_observed_track_samples() -> None:
    frames = {
        "f0": _frame(0),
        "f1": _frame(1),
        "f2": _frame(2),
    }
    result = canonicalize_attested_track_masks(
        frames,
        fps=1.0,
        source_index=0,
        selected_track_id="s00-t7",
        requested_timestamps_ms=[0, 2000],
        decode_mask=lambda raw: _mask(),
    )
    assert result["selected_track_id"] == "s00-t7"
    assert result["requested_timestamps_ms"] == [0, 2000]
    assert result["all_samples_observed"] is True
    assert result["hidden_pixels_inferred"] is False
    assert result["generative_pixels_used"] is False
    assert len(result["samples"]) == 2
    sample = result["samples"][0]
    assert sample["mask_rle"]["size"] == [4, 5]
    # Column-major bits are: 0000, 0110, 0010, 0000, 0000.
    assert sample["mask_rle"]["counts"] == [5, 2, 3, 1, 9]
    assert sample["mask_pixel_count"] == 3
    assert sample["mask_bbox_ltrb"] == [1, 1, 3, 3]
    assert sample["mask_sha256"] == mask_sha256(height=4, width=5, counts=[5, 2, 3, 1, 9])


def test_attested_mask_rejects_predicted_or_missing_requested_state() -> None:
    frames = {"f0": _frame(0, age=1)}
    with pytest.raises(PhalpTrackMaskError, match="not exactly one observed detection"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s00-t7",
            requested_timestamps_ms=[0],
            decode_mask=lambda raw: _mask(),
        )


def test_attested_mask_rejects_duplicate_target_at_requested_timestamp() -> None:
    frame = _frame(0)
    for key in ("tid", "tracked_time", "bbox", "mask", "conf", "size"):
        frame[key] = [frame[key][0], frame[key][0]]
    frames = {"f0": frame}
    with pytest.raises(PhalpTrackMaskError, match="not exactly one observed detection"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s00-t7",
            requested_timestamps_ms=[0],
            decode_mask=lambda raw: _mask(),
        )


def test_attested_mask_rejects_nonbinary_or_wrong_size_mask() -> None:
    frames = {"f0": _frame(0)}
    bad = _mask()
    bad[0][0] = 2
    with pytest.raises(PhalpTrackMaskError, match="non-binary"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s00-t7",
            requested_timestamps_ms=[0],
            decode_mask=lambda raw: bad,
        )
    with pytest.raises(PhalpTrackMaskError, match="height differs"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s00-t7",
            requested_timestamps_ms=[0],
            decode_mask=lambda raw: [[0] * 5 for _ in range(3)],
        )


def test_attested_mask_requires_sorted_unique_bounded_timestamps_and_matching_track_prefix() -> None:
    frames = {"f0": _frame(0)}
    with pytest.raises(PhalpTrackMaskError, match="sorted and unique"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s00-t7",
            requested_timestamps_ms=[1000, 0],
            decode_mask=lambda raw: _mask(),
        )
    with pytest.raises(PhalpTrackMaskError, match="invalid for source index"):
        canonicalize_attested_track_masks(
            frames,
            fps=1.0,
            source_index=0,
            selected_track_id="s01-t7",
            requested_timestamps_ms=[0],
            decode_mask=lambda raw: _mask(),
        )
