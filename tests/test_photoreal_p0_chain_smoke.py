from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bodyrig.photoreal_dataset_plan import build_dataset_plan_file
from bodyrig.photoreal_frame_analyzer_runner import (
    build_analyzer_request,
    validate_analyzer_result,
)
from bodyrig.photoreal_frame_identity_sealed_readback_authority import (
    authorize_frame_identity_files_sealed_strict,
)
from bodyrig.photoreal_frame_index import build_frame_index_files
from bodyrig.photoreal_identity_bank import build_identity_bank_files
from bodyrig.photoreal_identity_bootstrap import build_identity_bootstrap_plan_file
from bodyrig.photoreal_identity_calibration_extractor_runner import (
    build_calibration_extractor_request,
    validate_calibration_extractor_result,
)
from bodyrig.photoreal_identity_calibration_plan import build_identity_calibration_plan_files
from bodyrig.photoreal_identity_calibration_provenance import (
    build_identity_calibration_provenance_files,
)
from bodyrig.photoreal_identity_extractor_runner import (
    build_identity_extractor_request,
    validate_identity_extractor_result,
)
from bodyrig.photoreal_identity_negative_inventory import build_identity_negative_inventory
from bodyrig.photoreal_identity_negative_verify import verify_identity_negative_inventory_file
from bodyrig.photoreal_model_set import write_model_set
from bodyrig.photoreal_scan_plan import build_scan_plan_files
from bodyrig.photoreal_source_verify import verify_inventory_file
from bodyrig.stash_path_cache import normalize_origin


PERFORMER_ID = "42"
PERFORMER_NAME = "Performer 42"
STASH_URL = "http://localhost:9999"
ADAPTER = "bodyrig-smoke-identity"
REVISION = "smoke-r1"
DIMENSION = 32


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _target_embedding() -> list[float]:
    return [1.0] + [0.0] * (DIMENSION - 1)


def _negative_embedding() -> list[float]:
    return [0.0, 1.0] + [0.0] * (DIMENSION - 2)


