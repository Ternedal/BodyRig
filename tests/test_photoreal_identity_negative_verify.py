from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_negative_verify import (
    PhotorealIdentityNegativeVerifyError,
    canonical_identity_negative_inventory_sha256,
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


def _mapping() -> dict[str, str]:
    return {"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"}


def _sizes() -> dict[str, int]:
    return {
        r"\\stash\VR_E\neg7.mp4": 100,
        r"\\stash\VR_F\neg8.jpg": 50,
    }


def _hashes() -> dict[str, str]:
    return {
        r"\\stash\VR_E\neg7.mp4": "a" * 64,
        r"\\stash\VR_F\neg8.jpg": "b" * 64,
    }


def test_negative_verifier_binds_sources_to_bytes_and_inventory() -> None:
    sizes = _sizes()
    hashes = _hashes()
    inventory = _inventory()
    result = verify_identity_negative_sources(
        inventory,
        path_mapping=_mapping(),
        exists_file=lambda path: str(path) in sizes,
        file_size=lambda path: sizes[str(path)],
        hash_file=lambda path: hashes[str(path)],
    )

    assert result["negative_inventory_sha256"] == canonical_identity_negative_inventory_sha256(inventory)
    assert result["source_count"] == 2
    assert result["negative_performer_count"] == 2
    assert result["total_bytes"] == 150
    assert result["all_sources_readable"] is True
    assert result["all_sources_sha256_bound"] is True
    assert result["calibration_only"] is True
    assert result["photoreal_teacher_input"] is False
    assert result["identity_matching_authorized"] is False
    assert result["production_activation"] is False
    assert {item["sha256"] for item in result["sources"]} == {"a" * 64, "b" * 64}


def test_negative_verifier_inventory_digest_changes_with_manifest() -> None:
    original = _inventory()
    changed = copy.deepcopy(original)
    changed["sources"][0]["path"] = "E:/different.mp4"

    assert canonical_identity_negative_inventory_sha256(original) != canonical_identity_negative_inventory_sha256(changed)


def test_negative_verifier_rejects_target_as_negative_subject() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][0]["subject_performer_id"] = "42"

    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="target performer cannot"):
        verify_identity_negative_sources(
            inventory,
            path_mapping=_mapping(),
            exists_file=lambda _path: True,
            file_size=lambda _path: 100,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verifier_rejects_non_authoritative_binding() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][1]["source_binding"] = "performer-gallery"

    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="not single-performer authoritative"):
        verify_identity_negative_sources(
            inventory,
            path_mapping=_mapping(),
            exists_file=lambda _path: True,
            file_size=lambda path: 50 if str(path).endswith("jpg") else 100,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verifier_rejects_changed_size() -> None:
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="size changed"):
        verify_identity_negative_sources(
            _inventory(),
            path_mapping=_mapping(),
            exists_file=lambda _path: True,
            file_size=lambda path: 99 if str(path).endswith("mp4") else 50,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verifier_rejects_duplicate_resolved_file() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["sources"][1]["path"] = "E:/neg7.mp4"
    inventory["sources"][1]["source_key"] = "image:i8:E:/neg7.mp4"

    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="same local file"):
        verify_identity_negative_sources(
            inventory,
            path_mapping=_mapping(),
            exists_file=lambda _path: True,
            file_size=lambda _path: 100,
            hash_file=lambda _path: "a" * 64,
        )


def test_negative_verifier_rejects_invalid_hash() -> None:
    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="SHA-256"):
        verify_identity_negative_sources(
            _inventory(),
            path_mapping=_mapping(),
            exists_file=lambda _path: True,
            file_size=lambda path: 50 if str(path).endswith("jpg") else 100,
            hash_file=lambda _path: "nope",
        )
