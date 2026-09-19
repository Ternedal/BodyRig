from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_source_receipt_rebind import (
    PhotorealSourceReceiptRebindError,
    rebind_verified_source_receipt,
)


def _inventory(*, projection: str = "flat", path: str = "E:/VR/source.mp4", size: int = 100) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "video_file_count": 1,
        "image_file_count": 0,
        "summary": {"source_universe_exhaustive": True},
        "videos": [
            {
                "scene_id": "s1",
                "path": path,
                "size_bytes": size,
                "projection": projection,
                "stereo_layout": "unknown" if projection == "projection-ambiguous-2to1" else "mono",
                "tags": ["180°"] if projection != "flat" else [],
            }
        ],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _raw(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _prior_receipt(inventory_raw: bytes) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "source_count": 1,
        "video_count": 1,
        "image_count": 0,
        "total_bytes": 100,
        "sources": [
            {
                "kind": "video",
                "source_id": "s1",
                "source_key": "scene:s1:E:/VR/source.mp4",
                "catalog_path": "E:/VR/source.mp4",
                "resolved_path": "E:/VR/source.mp4",
                "size_bytes": 100,
                "sha256": "a" * 64,
            }
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "teacher_input_authority": True,
        "runtime_dependency": False,
        "production_activation": False,
        "inventory_sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "path_map_mode": "photoreal-direct-local-v1",
        "stash_origin": "http://stash.local:9998",
    }


def _path_map() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-direct-path-proof",
        "version": 1,
        "transport_mode": "direct-local",
        "source_scope": "primary",
        "source_count": 1,
        "stash_origin": "http://stash.local:9998",
        "performer_ids": ["42"],
        "all_sources_directly_readable": True,
        "mapping": {},
        "proof": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_rebind_reuses_verified_hash_for_metadata_only_inventory_change() -> None:
    prior_inventory = _inventory()
    prior_inventory_raw = _raw(prior_inventory)
    prior_receipt = _prior_receipt(prior_inventory_raw)
    new_inventory = _inventory(projection="projection-ambiguous-2to1")
    new_inventory_raw = _raw(new_inventory)

    receipt, proof = rebind_verified_source_receipt(
        prior_inventory=prior_inventory,
        prior_inventory_raw=prior_inventory_raw,
        prior_receipt=prior_receipt,
        prior_receipt_raw=_raw(prior_receipt),
        new_inventory=new_inventory,
        new_inventory_raw=new_inventory_raw,
        new_path_map=_path_map(),
        stash_url="http://stash.local:9998",
        exists_file=lambda _path: True,
        file_size=lambda _path: 100,
    )

    assert receipt["inventory_sha256"] == hashlib.sha256(new_inventory_raw).hexdigest()
    assert receipt["sources"][0]["sha256"] == "a" * 64
    assert receipt["all_sources_sha256_bound"] is True
    assert proof["source_rehash_skipped_explicitly"] is True
    assert proof["all_source_records_exactly_preserved"] is True
    assert proof["all_current_sizes_match_verified_receipt"] is True
    assert proof["production_activation"] is False


def test_rebind_rejects_changed_source_path() -> None:
    prior_inventory = _inventory()
    prior_raw = _raw(prior_inventory)
    with pytest.raises(PhotorealSourceReceiptRebindError, match="source universe"):
        rebind_verified_source_receipt(
            prior_inventory=prior_inventory,
            prior_inventory_raw=prior_raw,
            prior_receipt=_prior_receipt(prior_raw),
            prior_receipt_raw=b"{}",
            new_inventory=_inventory(path="E:/VR/different.mp4"),
            new_inventory_raw=_raw(_inventory(path="E:/VR/different.mp4")),
            new_path_map=_path_map(),
            stash_url="http://stash.local:9998",
            exists_file=lambda _path: True,
            file_size=lambda _path: 100,
        )


def test_rebind_rejects_changed_source_size() -> None:
    prior_inventory = _inventory()
    prior_raw = _raw(prior_inventory)
    with pytest.raises(PhotorealSourceReceiptRebindError, match="byte-relevant source field expected_size_bytes"):
        rebind_verified_source_receipt(
            prior_inventory=prior_inventory,
            prior_inventory_raw=prior_raw,
            prior_receipt=_prior_receipt(prior_raw),
            prior_receipt_raw=b"{}",
            new_inventory=_inventory(size=101),
            new_inventory_raw=_raw(_inventory(size=101)),
            new_path_map=_path_map(),
            stash_url="http://stash.local:9998",
            exists_file=lambda _path: True,
            file_size=lambda _path: 101,
        )


def test_rebind_rejects_prior_receipt_bound_to_other_inventory() -> None:
    prior_inventory = _inventory()
    prior_raw = _raw(prior_inventory)
    receipt = _prior_receipt(prior_raw)
    receipt["inventory_sha256"] = "b" * 64

    with pytest.raises(PhotorealSourceReceiptRebindError, match="not bound"):
        rebind_verified_source_receipt(
            prior_inventory=prior_inventory,
            prior_inventory_raw=prior_raw,
            prior_receipt=receipt,
            prior_receipt_raw=_raw(receipt),
            new_inventory=_inventory(projection="projection-ambiguous-2to1"),
            new_inventory_raw=_raw(_inventory(projection="projection-ambiguous-2to1")),
            new_path_map=_path_map(),
            stash_url="http://stash.local:9998",
            exists_file=lambda _path: True,
            file_size=lambda _path: 100,
        )


def test_rebind_rejects_current_size_drift_without_rehashing() -> None:
    prior_inventory = _inventory()
    prior_raw = _raw(prior_inventory)

    with pytest.raises(PhotorealSourceReceiptRebindError, match="size changed"):
        rebind_verified_source_receipt(
            prior_inventory=prior_inventory,
            prior_inventory_raw=prior_raw,
            prior_receipt=_prior_receipt(prior_raw),
            prior_receipt_raw=b"{}",
            new_inventory=_inventory(projection="projection-ambiguous-2to1"),
            new_inventory_raw=_raw(_inventory(projection="projection-ambiguous-2to1")),
            new_path_map=_path_map(),
            stash_url="http://stash.local:9998",
            exists_file=lambda _path: True,
            file_size=lambda _path: 99,
        )
