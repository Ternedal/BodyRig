from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from bodyrig.photoidentity_multiperformer_track_runner import (
    PhotoIdentityMultiTrackRunnerError,
    validate_track_review_batch,
)


ROOT = Path(__file__).resolve().parents[1]


def _review(source_index: int = 0) -> dict:
    return {
        "format": "bodyrig-phalp-track-review",
        "version": 1,
        "source_index": source_index,
        "tracks": [
            {
                "track_id": f"s{source_index:02d}-t7",
                "observation_count": 3,
                "first_timestamp_ms": 0,
                "last_timestamp_ms": 2000,
                "samples": [
                    {"timestamp_ms": 0, "confidence": 0.9, "bbox_tlwh": [1.0, 2.0, 30.0, 40.0]},
                    {"timestamp_ms": 2000, "confidence": 0.8, "bbox_tlwh": [2.0, 3.0, 30.0, 40.0]},
                ],
            }
        ],
        "target_track_id": None,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }


def _batch() -> dict:
    return {
        "format": "bodyrig-phalp-track-review-batch",
        "version": 1,
        "adapter": ADAPTER_NAME,
        "revision": ADAPTER_REVISION,
        "sources": [
            {
                "source_index": 0,
                "source_media_sha256": "a" * 64,
                "review": _review(0),
            }
        ],
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "appearance_embeddings_exported": False,
        "source_paths_exported": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }


def test_validator_accepts_exact_no_target_review_batch():
    value = validate_track_review_batch(_batch(), expected_source_count=1)
    assert value["adapter"] == ADAPTER_NAME
    assert value["revision"] == ADAPTER_REVISION
    assert value["target_track_selected"] is False
    assert value["sources"][0]["review"]["target_track_id"] is None


def test_validator_rejects_machine_selected_target():
    value = _batch()
    value["sources"][0]["review"]["target_track_id"] = "s00-t7"
    with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="illegally selected"):
        validate_track_review_batch(value, expected_source_count=1)


def test_validator_rejects_exported_appearance_or_paths():
    for field in ("appearance_embeddings_exported", "source_paths_exported"):
        value = _batch()
        value[field] = True
        with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="illegally enabled"):
            validate_track_review_batch(value, expected_source_count=1)


def test_validator_rejects_wrong_adapter_or_source_hash():
    value = _batch()
    value["revision"] = "wrong"
    with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="adapter authority"):
        validate_track_review_batch(value, expected_source_count=1)

    value = _batch()
    value["sources"][0]["source_media_sha256"] = "not-a-sha"
    with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="SHA-256"):
        validate_track_review_batch(value, expected_source_count=1)


def test_validator_rejects_non_finite_wire_values_and_out_of_range_samples():
    value = _batch()
    value["sources"][0]["review"]["tracks"][0]["samples"][0]["bbox_tlwh"][2] = float("inf")
    with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="finite"):
        validate_track_review_batch(value, expected_source_count=1)

    value = _batch()
    value["sources"][0]["review"]["tracks"][0]["samples"][1]["timestamp_ms"] = 3000
    with pytest.raises(PhotoIdentityMultiTrackRunnerError, match="timestamps"):
        validate_track_review_batch(value, expected_source_count=1)


def test_pinned_bridge_reuses_production_preflight_but_has_separate_output_contract():
    text = (ROOT / "bodyrig" / "bridges" / "hmr2_track_review_bridge.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "base._verify_repo" in text
    assert "base._verify_phalp_install" in text
    assert "base._verify_nmr_install" in text
    assert "base._recovery_loader_env" in text
    assert "base._ensure_phalp_smpl_cache" in text
    assert "canonicalize_phalp_track_review" in text
    assert '"appearance_embeddings_exported": False' in text
    assert '"source_paths_exported": False' in text
    assert '"target_track_selected": False' in text
    assert "visualizer" not in lowered
    assert "target_track_id" not in lowered


def test_runner_reuses_atomic_wsl_file_protocol_and_never_invokes_reconstruction():
    text = (ROOT / "bodyrig" / "photoidentity_multiperformer_track_runner.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "_run_wsl_file_protocol" in text
    assert "make_wsl_path_converter" in text
    assert "hmr2_track_review_bridge.py" in text
    assert "bodyrig-recovery-request" in text
    assert "sith" not in lowered
    assert "unity" not in lowered
    assert "run-quest" not in lowered
    assert "quest-renderer" not in lowered
    assert "production_activation" in lowered
