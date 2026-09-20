from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_negative_confusion_review.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_negative_confusion_review_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_nearest_reports_group_and_reference_confusion() -> None:
    ab = types.SimpleNamespace(_cosine=_cosine)
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:2", "embedding": [0.0, 1.0]},
        {"reference_index": 2, "group_id": "scene:2", "embedding": [0.1, 0.9]},
    ]
    group_centroids = {
        "scene:1": [1.0, 0.0],
        "scene:2": [0.0, 1.0],
    }

    result = diagnostic._nearest(
        ab=ab,
        vector=[0.05, 0.95],
        positives=positives,
        group_centroids=group_centroids,
    )

    assert result["nearest_group_id"] == "scene:2"
    assert result["nearest_reference_index"] == 1
    assert result["nearest_reference_group_id"] == "scene:2"
    assert result["nearest_group_cosine"] == 0.95
    assert result["top_group_scores"][0]["group_id"] == "scene:2"


def test_review_html_marks_diagnostic_boundary_and_uses_exact_crops() -> None:
    rows = [
        {
            "negative_index": 3,
            "subject_performer_id": "99",
            "timestamp_seconds": 12.5,
            "eye": "left",
            "negative_image": "negative/negative-03.png",
            "source_key": "scene:99:E:/negative.mp4",
            "current_target_cosine": 0.31,
            "alternate_target_cosine": 0.27,
            "current": {
                "nearest_group_id": "scene:978",
                "nearest_group_cosine": 0.61,
                "nearest_reference_index": 4,
                "nearest_reference_cosine": 0.66,
            },
            "alternate": {
                "nearest_group_id": "scene:978",
                "nearest_group_cosine": 0.53,
                "nearest_reference_index": 5,
                "nearest_reference_cosine": 0.58,
            },
        }
    ]
    document = diagnostic._build_html(
        performer_id="42",
        rows=rows,
        positive_images={
            4: "positive/current.png",
            5: "positive/alternate.png",
        },
    )

    assert "aligned 112x112 face crop" in document
    assert "scene:978" in document
    assert "negative/negative-03.png" in document
    assert "positive/current.png" in document
    assert "positive/alternate.png" in document
    assert "diagnostic only" in document.lower()
    assert "grants no matching, training, photoreal or production authority" in document


def test_safe_slug_cannot_escape_review_directory() -> None:
    value = diagnostic._safe_slug("../../scene:978\\target")
    assert "/" not in value
    assert "\\" not in value
    assert ".." not in value
