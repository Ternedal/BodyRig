from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.photoidentity_target_isolation_prepare as prepare
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from bodyrig.photoidentity_target_isolation_prepare import (
    PhotoIdentityTargetIsolationError,
    _validate_isolation_payload,
    prepare_target_isolation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _track() -> dict:
    return {
        "track_id": "s00-t7",
        "observation_count": 4,
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3000,
        "samples": [
            {"timestamp_ms": 0, "confidence": 0.95, "bbox_tlwh": [50.0, 20.0, 100.0, 180.0]},
            {"timestamp_ms": 3000, "confidence": 0.90, "bbox_tlwh": [55.0, 20.0, 100.0, 180.0]},
        ],
    }


def _machine_review(source_sha: str) -> dict:
    return {
        "format": "bodyrig-phalp-track-review-batch",
        "version": 1,
        "adapter": ADAPTER_NAME,
        "revision": ADAPTER_REVISION,
        "sources": [{
            "source_index": 0,
            "source_media_sha256": source_sha,
            "review": {
                "format": "bodyrig-phalp-track-review",
                "version": 1,
                "source_index": 0,
                "tracks": [_track()],
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


def _bridge(source_sha: str) -> dict:
    samples = [
        {"timestamp_ms": 0, "confidence": 0.95, "bbox_tlwh": [50.0, 20.0, 100.0, 180.0], "observed_other_track_count": 1, "max_other_overlap_fraction": 0.0},
        {"timestamp_ms": 1500, "confidence": 0.93, "bbox_tlwh": [52.0, 20.0, 100.0, 180.0], "observed_other_track_count": 1, "max_other_overlap_fraction": 0.05},
        {"timestamp_ms": 3000, "confidence": 0.90, "bbox_tlwh": [55.0, 20.0, 100.0, 180.0], "observed_other_track_count": 1, "max_other_overlap_fraction": 0.15},
    ]
    isolation = {
        "format": "bodyrig-phalp-target-isolation",
        "version": 1,
        "source_index": 0,
        "selected_track_id": "s00-t7",
        "identity_authority": "human-track-attestation",
        "canonical_review_track": _track(),
        "observed_state_count": 4,
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3000,
        "max_other_overlap_fraction": 0.15,
        "p95_other_overlap_fraction": 0.15,
        "high_overlap_state_count": 1,
        "severe_overlap_state_count": 0,
        "isolation_samples": samples,
        "machine_identity_selection": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    return {
        "format": "bodyrig-phalp-target-isolation-result",
        "version": 1,
        "adapter": ADAPTER_NAME,
        "revision": ADAPTER_REVISION,
        "source_media_sha256": source_sha,
        "isolation": isolation,
        "source_paths_exported": False,
        "appearance_embeddings_exported": False,
        "machine_identity_selection": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }


def _review_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "review"
    private_root = root / "private-track-review"
    private_root.mkdir(parents=True)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact multi performer source")
    source_sha = _sha(source)

    machine = _machine_review(source_sha)
    machine_path = root / "machine-track-review.json"
    machine_path.write_text(json.dumps(machine, sort_keys=True) + "\n", encoding="utf-8")

    track_candidate_id = "trackcand-" + "1" * 32
    public = {
        "format": "bodyrig-photoidentity-multiperformer-track-review-candidates",
        "version": 1,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "source_discovery_manifest_sha256": "2" * 64,
        "source_discovery_private_index_sha256": "3" * 64,
        "source_candidate_id": "multicand-" + "4" * 32,
        "scene_id": "scene-1",
        "source_media_sha256": source_sha,
        "machine_track_review_sha256": _sha(machine_path),
        "track_candidate_count": 1,
        "tracks": [{
            "track_candidate_id": track_candidate_id,
            "track_id": "s00-t7",
            "observation_count": 4,
            "first_timestamp_ms": 0,
            "last_timestamp_ms": 3000,
            "review_sample_count": 2,
            "review_sheet_sha256": "5" * 64,
            "samples": [],
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
        "format": "bodyrig-photoidentity-private-multiperformer-track-review-index",
        "version": 1,
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "public_review_manifest_sha256": _sha(public_path),
        "source_candidate_id": public["source_candidate_id"],
        "scene_id": "scene-1",
        "source_media_sha256": source_sha,
        "source_path": str(source.resolve()),
        "tracks": [{"track_candidate_id": track_candidate_id, "track_id": "s00-t7", "review_sheet": str(tmp_path / "unused.png")}],
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-review-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")

    attestation = {
        "format": "bodyrig-photoidentity-multiperformer-track-attestation",
        "version": 1,
        "policy": "human-source-track-identity-v1",
        "bodyrig_revision": "a" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_candidate_id": public["source_candidate_id"],
        "source_media_sha256": source_sha,
        "public_review_manifest_sha256": _sha(public_path),
        "private_review_index_sha256": _sha(private_path),
        "machine_track_review_sha256": _sha(machine_path),
        "track_candidate_id": track_candidate_id,
        "selected_track_id": "s00-t7",
        "review_sheet_sha256": "5" * 64,
        "review_sample_count": 2,
        "human_identity_attested": True,
        "human_identity_note": "Reviewed exact source-derived track frames.",
        "attested_at_utc": "2026-09-10T20:00:00Z",
        "source_paths_persisted": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    (root / "photoidentity-multiperformer-track-attestation.json").write_text(
        json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root, source, source_sha


def test_prepare_accepts_ancestor_attestation_revision_and_materializes_path_free_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    review, source, source_sha = _review_fixture(tmp_path)
    monkeypatch.setattr(prepare, "_run_target_isolation", lambda **kwargs: _bridge(source_sha))

    def fake_extract(*, ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 240), (120, 130, 140)).save(output, format="PNG")

    monkeypatch.setattr(prepare, "_extract_frame", fake_extract)
    output = tmp_path / "isolation"
    result = prepare_target_isolation(
        review_root=review,
        output_dir=output,
        current_revision="b" * 40,
        ffmpeg="ffmpeg",
        external_python="/opt/recovery/python",
        four_d_humans_repo="/opt/4D-Humans",
        phalp_repo="/opt/PHALP",
        distribution="Ubuntu-22.04",
    )
    public_path = Path(result["public_manifest"])
    public = json.loads(public_path.read_text(encoding="utf-8"))
    assert public["attestation_revision"] == "a" * 40
    assert public["isolation_operator_revision"] == "b" * 40
    assert public["source_paths_persisted"] is False
    assert public["machine_identity_selection"] is False
    assert public["human_isolation_review_required"] is True
    assert public["target_isolated_source_authority"] is False
    assert public["photoidentity_source_evidence_authority"] is False
    assert public["reconstruction_permitted"] is False
    assert str(source.resolve()) not in public_path.read_text(encoding="utf-8")

    private = json.loads(Path(result["private_index"]).read_text(encoding="utf-8"))
    assert private["source_path"] == str(source.resolve())
    assert ".stage-" not in private["contact_sheet"]
    first_isolated = Path(private["samples"][0]["isolated_frame"])
    with Image.open(first_isolated) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
        assert image.getpixel((100, 100)) == (120, 130, 140)


def test_prepare_fails_closed_when_rerun_track_fingerprint_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    review, _, source_sha = _review_fixture(tmp_path)
    payload = _bridge(source_sha)
    payload["isolation"]["canonical_review_track"]["observation_count"] = 999
    monkeypatch.setattr(prepare, "_run_target_isolation", lambda **kwargs: payload)
    with pytest.raises(PhotoIdentityTargetIsolationError, match="fingerprint differs"):
        prepare_target_isolation(
            review_root=review,
            output_dir=tmp_path / "isolation",
            current_revision="b" * 40,
            ffmpeg="ffmpeg",
            external_python="/opt/recovery/python",
            four_d_humans_repo="/opt/4D-Humans",
            phalp_repo="/opt/PHALP",
            distribution="Ubuntu-22.04",
        )


def test_bridge_receiver_rejects_illegal_authority_and_nonfinite_overlap() -> None:
    payload = _bridge("a" * 64)
    payload["target_isolated_source_authority"] = True
    with pytest.raises(PhotoIdentityTargetIsolationError, match="illegally enabled"):
        _validate_isolation_payload(payload, expected_track_id="s00-t7")

    payload = _bridge("a" * 64)
    payload["isolation"]["max_other_overlap_fraction"] = float("nan")
    with pytest.raises(PhotoIdentityTargetIsolationError, match="finite"):
        _validate_isolation_payload(payload, expected_track_id="s00-t7")


def test_prepare_fails_if_source_changes_during_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    review, source, source_sha = _review_fixture(tmp_path)
    monkeypatch.setattr(prepare, "_run_target_isolation", lambda **kwargs: _bridge(source_sha))
    calls = 0

    def mutating_extract(*, ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
        nonlocal calls
        calls += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 240), "gray").save(output, format="PNG")
        if calls == 1:
            source.write_bytes(b"changed while isolation was running")

    monkeypatch.setattr(prepare, "_extract_frame", mutating_extract)
    with pytest.raises(PhotoIdentityTargetIsolationError, match="changed during"):
        prepare_target_isolation(
            review_root=review,
            output_dir=tmp_path / "isolation",
            current_revision="b" * 40,
            ffmpeg="ffmpeg",
            external_python="/opt/recovery/python",
            four_d_humans_repo="/opt/4D-Humans",
            phalp_repo="/opt/PHALP",
            distribution="Ubuntu-22.04",
        )