def _direct_path_proof(*, source_count: int, scope: str) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-direct-path-proof",
        "version": 1,
        "transport_mode": "direct-local",
        "stash_origin": normalize_origin(STASH_URL),
        "performer_ids": [PERFORMER_ID],
        "source_scope": scope,
        "source_count": source_count,
        "all_sources_directly_readable": True,
        "mapping": {},
        "proof": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _target_inventory(media: list[Path]) -> dict[str, object]:
    videos = []
    for index, path in enumerate(media, start=1):
        videos.append(
            {
                "scene_id": f"target-{index}",
                "path": str(path),
                "performer_count": 1,
                "information_score": float(100 - index),
                "projection": "flat",
                "stereo_layout": "mono",
                "width": 1920,
                "height": 1080,
                "duration_seconds": 120.0,
                "frame_rate": 30.0,
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": PERFORMER_ID,
        "performer_name": PERFORMER_NAME,
        "performer": {"id": PERFORMER_ID, "name": PERFORMER_NAME},
        "video_file_count": len(videos),
        "image_file_count": 0,
        "summary": {"source_universe_exhaustive": True},
        "videos": videos,
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _negative_performer_inventory(performer_id: str, path: Path) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": performer_id,
        "performer_name": f"Negative {performer_id}",
        "videos": [
            {
                "scene_id": f"negative-{performer_id}",
                "path": str(path),
                "performer_count": 1,
                "information_score": 90.0,
                "projection": "flat",
                "stereo_layout": "mono",
                "width": 1920,
                "height": 1080,
                "duration_seconds": 60.0,
                "frame_rate": 30.0,
                "size_bytes": path.stat().st_size,
            }
        ],
        "images": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _identity_observations(bootstrap: dict[str, object], model_set_sha256: str) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    for source_index, source in enumerate(bootstrap["sources"]):
        for sample_index, sample in enumerate(source["reference_samples"][:2]):
            observations.append(
                {
                    "source_key": source["source_key"],
                    "source_sha256": source["source_sha256"],
                    "timestamp_seconds": sample["timestamp_seconds"],
                    "eye": sample["eye"],
                    "frame_sha256": _sha(f"identity:{source_index}:{sample_index}"),
                    "embedding": _target_embedding(),
                }
            )
    return {
        "format": "bodyrig-photoreal-identity-reference-observations",
        "version": 1,
        "performer_id": PERFORMER_ID,
        "extractor": ADAPTER,
        "extractor_revision": REVISION,
        "model_set_sha256": model_set_sha256,
        "embedding_dimension": DIMENSION,
        "observations": observations,
        "build_only": True,
        "production_activation": False,
    }


def _negative_observations(plan: dict[str, object], model_set_sha256: str) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    for source_index, source in enumerate(plan["sources"]):
        for sample_index, sample in enumerate(source["samples"]):
            observations.append(
                {
                    "source_key": source["source_key"],
                    "source_sha256": source["source_sha256"],
                    "subject_performer_id": source["subject_performer_id"],
                    "timestamp_seconds": sample["timestamp_seconds"],
                    "eye": sample["eye"],
                    "frame_sha256": _sha(f"negative:{source_index}:{sample_index}"),
                    "embedding": _negative_embedding(),
                }
            )
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": PERFORMER_ID,
        "identity_bank_sha256": plan["identity_bank_sha256"],
        "extractor": ADAPTER,
        "extractor_revision": REVISION,
        "model_set_sha256": model_set_sha256,
        "embedding_dimension": DIMENSION,
        "observations": observations,
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def _frame_measurements(scan: dict[str, object], model_set_sha256: str) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    for source in scan["sources"]:
        for sample_index, sample in enumerate(source["samples"]):
            if source["split"] == "evaluation":
                view_bin = (
                    "front"
                    if sample_index == 0
                    else "three-quarter-left"
                    if sample_index == 1
                    else "profile-left"
                    if sample_index == 2
                    else "front"
                )
                perceptual_hash = "ffffffffffffffff"
            else:
                view_bin = "front"
                perceptual_hash = "0000000000000000"
            observations.append(
                {
                    "source_key": source["source_key"],
                    "source_sha256": source["source_sha256"],
                    "kind": source["kind"],
                    "timestamp_seconds": sample["timestamp_seconds"],
                    "eye": sample["eye"],
                    "projection": source["projection"],
                    "frame_sha256": _sha(
                        f"frame:{source['source_key']}:{sample['timestamp_seconds']}:{sample['eye']}"
                    ),
                    "perceptual_hash": perceptual_hash,
                    "candidate_id": "person-0",
                    "person_detected": True,
                    "width": 1920,
                    "height": 1080,
                    "view_bin": view_bin,
                    "face_visibility": 0.95,
                    "full_body_visibility": 0.95,
                    "person_fraction": 0.80,
                    "sharpness": 0.90,
                    "motion": 0.05,
                    "occlusion": 0.05,
                    "identity_measurement_status": "unavailable",
                    "identity_embedding": None,
                }
            )
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": PERFORMER_ID,
        "analyzer": "bodyrig-smoke-frame",
        "analyzer_revision": REVISION,
        "analyzer_model_set_sha256": model_set_sha256,
        "identity_embedding_dimension": DIMENSION,
        "observations": observations,
        "build_only": True,
        "production_activation": False,
    }


@pytest.mark.skipif(
    os.name != "nt",
    reason="direct-local source receipt verification is a Windows-native P0 stage",
)
def test_photoreal_p0_cross_stage_chain_reaches_teacher_gate(tmp_path: Path) -> None:
    # Stage 1 (live Stash inventory discovery) is intentionally injected: this
    # smoke proves the persisted artifact chain from dataset planning through
    # the final teacher gate without requiring a live Stash server or GPU.
    media_root = tmp_path / "media"
    media_root.mkdir()
    target_media = [media_root / f"target-{index}.mp4" for index in range(1, 4)]
    for index, path in enumerate(target_media, start=1):
        path.write_bytes(f"synthetic-target-{index}".encode("utf-8"))

    inventory_path = tmp_path / "source-inventory.json"
    _write_json(inventory_path, _target_inventory(target_media))

    # 2/16 dataset plan.
    plan_path = tmp_path / "dataset-plan.json"
    plan = build_dataset_plan_file(inventory_path, plan_path)
    assert plan["train_source_count"] == 2
    assert plan["evaluation_source_count"] == 1

    # 3/16 exact source-byte receipt using real hashing of the tiny fixtures.
    primary_path_map = tmp_path / "source-path-map.json"
    _write_json(primary_path_map, _direct_path_proof(source_count=3, scope="primary"))
    receipt_path = tmp_path / "source-receipt.json"
    receipt = verify_inventory_file(
        inventory_path,
        primary_path_map,
        receipt_path,
        stash_url=STASH_URL,
    )
    assert receipt["all_sources_readable"] is True
    assert receipt["all_sources_sha256_bound"] is True

    # 4/16 scan plan. Flat/mono is already decode-authoritative, so this path
    # legitimately bypasses Spherical-V2 resolution without weakening Stage 4.
    scan_path = tmp_path / "scan-plan.json"
    scan = build_scan_plan_files(plan_path, receipt_path, scan_path)
    assert scan["source_count"] == 3
    assert all(source["decode_mode"] == "rectilinear-mono" for source in scan["sources"])

    # 5/16 identity bootstrap.
    bootstrap_path = tmp_path / "identity-bootstrap-plan.json"
    bootstrap = build_identity_bootstrap_plan_file(scan_path, bootstrap_path)
    assert bootstrap["source_count"] == 2
    assert bootstrap["source_group_count"] == 2

    # 6/16 model-set provenance over a tiny real file.
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "smoke-model.bin").write_bytes(b"bodyrig-smoke-model")
    model_set_path = tmp_path / "model-set.json"
    model_set = write_model_set(model_root, model_set_path)
    model_sha = model_set["model_set_sha256"]

    # 7/16 external identity inference is the first intentionally synthetic
    # process result. Its request and result still pass the real runner contract.
    identity_request = build_identity_extractor_request(
        bootstrap,
        model_set,
        adapter=ADAPTER,
        revision=REVISION,
        expected_model_set_sha256=model_sha,
    )
    assert identity_request["teacher_training_authority"] is False
    identity_result = _identity_observations(bootstrap, model_sha)
    identity_result = validate_identity_extractor_result(
        identity_result,
        performer_id=PERFORMER_ID,
        adapter=ADAPTER,
        revision=REVISION,
        model_set_sha256=model_sha,
    )
    identity_observations_path = tmp_path / "identity-observations.json"
    _write_json(identity_observations_path, identity_result)

    # 8/16 real identity-bank derivation.
    bank_path = tmp_path / "identity-bank.json"
    bank = build_identity_bank_files(
        bootstrap_path,
        model_set_path,
        identity_observations_path,
        bank_path,
    )
    assert bank["reference_count"] == 4
    assert bank["source_group_count"] == 2

    # 9/16 negative inventory from two independently labelled performers.
    negative_paths = {
        "100": media_root / "negative-100.mp4",
        "101": media_root / "negative-101.mp4",
    }
    for performer_id, path in negative_paths.items():
        path.write_bytes(f"synthetic-negative-{performer_id}".encode("utf-8"))
    target_scenes = [
        {"id": "co-100", "performers": [{"id": PERFORMER_ID}, {"id": "100"}]},
        {"id": "co-101", "performers": [{"id": PERFORMER_ID}, {"id": "101"}]},
    ]
    performer_records = {
        performer_id: {"id": performer_id, "name": f"Negative {performer_id}"}
        for performer_id in negative_paths
    }
    source_inventories = {
        performer_id: _negative_performer_inventory(performer_id, path)
        for performer_id, path in negative_paths.items()
    }
    negative_inventory = build_identity_negative_inventory(
        target_performer_id=PERFORMER_ID,
        target_scenes=target_scenes,
        performer_records=performer_records,
        source_inventories=source_inventories,
        max_performers=2,
        max_sources_per_performer=1,
    )
    negative_inventory_path = tmp_path / "negative-inventory.json"
    _write_json(negative_inventory_path, negative_inventory)
    assert negative_inventory["performer_count"] == 2
    assert negative_inventory["source_count"] == 2

    # 10/16 negative source receipt, again with real fixture hashing.
    negative_path_map = tmp_path / "negative-path-map.json"
    _write_json(
        negative_path_map,
        _direct_path_proof(source_count=2, scope="negative-calibration"),
    )
    negative_receipt_path = tmp_path / "negative-receipt.json"
    negative_receipt = verify_identity_negative_inventory_file(
        negative_inventory_path,
        negative_path_map,
        negative_receipt_path,
        stash_url=STASH_URL,
    )
    assert negative_receipt["all_sources_readable"] is True
    assert negative_receipt["all_sources_sha256_bound"] is True

    # 11/16 calibration plan.
    calibration_plan_path = tmp_path / "identity-calibration-plan.json"
    calibration_plan = build_identity_calibration_plan_files(
        bank_path,
        negative_inventory_path,
        negative_receipt_path,
        calibration_plan_path,
    )
    assert calibration_plan["negative_performer_count"] == 2
    assert calibration_plan["negative_source_count"] == 2

    # 12/16 synthetic negative inference through the real calibration runner contract.
    calibration_request = build_calibration_extractor_request(
        calibration_plan,
        model_set,
        adapter=ADAPTER,
        revision=REVISION,
        expected_model_set_sha256=model_sha,
    )
    assert calibration_request["calibration_only"] is True
    negative_result = _negative_observations(calibration_plan, model_sha)
    negative_result = validate_calibration_extractor_result(
        negative_result,
        target_performer_id=PERFORMER_ID,
        identity_bank_sha256=calibration_plan["identity_bank_sha256"],
        adapter=ADAPTER,
        revision=REVISION,
        model_set_sha256=model_sha,
    )
    negative_observations_path = tmp_path / "negative-observations.json"
    _write_json(negative_observations_path, negative_result)

    calibration_path = tmp_path / "identity-calibration.json"
    calibration = build_identity_calibration_provenance_files(
        bank_path,
        calibration_plan_path,
        negative_observations_path,
        calibration_path,
    )
    assert calibration["calibration_complete"] is True

    # 13/16 frame-analyzer request/result contract.
    frame_request = build_analyzer_request(
        scan,
        model_set,
        analyzer="bodyrig-smoke-frame",
        analyzer_revision=REVISION,
        expected_model_set_sha256=model_sha,
    )
    assert frame_request["identity_matching_authority"] is False
    frame_result = _frame_measurements(scan, model_sha)
    frame_result = validate_analyzer_result(
        frame_result,
        scan_plan=scan,
        performer_id=PERFORMER_ID,
        analyzer="bodyrig-smoke-frame",
        analyzer_revision=REVISION,
        analyzer_model_set_sha256=model_sha,
    )
    frame_observations_path = tmp_path / "frame-observations.json"
    _write_json(frame_observations_path, frame_result)

    # 14/16 sealed identity authorization.
    authorized_observations_path = tmp_path / "authorized-observations.json"
    authorized = authorize_frame_identity_files_sealed_strict(
        frame_observations_path,
        scan_path,
        bank_path,
        calibration_path,
        authorized_observations_path,
    )
    assert authorized["identity_matching_calibrated"] is True
    assert authorized["identity_authority_is_core_derived"] is True

    # 15/16 frame index.
    frame_index_path = tmp_path / "frame-index.json"
    frame_index = build_frame_index_files(
        scan_path,
        authorized_observations_path,
        frame_index_path,
    )
    assert frame_index["source_count"] == 3
    assert frame_index["teacher_training_authority"] is True

    # 16/16 teacher gate evidence. The smoke fixture intentionally guarantees
    # held-out face-front, three-quarter, profile and full-body coverage.
    assert frame_index["teacher_training_authorized"] is True
    assert frame_index["blockers"] == []
