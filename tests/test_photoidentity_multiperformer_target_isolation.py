from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from bodyrig.photoidentity_multiperformer_review_prepare import (
    FORMAT as REVIEW_FORMAT,
    PRIVATE_FORMAT as REVIEW_PRIVATE_FORMAT,
)
from bodyrig.photoidentity_multiperformer_target_isolation import (
    FORMAT as ISOLATION_FORMAT,
    PhotoIdentityMultiTargetIsolationError,
    isolate_human_attested_track_source,
)
from bodyrig.photoidentity_multiperformer_track_attestation import record_multiperformer_track_attestation


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_png(path: Path, *, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 100), color).save(path, format="PNG", optimize=False)


def _fixture(tmp_path: Path) -> tuple[Path, str, Path]:
    root = tmp_path / "review"
    private_root = root / "private-track-review"
    track_candidate_id = "trackcand-" + "a" * 32
    track_id = "s00-t7"
    track_root = private_root / track_candidate_id
    samples_root = track_root / "samples"
    samples_root.mkdir(parents=True)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact-multiperformer-source-bytes")

    frame1 = samples_root / "sample-01-source-frame.png"
    frame2 = samples_root / "sample-02-source-frame.png"
    _write_png(frame1, color=(20, 30, 40))
    _write_png(frame2, color=(50, 60, 70))
    tile1 = samples_root / "sample-01-review-tile.png"
    tile2 = samples_root / "sample-02-review-tile.png"
    _write_png(tile1, color=(80, 90, 100))
    _write_png(tile2, color=(110, 100, 90))
    sheet = track_root / "review-sheet.png"
    _write_png(sheet, color=(1, 2, 3))

    machine = {
        "format": "bodyrig-phalp-track-review-batch",
        "version": 1,
        "adapter": ADAPTER_NAME,
        "revision": ADAPTER_REVISION,
        "sources": [{
            "source_index": 0,
            "source_media_sha256": _sha(source),
            "review": {
                "format": "bodyrig-phalp-track-review",
                "version": 1,
                "source_index": 0,
                "tracks": [{
                    "track_id": track_id,
                    "observation_count": 4,
                    "first_timestamp_ms": 1000,
                    "last_timestamp_ms": 4000,
                    "samples": [
                        {"timestamp_ms": 1000, "confidence": 0.95, "bbox_tlwh": [10.2, 20.1, 40.0, 50.0]},
                        {"timestamp_ms": 4000, "confidence": 0.91, "bbox_tlwh": [15.0, 12.0, 44.0, 55.0]},
                    ],
                }],
                "target_track_id": None,
                "human_identity_attestation_required": True,
                "biometric_identity_inference_used": False,
                "generic_guessing_permitted": False,
                "reconstruction_permitted": False,
                "production_activation": False,
            },
        }],
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "appearance_embeddings_exported": False,
        "source_paths_exported": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    machine_path = root / "machine-track-review.json"
    machine_path.write_text(json.dumps(machine, sort_keys=True) + "\n", encoding="utf-8")

    public = {
        "format": REVIEW_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "source_discovery_manifest_sha256": "c" * 64,
        "source_discovery_private_index_sha256": "d" * 64,
        "source_candidate_id": "multicand-" + "e" * 32,
        "scene_id": "scene-1",
        "source_media_sha256": _sha(source),
        "machine_track_review_sha256": _sha(machine_path),
        "track_candidate_count": 1,
        "tracks": [{
            "track_candidate_id": track_candidate_id,
            "track_id": track_id,
            "observation_count": 4,
            "first_timestamp_ms": 1000,
            "last_timestamp_ms": 4000,
            "review_sample_count": 2,
            "review_sheet_sha256": _sha(sheet),
            "samples": [
                {"timestamp_ms": 1000, "source_frame_sha256": _sha(frame1), "review_tile_sha256": _sha(tile1)},
                {"timestamp_ms": 4000, "source_frame_sha256": _sha(frame2), "review_tile_sha256": _sha(tile2)},
            ],
        }],
        "source_paths_persisted": False,
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    public_path = root / "multiperformer-track-review-candidates.json"
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")

    private = {
        "format": REVIEW_PRIVATE_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "public_review_manifest_sha256": _sha(public_path),
        "source_candidate_id": public["source_candidate_id"],
        "scene_id": "scene-1",
        "source_media_sha256": _sha(source),
        "source_path": str(source.resolve()),
        "tracks": [{
            "track_candidate_id": track_candidate_id,
            "track_id": track_id,
            "review_sheet": str(sheet.resolve()),
        }],
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-review-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")

    record_multiperformer_track_attestation(
        review_root=root,
        track_candidate_id=track_candidate_id,
        current_revision="b" * 40,
        quality_note="I reviewed all source crops and this PHALP track is the requested performer.",
        confirm_identity=True,
    )
    return root, track_candidate_id, source


def test_target_isolation_materializes_only_reviewed_native_source_crop_candidates(tmp_path: Path) -> None:
    root, candidate, source = _fixture(tmp_path)
    out = tmp_path / "isolated"
    result = isolate_human_attested_track_source(
        review_root=root,
        output_dir=out,
        current_revision="b" * 40,
    )
    assert result["format"] == ISOLATION_FORMAT
    assert result["sample_count"] == 2
    assert result["track_candidate_id"] == candidate
    assert result["source_media_sha256"] == _sha(source)
    assert result["target_track_identity_attested"] is True
    assert result["source_frames_human_review_bound"] is True
    assert result["all_samples_phalp_observed"] is True
    assert result["bbox_interpolation_used"] is False
    assert result["source_pixels_resized"] is False
    assert result["occlusion_removal_used"] is False
    assert result["generative_pixels_used"] is False
    assert result["biometric_identity_inference_used"] is False
    assert result["generic_guessing_permitted"] is False
    assert result["target_isolation_human_review_required"] is True
    assert result["target_isolated_source_authority"] is False
    assert result["photoidentity_source_evidence_authority"] is False
    assert result["reconstruction_permitted"] is False
    assert result["production_activation"] is False

    manifest_text = Path(result["public_manifest"]).read_text(encoding="utf-8")
    assert str(source.resolve()) not in manifest_text
    assert "private-target-source" not in manifest_text
    rows = result["samples"]
    assert rows[0]["crop_ltrb"] == [10, 20, 51, 71]
    assert rows[0]["native_crop_width"] == 41
    assert rows[0]["native_crop_height"] == 51
    crop = out / "private-target-source" / "targetsample-0001" / "target-track-crop.png"
    with Image.open(crop) as opened:
        assert opened.size == (41, 51)


def test_target_isolation_fails_closed_if_reviewed_source_frame_changes(tmp_path: Path) -> None:
    root, candidate, _ = _fixture(tmp_path)
    frame = root / "private-track-review" / candidate / "samples" / "sample-01-source-frame.png"
    frame.write_bytes(frame.read_bytes() + b"tamper")
    with pytest.raises(PhotoIdentityMultiTargetIsolationError, match="source-frame bytes changed"):
        isolate_human_attested_track_source(
            review_root=root,
            output_dir=tmp_path / "isolated",
            current_revision="b" * 40,
        )


def test_target_isolation_fails_closed_if_machine_review_changes_after_attestation(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    machine = root / "machine-track-review.json"
    machine.write_bytes(machine.read_bytes() + b" ")
    with pytest.raises(PhotoIdentityMultiTargetIsolationError, match="machine-track bytes"):
        isolate_human_attested_track_source(
            review_root=root,
            output_dir=tmp_path / "isolated",
            current_revision="b" * 40,
        )


def test_target_isolation_is_revision_bound_and_create_only(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityMultiTargetIsolationError, match="different BodyRig revision"):
        isolate_human_attested_track_source(
            review_root=root,
            output_dir=tmp_path / "wrong-revision",
            current_revision="c" * 40,
        )
    out = tmp_path / "isolated"
    isolate_human_attested_track_source(
        review_root=root,
        output_dir=out,
        current_revision="b" * 40,
    )
    with pytest.raises(PhotoIdentityMultiTargetIsolationError, match="already exists"):
        isolate_human_attested_track_source(
            review_root=root,
            output_dir=out,
            current_revision="b" * 40,
        )
