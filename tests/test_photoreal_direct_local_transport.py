from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_identity_negative_verify import (
    PhotorealIdentityNegativeVerifyError,
    verify_identity_negative_inventory_file,
)
from bodyrig.photoreal_source_verify import PhotorealSourceVerifyError, verify_inventory_file


def _direct_proof(*, source_scope: str, source_count: int) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-direct-path-proof",
        "version": 1,
        "transport_mode": "direct-local",
        "stash_origin": "http://localhost:9999",
        "stash_host": "localhost",
        "performer_ids": ["42"],
        "source_scope": source_scope,
        "source_count": source_count,
        "all_sources_directly_readable": True,
        "mapping": {},
        "proof": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
        "updated_utc": "2026-09-15T12:00:00Z",
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_inventory(media: Path) -> dict[str, object]:
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
                "path": str(media),
                "size_bytes": media.stat().st_size,
            }
        ],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _negative_inventory(media: Path) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-inventory",
        "version": 1,
        "target_performer_id": "42",
        "label_authority": "stash-single-performer-other-id-v1",
        "sources": [
            {
                "source_key": f"scene:99:{media}",
                "subject_performer_id": "99",
                "subject_performer_name": "Negative 99",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "path": str(media),
                "size_bytes": media.stat().st_size,
                "width": 1920,
                "height": 1080,
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 1.0,
                "frame_rate": 30.0,
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


def test_source_receipt_hashes_direct_local_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    media = Path("performer42.mp4")
    media.write_bytes(b"performer-42-source")
    inventory_path = Path("source-inventory.json")
    proof_path = Path("source-path-map.json")
    receipt_path = Path("source-receipt.json")
    _write_json(inventory_path, _source_inventory(media))
    _write_json(proof_path, _direct_proof(source_scope="primary", source_count=1))

    result = verify_inventory_file(
        inventory_path,
        proof_path,
        receipt_path,
        stash_url="http://localhost:9999",
    )

    assert result["path_map_mode"] == "photoreal-direct-local-v1"
    assert result["all_sources_readable"] is True
    assert result["all_sources_sha256_bound"] is True
    assert result["sources"][0]["resolved_path"] == str(media)
    assert result["sources"][0]["sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert result["production_activation"] is False


def test_negative_receipt_hashes_direct_local_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    media = Path("negative99.mp4")
    media.write_bytes(b"negative-99-source")
    inventory_path = Path("negative-inventory.json")
    proof_path = Path("calibration-path-map.json")
    receipt_path = Path("negative-receipt.json")
    _write_json(inventory_path, _negative_inventory(media))
    _write_json(proof_path, _direct_proof(source_scope="negative-calibration", source_count=1))

    result = verify_identity_negative_inventory_file(
        inventory_path,
        proof_path,
        receipt_path,
        stash_url="http://localhost:9999",
    )

    assert result["path_map_mode"] == "photoreal-direct-local-v1"
    assert result["all_sources_readable"] is True
    assert result["all_sources_sha256_bound"] is True
    assert result["sources"][0]["resolved_path"] == str(media)
    assert result["sources"][0]["sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert result["identity_matching_authorized"] is False
    assert result["production_activation"] is False


def test_source_receipt_rejects_wrong_direct_scope_or_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    media = Path("performer42.mp4")
    media.write_bytes(b"performer-42-source")
    inventory_path = Path("source-inventory.json")
    proof_path = Path("source-path-map.json")
    receipt_path = Path("source-receipt.json")
    _write_json(inventory_path, _source_inventory(media))

    _write_json(proof_path, _direct_proof(source_scope="negative-calibration", source_count=1))
    with pytest.raises(PhotorealSourceVerifyError, match="source scope mismatch"):
        verify_inventory_file(inventory_path, proof_path, receipt_path, stash_url="http://localhost:9999")

    proof_path.unlink()
    _write_json(proof_path, _direct_proof(source_scope="primary", source_count=2))
    with pytest.raises(PhotorealSourceVerifyError, match="source count mismatch"):
        verify_inventory_file(inventory_path, proof_path, receipt_path, stash_url="http://localhost:9999")


def test_negative_receipt_rejects_primary_direct_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    media = Path("negative99.mp4")
    media.write_bytes(b"negative-99-source")
    inventory_path = Path("negative-inventory.json")
    proof_path = Path("calibration-path-map.json")
    receipt_path = Path("negative-receipt.json")
    _write_json(inventory_path, _negative_inventory(media))
    _write_json(proof_path, _direct_proof(source_scope="primary", source_count=1))

    with pytest.raises(PhotorealIdentityNegativeVerifyError, match="source scope mismatch"):
        verify_identity_negative_inventory_file(
            inventory_path,
            proof_path,
            receipt_path,
            stash_url="http://localhost:9999",
        )
