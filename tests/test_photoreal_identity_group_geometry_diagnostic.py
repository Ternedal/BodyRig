from __future__ import annotations

import importlib.util
import json
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


def test_score_model_witnesses_identifies_reference_floor_and_negative_ceiling() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:1", "embedding": _normalize([0.95, 0.1])},
        {"reference_index": 2, "group_id": "scene:2", "embedding": _normalize([0.8, 0.6])},
        {"reference_index": 3, "group_id": "scene:3", "embedding": _normalize([0.7, 0.7])},
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
            "embedding": _normalize([0.4, 0.9]),
        },
    ]
    result = diagnostic._score_model_witnesses(
        flip=_flip(),
        positives=positives,
        negatives=negatives,
    )

    current = result["current-reference-weighted"]
    assert current["positive_floor_witness"]["reference_index"] in {0, 1, 2, 3}
    assert current["negative_ceiling_witness"]["negative_index"] in {0, 1}
    assert current["observed_separation_margin"] == pytest.approx(
        current["positive_floor_witness"]["score"]
        - current["negative_ceiling_witness"]["score"],
        abs=1e-9,
    )
    prototype = result["nearest-group-prototype"]
    assert "neighbor_group_id" in prototype["positive_floor_witness"]
    assert "nearest_group_id" in prototype["negative_ceiling_witness"]


def test_reference_ablation_only_removes_refs_from_multi_reference_groups() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:1", "embedding": _normalize([0.95, 0.1])},
        {"reference_index": 2, "group_id": "scene:2", "embedding": _normalize([0.9, 0.3])},
        {"reference_index": 3, "group_id": "scene:3", "embedding": _normalize([0.8, 0.6])},
        {"reference_index": 4, "group_id": "scene:805", "embedding": [0.0, 1.0]},
        {"reference_index": 5, "group_id": "scene:889", "embedding": [0.0, 1.0]},
        {"reference_index": 6, "group_id": "scene:978", "embedding": [0.0, 1.0]},
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
            removed_ref_1 = all(
                int(item["reference_index"]) != 1
                for item in subset
            )
            margin = 0.10 if removed_ref_1 else 0.01
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

    result = diagnostic._reference_ablation_after_removed_groups(
        flip=Flip(),
        positives=positives,
        negatives=negatives,
        removed_group_ids=["scene:805", "scene:889", "scene:978"],
    )

    assert result["baseline_remaining_group_count"] == 3
    assert result["baseline_remaining_reference_count"] == 4
    assert result["removable_reference_count"] == 2
    assert {
        item["removed_reference_index"]
        for item in result["ranked_single_reference_ablation"]
    } == {0, 1}
    assert result["best_single_reference_ablation"][
        "removed_reference_index"
    ] == 1
    assert result["first_all_models_pass"]["removed_reference_index"] == 1
    assert result["human_attested_valid_reference_is_not_rejected"] is True
    assert result["identity_bank_mutation_authority"] is False


