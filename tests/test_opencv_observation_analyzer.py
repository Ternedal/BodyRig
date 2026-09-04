from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.bridges.opencv_observation_analyzer import (
    _analyze_source,
    _face_score,
    _full_body_score,
    _nms,
    _read_manifest_counts,
)


def test_full_body_score_rewards_visible_margins_and_penalizes_clipping():
    centered = _full_body_score((250, 80, 220, 720), 720, 900)
    clipped = _full_body_score((0, 0, 700, 895), 720, 900)
    tiny = _full_body_score((300, 300, 70, 120), 720, 900)

    assert 0.0 <= tiny < centered <= 1.0
    assert clipped < centered


def test_nms_keeps_distinct_people_and_deduplicates_overlapping_boxes():
    rows = [
        ((10, 10, 100, 200), 0.95),
        ((14, 14, 100, 200), 0.80),
        ((300, 20, 100, 200), 0.70),
    ]
    kept = _nms(rows, threshold=0.45)

    assert len(kept) == 2
    assert kept[0][0] == (10, 10, 100, 200)
    assert {item[0] for item in kept} == {(10, 10, 100, 200), (300, 20, 100, 200)}


def test_face_score_is_zero_without_face_and_positive_with_face():
    person = (0, 0, 200, 400)
    assert _face_score(None, person) == 0.0
    small = _face_score((50, 20, 30, 30), person)
    large = _face_score((40, 15, 70, 70), person)
    assert 0.0 < small < large <= 1.0


def test_multi_performer_source_is_rejected_before_any_cv_work(tmp_path: Path):
    # The simple built-in analyzer must not guess which visible person is the
    # requested Stash performer. performer_count != 1 is an immediate no-op,
    # so this intentionally passes an object that could not behave like cv2.
    class MustNotBeUsed:
        def __getattr__(self, name):  # pragma: no cover - should never execute
            raise AssertionError(f"cv2 was touched for multi-performer input: {name}")

    result = _analyze_source(
        MustNotBeUsed(),
        path=tmp_path / "does-not-need-to-exist.mp4",
        source_id="s001",
        requested_duration=60.0,
        performer_count=2,
        hog=MustNotBeUsed(),
        front=MustNotBeUsed(),
        profile=MustNotBeUsed(),
    )
    assert result == []


def test_manifest_performer_binding_and_counts_are_strict(tmp_path: Path):
    manifest = {
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "source_kind": "stash-local",
        "performer": {"id": "7", "name": "Alice", "disambiguation": ""},
        "stash_version": "test",
        "candidate_count": 2,
        "selected": [
            {"scene_id": "1", "performer_count": 1},
            {"scene_id": "2", "performer_count": 3},
        ],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert _read_manifest_counts(path, "7") == [1, 3]

    with pytest.raises(RuntimeError, match="performer does not match"):
        _read_manifest_counts(path, "99")

    manifest["selected"][0]["performer_count"] = 0
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be positive"):
        _read_manifest_counts(path, "7")
