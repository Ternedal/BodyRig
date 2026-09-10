from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoidentity_multiperformer_review_prepare import (
    FORMAT as REVIEW_FORMAT,
    PRIVATE_FORMAT as REVIEW_PRIVATE_FORMAT,
)
from bodyrig.photoidentity_multiperformer_track_attestation import (
    PhotoIdentityMultiTrackAttestationError,
    record_multiperformer_track_attestation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    root = tmp_path / "review"
    private_root = root / "private-track-review"
    track_candidate_id = "trackcand-" + "a" * 32
    track_root = private_root / track_candidate_id
    track_root.mkdir(parents=True)
    sheet = track_root / "review-sheet.png"
    Image.new("RGB", (320, 240), "gray").save(sheet, format="PNG")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact-source")
    machine = root / "machine-track-review.json"
    machine.write_text('{"machine":"review"}\n', encoding="utf-8")

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
        "machine_track_review_sha256": _sha(machine),
        "track_candidate_count": 1,
        "tracks": [{
            "track_candidate_id": track_candidate_id,
            "track_id": "s00-t7",
            "observation_count": 4,
            "first_timestamp_ms": 0,
            "last_timestamp_ms": 3000,
            "review_sample_count": 2,
            "review_sheet_sha256": _sha(sheet),
            "samples": [
                {"timestamp_ms": 0, "source_frame_sha256": "1" * 64, "review_tile_sha256": "2" * 64},
                {"timestamp_ms": 3000, "source_frame_sha256": "3" * 64, "review_tile_sha256": "4" * 64},
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
            "track_id": "s00-t7",
            "review_sheet": str(sheet.resolve()),
        }],
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-review-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")
    return root, track_candidate_id, source, sheet


def test_human_attestation_binds_source_track_review_and_stays_non_production(tmp_path: Path):
    root, candidate, source, _ = _fixture(tmp_path)
    result = record_multiperformer_track_attestation(
        review_root=root,
        track_candidate_id=candidate,
        current_revision="b" * 40,
        quality_note="I reviewed every shown source crop and this track is the requested performer.",
        confirm_identity=True,
    )
    receipt_path = Path(result["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["human_identity_attested"] is True
    assert receipt["selected_track_id"] == "s00-t7"
    assert receipt["source_media_sha256"] == _sha(source)
    assert receipt["source_paths_persisted"] is False
    assert receipt["target_isolated_source_authority"] is False
    assert receipt["photoidentity_source_evidence_authority"] is False
    assert receipt["reconstruction_permitted"] is False
    assert receipt["production_activation"] is False
    assert str(source.resolve()) not in receipt_path.read_text(encoding="utf-8")


def test_human_attestation_requires_explicit_confirmation_and_exact_revision(tmp_path: Path):
    root, candidate, _, _ = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityMultiTrackAttestationError, match="explicit human"):
        record_multiperformer_track_attestation(
            review_root=root,
            track_candidate_id=candidate,
            current_revision="b" * 40,
            quality_note="This is long enough to be a deliberate human note.",
            confirm_identity=False,
        )
    with pytest.raises(PhotoIdentityMultiTrackAttestationError, match="different BodyRig revision"):
        record_multiperformer_track_attestation(
            review_root=root,
            track_candidate_id=candidate,
            current_revision="c" * 40,
            quality_note="This is long enough to be a deliberate human note.",
            confirm_identity=True,
        )


def test_human_attestation_fails_closed_on_source_or_review_sheet_tamper(tmp_path: Path):
    root, candidate, source, sheet = _fixture(tmp_path)
    source.write_bytes(b"changed-source")
    with pytest.raises(PhotoIdentityMultiTrackAttestationError, match="source media bytes changed"):
        record_multiperformer_track_attestation(
            review_root=root,
            track_candidate_id=candidate,
            current_revision="b" * 40,
            quality_note="This is long enough to be a deliberate human note.",
            confirm_identity=True,
        )

    root, candidate, _, sheet = _fixture(tmp_path / "other")
    sheet.write_bytes(sheet.read_bytes() + b"tamper")
    with pytest.raises(PhotoIdentityMultiTrackAttestationError, match="review sheet bytes changed"):
        record_multiperformer_track_attestation(
            review_root=root,
            track_candidate_id=candidate,
            current_revision="b" * 40,
            quality_note="This is long enough to be a deliberate human note.",
            confirm_identity=True,
        )


def test_human_attestation_is_create_only(tmp_path: Path):
    root, candidate, _, _ = _fixture(tmp_path)
    kwargs = dict(
        review_root=root,
        track_candidate_id=candidate,
        current_revision="b" * 40,
        quality_note="This is long enough to be a deliberate human note.",
        confirm_identity=True,
    )
    record_multiperformer_track_attestation(**kwargs)
    with pytest.raises(PhotoIdentityMultiTrackAttestationError, match="already exists"):
        record_multiperformer_track_attestation(**kwargs)