def test_boundary_witness_review_marks_witnesses_and_stereo_siblings(tmp_path: Path) -> None:
    current_boundary = {
        "baseline_witnesses": {
            "current-reference-weighted": {
                "positive_floor_witness": {
                    "reference_index": 18,
                    "group_id": "scene:909",
                }
            }
        }
    }
    alternate_boundary = {
        "baseline_witnesses": {
            "current-reference-weighted": {
                "positive_floor_witness": {
                    "reference_index": 9,
                    "group_id": "scene:709",
                }
            }
        }
    }
    quality = {
        "det_score": 0.9,
        "view_bin": "front",
        "pose": {
            "pitch_degrees": 1.0,
            "yaw_degrees": 2.0,
            "roll_degrees": 3.0,
        },
        "bbox_min_dimension_pixels": 64.0,
        "face_center_offset_fraction": 0.1,
        "frame_sharpness": 10.0,
        "face_crop_sharpness": 20.0,
    }
    current = [
        {
            "reference_index": 8,
            "group_id": "scene:709",
            "source_key": "scene:709",
            "timestamp_seconds": 12.0,
            "eye": "left",
            "frame_sha256": "a" * 64,
            "quality": quality,
            "embedding": [1.0, 0.0],
        },
        {
            "reference_index": 9,
            "group_id": "scene:709",
            "source_key": "scene:709",
            "timestamp_seconds": 12.0,
            "eye": "right",
            "frame_sha256": "b" * 64,
            "quality": quality,
            "embedding": _normalize([0.9, 0.1]),
        },
        {
            "reference_index": 17,
            "group_id": "scene:909",
            "source_key": "scene:909",
            "timestamp_seconds": 34.0,
            "eye": "left",
            "frame_sha256": "c" * 64,
            "quality": quality,
            "embedding": [1.0, 0.0],
        },
        {
            "reference_index": 18,
            "group_id": "scene:909",
            "source_key": "scene:909",
            "timestamp_seconds": 34.0,
            "eye": "right",
            "frame_sha256": "d" * 64,
            "quality": quality,
            "embedding": _normalize([0.8, 0.2]),
        },
    ]
    alternate = [
        {**item, "embedding": _normalize([item["embedding"][0], item["embedding"][1] + 0.01])}
        for item in current
    ]

    class Confusion:
        @staticmethod
        def _write_png(_runtime: object, path: Path, _image: object) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")

    media = {
        index: {
            "frame": object(),
            "aligned": object(),
            "viewport_id": f"viewport-{index}",
        }
        for index in (8, 9, 17, 18)
    }

    result = diagnostic._write_boundary_witness_review(
        confusion=Confusion(),
        runtime=object(),
        output_root=tmp_path / "review",
        current_boundary=current_boundary,
        alternate_boundary=alternate_boundary,
        current_positives=current,
        alternate_positives=alternate,
        review_media=media,
    )

    assert result["witness_indices"] == {
        "w600k-r50": 18,
        "antelopev2-glintr100": 9,
    }
    document = (tmp_path / "review" / "review-index.html").read_text(
        encoding="utf-8"
    )
    assert "ref 18" in document
    assert "ref 9" in document
    assert "stereo sibling=[17]" in document
    assert "stereo sibling=[8]" in document

    payload = json.loads(
        (tmp_path / "review" / "boundary-witness-review.json").read_text(
            encoding="utf-8"
        )
    )
    ref18 = next(
        item for item in payload["rows"] if item["reference_index"] == 18
    )
    assert ref18["witness_for"] == ["w600k-r50"]
    assert ref18[
        "opposite_eye_same_timestamp_sibling_reference_indices"
    ] == [17]
    assert payload["reference_rejection_authority"] is False
    assert payload["identity_bank_mutation_authority"] is False


def test_fused_embedding_cosine_matches_weighted_recognizer_cosines() -> None:
    left_current = _normalize([1.0, 0.2])
    right_current = _normalize([0.8, 0.6])
    left_alternate = _normalize([0.1, 1.0])
    right_alternate = _normalize([0.7, 0.7])

    fused_left = diagnostic._fused_embedding(
        left_current,
        left_alternate,
        current_weight=0.5,
    )
    fused_right = diagnostic._fused_embedding(
        right_current,
        right_alternate,
        current_weight=0.5,
    )

    expected = (
        0.5 * _cosine(left_current, right_current)
        + 0.5 * _cosine(left_alternate, right_alternate)
    )
    assert _cosine(fused_left, fused_right) == pytest.approx(
        expected,
        abs=1e-12,
    )
    assert sum(value * value for value in fused_left) == pytest.approx(
        1.0,
        abs=1e-12,
    )


def test_recognizer_fusion_sweep_retains_all_evidence_and_finds_best_weight() -> None:
    current_positives = [
        {
            "reference_index": 0,
            "group_id": "scene:1",
            "frame_sha256": "a" * 64,
            "embedding": [1.0, 0.0],
        },
        {
            "reference_index": 1,
            "group_id": "scene:2",
            "frame_sha256": "b" * 64,
            "embedding": _normalize([0.9, 0.3]),
        },
    ]
    alternate_positives = [
        {
            **current_positives[0],
            "embedding": [0.0, 1.0],
        },
        {
            **current_positives[1],
            "embedding": _normalize([0.3, 0.9]),
        },
    ]
    current_negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "frame_sha256": "c" * 64,
            "embedding": _normalize([-1.0, 0.0]),
        }
    ]
    alternate_negatives = [
        {
            **current_negatives[0],
            "embedding": _normalize([0.0, -1.0]),
        }
    ]

    class Flip:
        _cosine = staticmethod(_cosine)
        _centroid = staticmethod(_centroid)

        @staticmethod
        def _score_models(
            positives: list[dict[str, object]],
            negatives: list[dict[str, object]],
        ) -> dict[str, dict[str, object]]:
            weight_signal = float(positives[0]["embedding"][0]) ** 2
            margin = 0.2 - abs(weight_signal - 0.5)
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

    original_witness = diagnostic._score_model_witnesses
    try:
        diagnostic._score_model_witnesses = lambda **_kwargs: {
            "diagnostic": True
        }
        result = diagnostic._recognizer_fusion_sweep(
            flip=Flip(),
            current_positives=current_positives,
            alternate_positives=alternate_positives,
            current_negatives=current_negatives,
            alternate_negatives=alternate_negatives,
            weight_steps=4,
        )
    finally:
        diagnostic._score_model_witnesses = original_witness

    assert result["weight_count"] == 5
    assert result["all_positive_evidence_retained"] is True
    assert result["all_negative_evidence_retained"] is True
    assert result["best_weight"]["current_weight"] == pytest.approx(0.5)
    assert result["best_weight"]["alternate_weight"] == pytest.approx(0.5)
    assert result["best_weight"]["all_models_meet_margin"] is True
    assert result["negative_observation_count_below_production_minimum"] is True


