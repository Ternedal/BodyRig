from __future__ import annotations

import pytest

from bodyrig.photoreal_identity_negative_verify import (
    PhotorealIdentityNegativeVerifyError,
    verify_identity_negative_sources,
)
from bodyrig.photoreal_source_verify import (
    PhotorealSourceVerifyError,
    verify_inventory_sources,
)


def _source_inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "videos": [{"scene_id": "s1", "path": "source.mp4", "size_bytes": 1}],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _negative_inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-inventory",
        "version": 1,
        "target_performer_id": "42",
        "label_authority": "stash-single-performer-other-id-v1",
        "sources": [
            {
                "source_key": "scene:99:negative.mp4",
                "subject_performer_id": "99",
                "subject_performer_name": "Negative 99",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "path": "negative.mp4",
                "size_bytes": 1,
                "width": 1,
                "height": 1,
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 1.0,
                "frame_rate": 1.0,
            }
        ],
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_source_verify_rejects_boolean_v1() -> None:
    inventory = _source_inventory()
    inventory["version"] = True
    with pytest.raises(PhotorealSourceVerifyError, match="format/version"):
        verify_inventory_sources(
            inventory,
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 1,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verify_rejects_boolean_v1() -> None:
    inventory = _negative_inventory()
    inventory["version"] = True
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="format/version"):
        verify_identity_negative_sources(
            inventory,
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 1,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verify_rejects_non_string_target_id() -> None:
    inventory = _negative_inventory()
    inventory["target_performer_id"] = 42
    inventory["sources"][0]["target_performer_id"] = 42
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="target performer is missing"):
        verify_identity_negative_sources(
            inventory,
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 1,
            hash_file=lambda _path: "a" * 64,
        )
