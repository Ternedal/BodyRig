from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_negative_verify import (
    PhotorealIdentityNegativeVerifyError,
    verify_identity_negative_sources,
)


def _inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-inventory",
        "version": 1,
        "target_performer_id": "42",
        "label_authority": "stash-single-performer-other-id-v1",
        "negative_performer_count": 2,
        "source_count": 2,
        "sources": [
            {
                "source_key": "scene:s7:E:/neg7.mp4",
                "scene_id": "s7",
                "subject_performer_id": "7",
                "subject_performer_name": "Performer 7",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "path": "E:/neg7.mp4",
                "size_bytes": 100,
                "width": 3840,
                "height": 2160,
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 60.0,
                "frame_rate": 30.0,
            },
            {
                "source_key": "image:i8:F:/neg8.jpg",
                "image_id": "i8",
                "subject_performer_id": "8",
                "subject_performer_name": "Performer 8",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "image",
                "source_binding": "direct-performer",
                "path": "F:/neg8.jpg",
                "size_bytes": 50,
                "width": 6000,
                "height": 4000,
                "megapixels": 24.0,
            },
        ],
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _verify(inventory: dict[str, object]) -> dict[str, object]:
    return verify_identity_negative_sources(
        inventory,
        path_mapping={"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"},
        exists_file=lambda _path: True,
        file_size=lambda path: 50 if str(path).lower().endswith(".jpg") else 100,
        hash_file=lambda path: ("b" if str(path).lower().endswith(".jpg") else "a") * 64,
    )


def test_point_of_use_rejects_source_count_mismatch() -> None:
    inventory = _inventory()
    inventory["source_count"] = 1
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="source_count mismatch"):
        _verify(inventory)


def test_point_of_use_rejects_negative_performer_count_mismatch() -> None:
    inventory = _inventory()
    inventory["negative_performer_count"] = 1
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="negative_performer_count mismatch"):
        _verify(inventory)


@pytest.mark.parametrize(
    ("source_index", "field", "value"),
    [
        (0, "source_key", True),
        (0, "scene_id", 7),
        (0, "subject_performer_id", 7),
        (0, "subject_performer_name", True),
        (0, "path", True),
        (0, "size_bytes", "100"),
        (0, "width", "3840"),
        (0, "duration_seconds", "60.0"),
        (0, "frame_rate", True),
        (1, "image_id", 8),
        (1, "height", 4000.0),
        (1, "megapixels", "24.0"),
    ],
)
def test_point_of_use_rejects_source_type_confusion(source_index: int, field: str, value: object) -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][source_index][field] = value
    with pytest.raises(PhotorealIdentityNegativeVerifyError):
        _verify(inventory)


def test_point_of_use_rejects_source_key_identity_substitution() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][0]["source_key"] = "scene:other:E:/neg7.mp4"
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="source_key does not match"):
        _verify(inventory)


def test_point_of_use_rejects_binding_kind_substitution_even_when_binding_is_individually_allowed() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][0]["source_binding"] = "direct-performer"
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="video binding is invalid"):
        _verify(inventory)


def test_point_of_use_preserves_canonical_inventory() -> None:
    result = _verify(_inventory())
    assert result["source_count"] == 2
    assert result["negative_performer_count"] == 2
    assert result["sources"][0]["subject_performer_id"] == "7"
    assert result["sources"][1]["subject_performer_id"] == "8"
    assert result["identity_matching_authorized"] is False
    assert result["production_activation"] is False