def test_fusion_rejects_mismatched_evidence_provenance() -> None:
    current_positive = {
        "reference_index": 0,
        "group_id": "scene:1",
        "frame_sha256": "a" * 64,
        "embedding": [1.0, 0.0],
    }
    alternate_positive = {
        **current_positive,
        "frame_sha256": "b" * 64,
    }
    negative = {
        "negative_index": 0,
        "subject_performer_id": "99",
        "frame_sha256": "c" * 64,
        "embedding": [-1.0, 0.0],
    }

    with pytest.raises(
        diagnostic.PhotorealIdentityGroupGeometryDiagnosticError,
        match="positive provenance mismatch",
    ):
        diagnostic._recognizer_fusion_sweep(
            flip=types.SimpleNamespace(),
            current_positives=[current_positive],
            alternate_positives=[alternate_positive],
            current_negatives=[negative],
            alternate_negatives=[negative],
            weight_steps=2,
        )


def test_top_k_mean_selects_highest_support_values() -> None:
    assert diagnostic._top_k_mean([0.1, 0.9, 0.5, 0.3], 2) == pytest.approx(0.7)
    with pytest.raises(
        diagnostic.PhotorealIdentityGroupGeometryDiagnosticError,
        match="outside available group evidence",
    ):
        diagnostic._top_k_mean([0.1, 0.2], 3)


def test_group_consensus_sweep_retains_all_evidence_and_can_find_passing_k() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:2", "embedding": _normalize([0.95, 0.1])},
        {"reference_index": 2, "group_id": "scene:3", "embedding": _normalize([0.9, 0.2])},
        {"reference_index": 3, "group_id": "scene:4", "embedding": _normalize([0.85, 0.3])},
    ]
    negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "embedding": _normalize([0.4, 0.9]),
        }
    ]

    result = diagnostic._group_consensus_sweep(
        flip=_flip(),
        positives=positives,
        negatives=negatives,
    )

    assert result["support_k_min"] == 1
    assert result["support_k_max"] == 3
    assert result["all_positive_references_retained"] is True
    assert result["all_positive_groups_retained"] is True
    assert result["all_negative_observations_retained"] is True
    assert result["negative_observation_count_below_production_minimum"] is True
    assert len(result["ranked_support"]) == 3
    assert all(
        item["positive_score_count"] == 4
        for item in result["ranked_support"]
    )
    assert all(
        item["negative_score_count"] == 1
        for item in result["ranked_support"]
    )


def test_group_consensus_positive_reference_cannot_use_own_group() -> None:
    positives = [
        {"reference_index": 0, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 1, "group_id": "scene:1", "embedding": [1.0, 0.0]},
        {"reference_index": 2, "group_id": "scene:2", "embedding": [0.0, 1.0]},
        {"reference_index": 3, "group_id": "scene:3", "embedding": [-1.0, 0.0]},
    ]
    negatives = [
        {
            "negative_index": 0,
            "subject_performer_id": "99",
            "embedding": [0.0, -1.0],
        }
    ]

    result = diagnostic._group_consensus_sweep(
        flip=_flip(),
        positives=positives,
        negatives=negatives,
    )

    k1 = next(
        item
        for item in result["ranked_support"]
        if item["support_k"] == 1
    )
    # The scene:1 references must be scored only against scene:2/scene:3;
    # their identical scene:1 sibling cannot inflate support.
    assert k1["positive_floor_witness"]["reference_index"] in {0, 1, 2, 3}
    scene1_scores = []
    grouped = {
        "scene:1": _centroid([[1.0, 0.0], [1.0, 0.0]]),
        "scene:2": [0.0, 1.0],
        "scene:3": [-1.0, 0.0],
    }
    for item in positives[:2]:
        scene1_scores.append(
            max(
                _cosine(item["embedding"], grouped["scene:2"]),
                _cosine(item["embedding"], grouped["scene:3"]),
            )
        )
    assert scene1_scores == [0.0, 0.0]
