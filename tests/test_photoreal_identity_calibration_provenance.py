from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_identity_calibration_provenance as provenance
from bodyrig.photoreal_identity_calibration import _canonical_calibration_digest
from bodyrig.photoreal_identity_calibration_provenance import (
    PhotorealIdentityCalibrationProvenanceError,
    bind_negative_inventory_provenance,
    build_identity_calibration_provenance_files,
)


def _valid_calibration() -> dict[str, object]:
    calibration: dict[str, object] = {
        "format": "bodyrig-photoreal-identity-calibration",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "d" * 64,
        "model_set_sha256": "c" * 64,
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "embedding_dimension": 32,
        "positive_reference_count": 4,
        "positive_group_count": 2,
        "negative_observation_count": 8,
        "negative_performer_count": 2,
        "positive_leave_group_out_cosine_min": 0.95,
        "positive_leave_group_out_cosine_median": 0.96,
        "positive_leave_group_out_cosine_max": 0.97,
        "negative_to_target_centroid_cosine_min": 0.10,
        "negative_to_target_centroid_cosine_median": 0.20,
        "negative_to_target_centroid_cosine_max": 0.30,
        "minimum_required_separation_margin": 0.05,
        "observed_separation_margin": 0.65,
        "threshold_derivation": "midpoint-positive-floor-negative-ceiling-v1",
        "match_threshold": 0.625,
        "match_threshold_calibrated": True,
        "identity_matching_authorized": True,
        "calibration_blockers": [],
        "calibration_data_teacher_input": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    calibration["identity_calibration_sha256"] = _canonical_calibration_digest(calibration)
    return calibration


def test_calibration_provenance_seal_binds_calibration_and_inventory_without_redefining_digest() -> None:
    calibration = _valid_calibration()
    original = dict(calibration)
    calibration_sha256 = str(calibration["identity_calibration_sha256"])
    inventory_sha256 = "e" * 64

    sealed = bind_negative_inventory_provenance(calibration, inventory_sha256)

    binding = {
        "identity_calibration_sha256": calibration_sha256,
        "negative_inventory_sha256": inventory_sha256,
    }
    expected = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert sealed["identity_calibration_sha256"] == calibration_sha256
    assert sealed["negative_inventory_sha256"] == inventory_sha256
    assert sealed["identity_calibration_provenance_sha256"] == expected
    assert "identity_calibration_core_sha256" not in sealed
    assert calibration == original


def test_calibration_provenance_seal_changes_only_provenance_with_inventory() -> None:
    calibration = _valid_calibration()
    calibration_sha256 = calibration["identity_calibration_sha256"]

    first = bind_negative_inventory_provenance(calibration, "e" * 64)
    second = bind_negative_inventory_provenance(calibration, "f" * 64)

    assert first["identity_calibration_sha256"] == second["identity_calibration_sha256"] == calibration_sha256
    assert first["identity_calibration_provenance_sha256"] != second["identity_calibration_provenance_sha256"]


def test_calibration_provenance_seal_rejects_invalid_calibration_digest() -> None:
    calibration = _valid_calibration()
    calibration["identity_calibration_sha256"] = True
    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="identity calibration SHA-256"):
        bind_negative_inventory_provenance(calibration, "e" * 64)


def test_calibration_provenance_seal_rejects_invalid_inventory_digest() -> None:
    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="negative inventory SHA-256"):
        bind_negative_inventory_provenance(_valid_calibration(), "not-a-sha")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_file_builder_routes_through_authority_then_persists_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bank_path = tmp_path / "bank.json"
    plan_path = tmp_path / "plan.json"
    observations_path = tmp_path / "observations.json"
    inventory_path = tmp_path / "inventory.json"
    output_path = tmp_path / "calibration.json"
    _write_json(bank_path, {"bank": True})
    _write_json(plan_path, {"negative_inventory_sha256": "e" * 64})
    _write_json(observations_path, {"observations": []})
    _write_json(inventory_path, {"inventory": True})

    captured: dict[str, object] = {}
    authorized = _valid_calibration()

    def _authorized(bank, plan, observations, inventory):
        captured.update(
            {
                "bank": bank,
                "plan": plan,
                "observations": observations,
                "inventory": inventory,
            }
        )
        return dict(authorized)

    monkeypatch.setattr(provenance, "build_identity_calibration_authorized", _authorized)

    result = build_identity_calibration_provenance_files(
        bank_path,
        plan_path,
        observations_path,
        inventory_path,
        output_path,
    )

    assert captured["plan"] == {"negative_inventory_sha256": "e" * 64}
    assert result["identity_calibration_sha256"] == authorized["identity_calibration_sha256"]
    assert result["negative_inventory_sha256"] == "e" * 64
    assert len(result["identity_calibration_provenance_sha256"]) == 64
    assert "identity_calibration_core_sha256" not in result
    assert json.loads(output_path.read_text(encoding="utf-8")) == result


def test_file_builder_rejects_missing_or_invalid_plan_inventory_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bank_path = tmp_path / "bank.json"
    plan_path = tmp_path / "plan.json"
    observations_path = tmp_path / "observations.json"
    inventory_path = tmp_path / "inventory.json"
    _write_json(bank_path, {})
    _write_json(plan_path, {"negative_inventory_sha256": True})
    _write_json(observations_path, {})
    _write_json(inventory_path, {})

    monkeypatch.setattr(
        provenance,
        "build_identity_calibration_authorized",
        lambda *_args: _valid_calibration(),
    )

    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="plan negative inventory SHA-256"):
        build_identity_calibration_provenance_files(
            bank_path,
            plan_path,
            observations_path,
            inventory_path,
            tmp_path / "out.json",
        )


def test_file_builder_is_create_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bank_path = tmp_path / "bank.json"
    plan_path = tmp_path / "plan.json"
    observations_path = tmp_path / "observations.json"
    inventory_path = tmp_path / "inventory.json"
    output_path = tmp_path / "calibration.json"
    for path, value in (
        (bank_path, {}),
        (plan_path, {"negative_inventory_sha256": "e" * 64}),
        (observations_path, {}),
        (inventory_path, {}),
    ):
        _write_json(path, value)
    output_path.write_text("sentinel\n", encoding="utf-8")

    monkeypatch.setattr(
        provenance,
        "build_identity_calibration_authorized",
        lambda *_args: _valid_calibration(),
    )

    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="already exists"):
        build_identity_calibration_provenance_files(
            bank_path,
            plan_path,
            observations_path,
            inventory_path,
            output_path,
        )
    assert output_path.read_text(encoding="utf-8") == "sentinel\n"
