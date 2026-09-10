from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoidentity_multiperformer_target_attestation import (
    PhotoIdentityMultiTargetAttestationError,
    record_target_isolation_attestation,
)
from bodyrig.photoidentity_multiperformer_target_isolation import FORMAT, PRIVATE_FORMAT


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 80), color).save(path, format="PNG", optimize=False)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "candidates"
    private_root = root / "private-target-source"
    rows = []
    private_rows = []
    for index in (1, 2):
        sample_id = f"targetsample-{index:04d}"
        sample_root = private_root / sample_id
        frame = sample_root / "reviewed-source-frame.png"
        crop = sample_root / "target-track-crop.png"
        _png(frame, (index * 20, 30, 40))
        _png(crop, (index * 30, 50, 60))
        rows.append({
            "sample_id": sample_id,
            "timestamp_ms": index * 1000,
            "confidence": 0.9,
            "bbox_tlwh": [1.0, 2.0, 64.0, 80.0],
            "crop_ltrb": [1, 2, 65, 82],
            "native_frame_width": 120,
            "native_frame_height": 100,
            "native_crop_width": 64,
            "native_crop_height": 80,
            "source_frame_sha256": _sha(frame),
            "target_crop_sha256": _sha(crop),
        })
        private_rows.append({"sample_id": sample_id, "reviewed_source_frame": str(frame.resolve()), "target_track_crop": str(crop.resolve())})

    private = {
        "format": PRIVATE_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_media_sha256": "a" * 64,
        "review_root": str((tmp_path / "review").resolve()),
        "source_path": str((tmp_path / "source.mp4").resolve()),
        "track_candidate_id": "trackcand-" + "c" * 32,
        "selected_track_id": "s00-t7",
        "samples": private_rows,
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-target-source-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")
    public = {
        "format": FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_candidate_id": "multicand-" + "d" * 32,
        "source_media_sha256": "a" * 64,
        "human_track_attestation_sha256": "e" * 64,
        "public_review_manifest_sha256": "f" * 64,
        "private_review_index_sha256": "1" * 64,
        "machine_track_review_sha256": "2" * 64,
        "private_target_source_index_sha256": _sha(private_path),
        "track_candidate_id": "trackcand-" + "c" * 32,
        "selected_track_id": "s00-t7",
        "sample_count": 2,
        "samples": rows,
        "target_track_identity_attested": True,
        "source_frames_human_review_bound": True,
        "all_samples_phalp_observed": True,
        "bbox_interpolation_used": False,
        "source_pixels_resized": False,
        "occlusion_removal_used": False,
        "generative_pixels_used": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolation_human_review_required": True,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    (root / "multiperformer-target-isolation-candidates.json").write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    return root


def test_target_isolation_attestation_grants_authority_only_to_selected_samples(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    result = record_target_isolation_attestation(
        candidate_root=root,
        sample_ids=["targetsample-0001"],
        current_revision="b" * 40,
        quality_note="I reviewed this exact source crop and it contains only the requested performer.",
        confirm_target_isolation=True,
    )
    assert result["accepted_sample_count"] == 1
    assert result["accepted_samples"][0]["sample_id"] == "targetsample-0001"
    assert result["human_target_isolation_attested"] is True
    assert result["cross_person_contamination_absent_attested"] is True
    assert result["authority_scope"] == "accepted-samples-only"
    assert result["target_isolated_source_authority"] is True
    assert result["photoidentity_source_evidence_authority"] is False
    assert result["reconstruction_permitted"] is False
    assert result["production_activation"] is False
    receipt_text = Path(result["receipt"]).read_text(encoding="utf-8")
    assert str(root.resolve()) not in receipt_text
    assert "targetsample-0002" not in receipt_text


def test_target_isolation_attestation_requires_explicit_confirmation_and_unique_known_samples(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityMultiTargetAttestationError, match="explicit human"):
        record_target_isolation_attestation(candidate_root=root, sample_ids=["targetsample-0001"], current_revision="b" * 40, quality_note="Long enough deliberate human review note.", confirm_target_isolation=False)
    with pytest.raises(PhotoIdentityMultiTargetAttestationError, match="unique"):
        record_target_isolation_attestation(candidate_root=root, sample_ids=["targetsample-0001", "targetsample-0001"], current_revision="b" * 40, quality_note="Long enough deliberate human review note.", confirm_target_isolation=True)
    with pytest.raises(PhotoIdentityMultiTargetAttestationError, match="unknown"):
        record_target_isolation_attestation(candidate_root=root, sample_ids=["targetsample-9999"], current_revision="b" * 40, quality_note="Long enough deliberate human review note.", confirm_target_isolation=True)


def test_target_isolation_attestation_fails_closed_on_crop_tamper_and_is_create_only(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    crop = root / "private-target-source" / "targetsample-0001" / "target-track-crop.png"
    crop.write_bytes(crop.read_bytes() + b"tamper")
    with pytest.raises(PhotoIdentityMultiTargetAttestationError, match="target crop bytes changed"):
        record_target_isolation_attestation(candidate_root=root, sample_ids=["targetsample-0001"], current_revision="b" * 40, quality_note="Long enough deliberate human review note.", confirm_target_isolation=True)

    root = _fixture(tmp_path / "second")
    kwargs = dict(candidate_root=root, sample_ids=["targetsample-0001"], current_revision="b" * 40, quality_note="Long enough deliberate human review note.", confirm_target_isolation=True)
    record_target_isolation_attestation(**kwargs)
    with pytest.raises(PhotoIdentityMultiTargetAttestationError, match="already exists"):
        record_target_isolation_attestation(**kwargs)
