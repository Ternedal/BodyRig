from __future__ import annotations

from types import SimpleNamespace

import pytest

from bodyrig.photoreal_appearance_epoch_visual_review import (
    PhotorealAppearanceEpochVisualReviewError,
    _reproduce_observation,
    build_review_request,
    build_runtime_path_map,
)


def _source(key: str, group: str, *, kind: str = "video") -> dict[str, object]:
    return {
        "kind": kind,
        "source_id": key,
        "group_id": group,
        "path": key,
        "information_score": 100.0,
        "projection": "flat",
        "stereo_layout": "mono",
        "width": 1920,
        "height": 1080,
        "duration_seconds": 60.0,
        "frame_rate": 30.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [_source("scene:t", "group:t")],
        "evaluation": [_source("scene:e", "group:e", kind="image")],
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "sources": [
            {
                "kind": "video",
                "source_key": "scene:t",
                "resolved_path": r"E:\train.mp4",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
            {
                "kind": "image",
                "source_key": "scene:e",
                "resolved_path": r"E:\eval.jpg",
                "size_bytes": 200,
                "sha256": "b" * 64,
            },
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observation(
    *,
    source: str,
    group: str,
    split: str,
    frame: str,
    timestamp: float | None,
) -> dict[str, object]:
    return {
        "source_key": source,
        "group_id": group,
        "split": split,
        "frame_sha256": frame * 64,
        "timestamp_seconds": timestamp,
        "eye": "mono",
        "view_bin": "front",
        "coverage": ["face-front", "full-body-front"],
        "target_identity_verified": True,
        "eligible_for_teacher": True,
    }


def _frame_index() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-index",
        "version": 1,
        "performer_id": "42",
        "identity_bank_sha256": "c" * 64,
        "identity_calibration_sha256": "d" * 64,
        "analyzer_model_set_sha256": "e" * 64,
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "observations": [
            _observation(source="scene:t", group="group:t", split="train", frame="1", timestamp=1.0),
            _observation(source="scene:e", group="group:e", split="evaluation", frame="2", timestamp=None),
        ],
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _path_map() -> dict[str, object]:
    return build_runtime_path_map(
        _plan(),
        _receipt(),
        _frame_index(),
        converter=lambda path: "/mnt/e/" + path.rsplit("\\", 1)[-1],
        dataset_plan_sha256="3" * 64,
        source_receipt_sha256="4" * 64,
        frame_index_sha256="5" * 64,
    )


def test_runtime_path_map_converts_only_eligible_sources_without_source_rehash() -> None:
    result = _path_map()

    assert result["source_count"] == 2
    assert [item["source_key"] for item in result["source_paths"]] == ["scene:e", "scene:t"]
    assert all(item["resolved_path"].startswith("/mnt/e/") for item in result["source_paths"])
    assert result["source_media_rehash_performed"] is False
    assert result["build_only"] is True
    assert result["production_activation"] is False


def test_review_request_keeps_train_and_eval_for_human_review_without_granting_authority() -> None:
    result = build_review_request(
        _plan(),
        _receipt(),
        _frame_index(),
        _path_map(),
        bodyrig_revision="f" * 40,
        dataset_plan_sha256="3" * 64,
        source_receipt_sha256="4" * 64,
        frame_index_sha256="5" * 64,
    )

    assert {item["split"] for item in result["observations"]} == {"train", "evaluation"}
    assert {item["source_key"] for item in result["sources"]} == {"scene:t", "scene:e"}
    assert result["source_media_rehash_performed"] is False
    assert result["review_only"] is True
    assert result["human_appearance_epoch_review_required"] is True
    assert result["teacher_input_authorized"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_review_request_rejects_runtime_path_map_that_drops_held_out_source() -> None:
    path_map = _path_map()
    path_map["source_paths"] = [item for item in path_map["source_paths"] if item["source_key"] == "scene:t"]
    path_map["source_count"] = 1

    with pytest.raises(
        PhotorealAppearanceEpochVisualReviewError,
        match="exactly the eligible review source universe",
    ):
        build_review_request(
            _plan(),
            _receipt(),
            _frame_index(),
            path_map,
            bodyrig_revision="f" * 40,
            dataset_plan_sha256="3" * 64,
            source_receipt_sha256="4" * 64,
            frame_index_sha256="5" * 64,
        )


def test_review_rejects_boolean_frame_index_version() -> None:
    frame_index = _frame_index()
    frame_index["version"] = True

    with pytest.raises(PhotorealAppearanceEpochVisualReviewError, match="frame index format/version mismatch"):
        build_runtime_path_map(
            _plan(),
            _receipt(),
            frame_index,
            converter=lambda _path: "/mnt/e/source",
            dataset_plan_sha256="3" * 64,
            source_receipt_sha256="4" * 64,
            frame_index_sha256="5" * 64,
        )


def test_reproduce_flat_observation_requires_exact_p0_frame_sha() -> None:
    image = object()

    class Base:
        @staticmethod
        def _frame_sha(value):
            assert value is image
            return "1" * 64

    class Adapter:
        base = Base()

        @staticmethod
        def _read_frame_sample(_runtime, _source, _sample):
            return image, False

    runtime = SimpleNamespace(np=SimpleNamespace(ascontiguousarray=lambda value: value))
    result = _reproduce_observation(
        Adapter(),
        runtime,
        {"source_key": "scene:t", "projection": "flat"},
        {"frame_sha256": "1" * 64, "timestamp_seconds": 1.0, "eye": "mono"},
    )

    assert result is image


def test_reproduce_spatial_observation_matches_exact_deprojected_viewport() -> None:
    raw = object()
    wrong = object()
    target = object()

    class Base:
        @staticmethod
        def _frame_sha(value):
            return {
                wrong: "8" * 64,
                target: "9" * 64,
            }[value]

        @staticmethod
        def deproject_equirectangular_views(_runtime, value, _authority):
            assert value is raw
            return [("front", wrong), ("right", target)]

    class Adapter:
        base = Base()

        @staticmethod
        def _read_frame_sample(_runtime, _source, _sample):
            return raw, True

    runtime = SimpleNamespace(np=SimpleNamespace(ascontiguousarray=lambda value: value))
    result = _reproduce_observation(
        Adapter(),
        runtime,
        {"source_key": "scene:vr", "projection": "equi", "projection_authority": {"version": 1}},
        {"frame_sha256": "9" * 64, "timestamp_seconds": 2.0, "eye": "mono"},
    )

    assert result is target


def test_reproduce_observation_fails_closed_when_frame_sha_does_not_reappear() -> None:
    image = object()

    class Base:
        @staticmethod
        def _frame_sha(_value):
            return "0" * 64

    class Adapter:
        base = Base()

        @staticmethod
        def _read_frame_sample(_runtime, _source, _sample):
            return image, False

    runtime = SimpleNamespace(np=SimpleNamespace(ascontiguousarray=lambda value: value))
    with pytest.raises(PhotorealAppearanceEpochVisualReviewError, match="did not reproduce exactly once"):
        _reproduce_observation(
            Adapter(),
            runtime,
            {"source_key": "scene:t", "projection": "flat"},
            {"frame_sha256": "1" * 64, "timestamp_seconds": 1.0, "eye": "mono"},
        )
