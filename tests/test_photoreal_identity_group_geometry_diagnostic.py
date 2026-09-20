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


def test_ablation_search_is_counterfactual_and_ranks_best_worst_margin() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:2", "embedding": _normalize([0.98, 0.2])},
        {"reference_index": 2, "group_id": "scene:3", "embedding": _normalize([0.90, 0.4])},
        {"reference_index": 3, "group_id": "scene:4", "embedding": _normalize([0.0, 1.0])},
        {"reference_index": 4, "group_id": "scene:5", "embedding": _normalize([0.95, 0.1])},
    ]
    negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "embedding": _normalize([-1.0, 0.0]),
        }
    ]

    class Flip:
        _cosine = staticmethod(_cosine)
        _centroid = staticmethod(_centroid)

        @staticmethod
        def _score_models(
            subset: list[dict[str, object]],
            _negatives: list[dict[str, object]],
        ) -> dict[str, dict[str, object]]:
            removed_scene4 = all(
                item["group_id"] != "scene:4"
                for item in subset
            )
            margin = 0.20 if removed_scene4 else -0.20
            return {
                name: {
                    "observed_separation_margin": margin,
                    "would_meet_margin": margin >= 0.05,
                }
                for name in (
                    "current-reference-weighted",
                    "group-balanced-centroid-lgo",
                    "nearest-group-prototype",
                )
            }

    result = diagnostic._ablation_search(
        flip=Flip(),
        positives=positives,
        negatives=negatives,
        max_removed_groups=3,
    )

    assert result["counterfactual_only"] is True
    assert result["valid_human_attested_groups_are_not_rejected"] is True
    assert result["identity_bank_mutation_authority"] is False
    assert result["combination_count"] == 26
    assert result["by_removed_count"]["1"][0]["removed_group_ids"] == ["scene:4"]
    assert result["first_all_models_pass"]["removed_group_ids"] == ["scene:4"]


def test_ablation_search_records_named_three_group_candidate() -> None:
    positives = [
        {"reference_index": index, "group_id": group_id, "embedding": [1.0, 0.0]}
        for index, group_id in enumerate(
            [
                "scene:805",
                "scene:889",
                "scene:978",
                "scene:804",
                "scene:909",
            ]
        )
    ]
    negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "embedding": [-1.0, 0.0],
        }
    ]

    class Flip:
        _cosine = staticmethod(_cosine)
        _centroid = staticmethod(_centroid)

        @staticmethod
        def _score_models(
            _subset: list[dict[str, object]],
            _negatives: list[dict[str, object]],
        ) -> dict[str, dict[str, object]]:
            return {
                name: {
                    "observed_separation_margin": 0.1,
                    "would_meet_margin": True,
                }
                for name in (
                    "current-reference-weighted",
                    "group-balanced-centroid-lgo",
                    "nearest-group-prototype",
                )
            }

    result = diagnostic._ablation_search(
        flip=Flip(),
        positives=positives,
        negatives=negatives,
        max_removed_groups=3,
    )

    candidate = result["candidate_scene_805_889_978"]
    assert candidate is not None
    assert candidate["removed_group_ids"] == [
        "scene:805",
        "scene:889",
        "scene:978",
    ]
    assert candidate["removed_group_count"] == 3
