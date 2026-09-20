from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_identity_group_geometry_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_identity_group_geometry_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _normalize(values: list[float]) -> list[float]:
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _centroid(vectors: list[list[float]]) -> list[float]:
    dimension = len(vectors[0])
    return _normalize(
        [
            sum(vector[index] for vector in vectors) / len(vectors)
            for index in range(dimension)
        ]
    )


def _flip() -> object:
    return types.SimpleNamespace(_cosine=_cosine, _centroid=_centroid)


def test_analyze_variant_reports_group_geometry_and_negative_overlap() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {
            "reference_index": 1,
            "group_id": "scene:1",
            "embedding": _normalize([0.98, 0.08]),
        },
        {
            "reference_index": 2,
            "group_id": "scene:2",
            "embedding": _normalize([0.90, 0.30]),
        },
        {
            "reference_index": 3,
            "group_id": "scene:3",
            "embedding": _normalize([0.65, 0.76]),
        },
    ]
    negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "embedding": _normalize([-1.0, 0.0]),
        },
        {
            "negative_index": 1,
            "subject_performer_id": "100",
            "embedding": _normalize([0.30, 0.95]),
        },
    ]

    result = diagnostic._analyze_variant(
        flip=_flip(),
        positives=positives,
        negatives=negatives,
    )

    assert result["positive_reference_count"] == 4
    assert result["positive_group_count"] == 3
    assert result["negative_observation_count"] == 2
    assert len(result["group_rows"]) == 3
    assert len(result["pairwise_positive_group_cosines"]) == 3
    assert len(result["negative_to_positive_group_cosines"]) == 6
    assert len(result["reference_leave_group_out"]) == 4

    scene1 = next(
        row for row in result["group_rows"] if row["group_id"] == "scene:1"
    )
    assert scene1["reference_count"] == 2
    assert scene1["within_group_cosine"] is not None
    assert scene1["reference_leave_group_out_cosine"] is not None
    assert scene1["highest_negative_index"] in {0, 1}
    assert isinstance(scene1["local_group_separation_margin"], float)


def test_compare_variants_reports_directional_deltas() -> None:
    current = {
        "group_rows": [
            {
                "group_id": "scene:1",
                "reference_count": 2,
                "centroid_to_leave_group_out_target_cosine": 0.20,
                "highest_negative_group_cosine": 0.30,
                "local_group_separation_margin": -0.10,
                "highest_negative_index": 0,
                "nearest_positive_group_id": "scene:2",
            }
        ]
    }
    alternate = {
        "group_rows": [
            {
                "group_id": "scene:1",
                "reference_count": 2,
                "centroid_to_leave_group_out_target_cosine": 0.35,
                "highest_negative_group_cosine": 0.25,
                "local_group_separation_margin": 0.10,
                "highest_negative_index": 1,
                "nearest_positive_group_id": "scene:3",
            }
        ]
    }

    result = diagnostic._compare_variants(
        current=current,
        alternate=alternate,
    )

    assert result == [
        {
            "group_id": "scene:1",
            "reference_count": 2,
            "current_centroid_lgo": 0.20,
            "alternate_centroid_lgo": 0.35,
            "delta_centroid_lgo": 0.15,
            "current_highest_negative_group_cosine": 0.30,
            "alternate_highest_negative_group_cosine": 0.25,
            "delta_highest_negative_group_cosine": -0.05,
            "current_local_group_separation_margin": -0.10,
            "alternate_local_group_separation_margin": 0.10,
            "delta_local_group_separation_margin": 0.20,
            "current_highest_negative_index": 0,
            "alternate_highest_negative_index": 1,
            "current_nearest_positive_group_id": "scene:2",
            "alternate_nearest_positive_group_id": "scene:3",
        }
    ]


def test_summary_handles_singletons_without_inventing_within_group_pairs() -> None:
    assert diagnostic._summary([]) is None
    assert diagnostic._summary([0.5]) == {
        "min": 0.5,
        "median": 0.5,
        "max": 0.5,
    }
