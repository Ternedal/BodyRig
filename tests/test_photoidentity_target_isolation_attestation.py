from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.photoidentity_target_isolation_attestation as attestation
from bodyrig.photoidentity_target_isolation_attestation import (
    PhotoIdentityTargetIsolationAttestationError,
    record_target_isolation_attestation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    root = tmp_path / "isolation"
    private_root = root / "private-target-isolation"
    private_root.mkdir(parents=True)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact original multi-person source")

    upstream_attestation = tmp_path / "upstream-track-attestation.json"
    upstream_attestation.write_text('{"human":"track"}\n', encoding="utf-8")
    upstream_machine = tmp_path / "upstream-machine-track.json"
    upstream_machine.write_text('{"machine":"track"}\n', encoding="utf-8")
    machine = root / "machine-target-isolation.json"
    machine.write_text('{"machine":"isolation"}\n', encoding="utf-8")
    contact = private_root / "target-isolation-contact-sheet.png"
    Image.new("RGB", (1000, 600), "black").save(contact, format="PNG")

    public_samples = []
    private_samples = []
    isolated_paths: list[Path] = []
    for index in range(1, 4):
        sample_root = private_root / f"sample-{index:03d}"
        sample_root.mkdir()
        source_frame = sample_root / "source-frame.png"
        isolated_frame = sample_root / "isolated-frame.png"
        review_tile = sample_root / "review-tile.png"
        Image.new("RGB", (320, 240), (80, 90, 100)).save(source_frame, format="PNG")
        Image.new("RGB", (320, 240), (0, 0, 0)).save(isolated_frame, format="PNG")
        Image.new("RGB", (1000, 600), "gray").save(review_tile, format="PNG")
        isolated_paths.append(isolated_frame)
        public_samples.append({
            "sample_index": index,
            "timestamp_ms": (index - 1) * 1000,
            "confidence": 0.9,
            "bbox_tlwh": [50.0, 20.0, 100.0, 180.0],
            "observed_other_track_count": 1,
            "max_other_overlap_fraction": 0.05,
            "source_frame_sha256": _sha(source_frame),
            "isolated_frame_sha256": _sha(isolated_frame),
            "review_tile_sha256": _sha(review_tile),
            "width": 320,
            "height": 240,
        })
        private_samples.append({
            "sample_index": index,
            "source_frame": str(source_frame.resolve()),
            "isolated_frame": str(isolated_frame.resolve()),
            "review_tile": str(review_tile.resolve()),
        })

    public = {
        "format": "bodyrig-photoidentity-target-isolation-candidate",
        "version": 1,
        "attestation_revision": "a" * 40,
        "isolation_operator_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_candidate_id": "multicand-" + "1" * 32,
        "source_media_sha256": _sha(source),
        "selected_track_id": "s00-t7",
        "human_track_attestation_sha256": _sha(upstream_attestation),
        "machine_track_review_sha256": _sha(upstream_machine),
        "machine_target_isolation_sha256": _sha(machine),
        "mask_method": "black-outside-human-attested-phalp-tlwh-v1",
        "bbox_padding_ratio": 0.12,
        "observed_state_count": 10,
        "max_other_overlap_fraction": 0.20,
        "p95_other_overlap_fraction": 0.10,
        "high_overlap_state_count": 2,
        "severe_overlap_state_count": 0,
        "candidate_frame_count": 3,
        "samples": public_samples,
        "contact_sheet_sha256": _sha(contact),
        "source_paths_persisted": False,
        "machine_identity_selection": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "human_isolation_review_required": True,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    public_path = root / "target-isolation-candidate.json"
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    private = {
        "format": "bodyrig-photoidentity-private-target-isolation-index",
        "version": 1,
        "public_manifest_sha256": _sha(public_path),
        "attestation_revision": "a" * 40,
        "isolation_operator_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_media_sha256": _sha(source),
        "selected_track_id": "s00-t7",
        "source_path": str(source.resolve()),
        "upstream_review_root": str(tmp_path / "review"),
        "human_track_attestation": str(upstream_attestation.resolve()),
        "machine_track_review": str(upstream_machine.resolve()),
        "machine_target_isolation": str(machine.resolve()),
        "contact_sheet": str(contact.resolve()),
        "samples": private_samples,
        "source_paths_private": True,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "production_activation": False,
    }
    (private_root / "private-isolation-index.json").write_text(
        json.dumps(private, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root, source, isolated_paths


def test_human_isolation_attestation_authorizes_only_reviewed_frame_set(tmp_path: Path) -> None:
    root, source, _ = _fixture(tmp_path)
    result = record_target_isolation_attestation(
        isolation_root=root,
        current_revision="b" * 40,
        quality_note="Reviewed every source/context pair; only the requested performer is visible on each isolated side.",
        confirm_isolation=True,
    )
    receipt_path = Path(result["receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["authority_scope"] == "isolated-sampled-frame-set-only"
    assert receipt["human_isolation_attested"] is True
    assert receipt["all_isolation_samples_reviewed"] is True
    assert receipt["visible_cross_person_contamination_absent"] is True
    assert receipt["target_isolated_source_authority"] is True
    assert receipt["photoidentity_source_evidence_authority"] is False
    assert receipt["reconstruction_permitted"] is False
    assert receipt["production_activation"] is False
    assert receipt["isolated_frame_count"] == 3
    assert str(source.resolve()) not in receipt_path.read_text(encoding="utf-8")


def test_human_isolation_attestation_requires_explicit_confirmation_and_exact_candidate_revision(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    with pytest.raises(PhotoIdentityTargetIsolationAttestationError, match="explicit human"):
        record_target_isolation_attestation(
            isolation_root=root,
            current_revision="b" * 40,
            quality_note="This is a deliberate human review note for the isolation candidate.",
            confirm_isolation=False,
        )
    with pytest.raises(PhotoIdentityTargetIsolationAttestationError, match="different BodyRig revision"):
        record_target_isolation_attestation(
            isolation_root=root,
            current_revision="c" * 40,
            quality_note="This is a deliberate human review note for the isolation candidate.",
            confirm_isolation=True,
        )


def test_human_isolation_attestation_rehashes_original_source_and_every_isolated_frame(tmp_path: Path) -> None:
    root, source, isolated = _fixture(tmp_path)
    source.write_bytes(b"changed original source")
    with pytest.raises(PhotoIdentityTargetIsolationAttestationError, match="original source media bytes changed"):
        record_target_isolation_attestation(
            isolation_root=root,
            current_revision="b" * 40,
            quality_note="This is a deliberate human review note for the isolation candidate.",
            confirm_isolation=True,
        )

    root, _, isolated = _fixture(tmp_path / "other")
    isolated[1].write_bytes(isolated[1].read_bytes() + b"tamper")
    with pytest.raises(PhotoIdentityTargetIsolationAttestationError, match="isolated review frame bytes changed"):
        record_target_isolation_attestation(
            isolation_root=root,
            current_revision="b" * 40,
            quality_note="This is a deliberate human review note for the isolation candidate.",
            confirm_isolation=True,
        )


def test_human_isolation_attestation_is_atomic_create_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _, _ = _fixture(tmp_path)
    output = root / "photoidentity-target-isolation-attestation.json"

    def competing_link(_source: Path | str, destination: Path | str) -> None:
        Path(destination).write_bytes(b"other-writer-won")
        raise FileExistsError("simulated race")

    monkeypatch.setattr(attestation.os, "link", competing_link)
    with pytest.raises(PhotoIdentityTargetIsolationAttestationError, match="already exists"):
        record_target_isolation_attestation(
            isolation_root=root,
            current_revision="b" * 40,
            quality_note="Reviewed every target-isolation sample and confirmed the requested performer only.",
            confirm_isolation=True,
        )
    assert output.read_bytes() == b"other-writer-won"


def test_machine_overlap_does_not_synthesize_or_block_human_authority(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    public_path = root / "target-isolation-candidate.json"
    public = json.loads(public_path.read_text(encoding="utf-8"))
    public["max_other_overlap_fraction"] = 0.95
    public["p95_other_overlap_fraction"] = 0.80
    public["high_overlap_state_count"] = 9
    public["severe_overlap_state_count"] = 7
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    private_path = root / "private-target-isolation" / "private-isolation-index.json"
    private = json.loads(private_path.read_text(encoding="utf-8"))
    private["public_manifest_sha256"] = _sha(public_path)
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")

    result = record_target_isolation_attestation(
        isolation_root=root,
        current_revision="b" * 40,
        quality_note="Despite bbox overlap, I reviewed every actual isolated image and no other performer pixels are visible.",
        confirm_isolation=True,
    )
    assert result["target_isolated_source_authority"] is True
    assert result["max_other_overlap_fraction"] == 0.95
