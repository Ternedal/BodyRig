from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_identity_calibration_provenance as provenance
from bodyrig.photoreal_identity_calibration_provenance import (
    PhotorealIdentityCalibrationProvenanceError,
    bind_negative_inventory_provenance,
    build_identity_calibration_provenance_files,
)


def test_calibration_provenance_seal_binds_core_and_inventory() -> None:
    calibration = {
        "format": "bodyrig-photoreal-identity-calibration",
        "identity_calibration_sha256": "a" * 64,
    }
    inventory_sha256 = "e" * 64

    sealed = bind_negative_inventory_provenance(calibration, inventory_sha256)

    binding = {
        "identity_calibration_core_sha256": "a" * 64,
        "negative_inventory_sha256": inventory_sha256,
    }
    expected = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert sealed["identity_calibration_core_sha256"] == "a" * 64
    assert sealed["negative_inventory_sha256"] == inventory_sha256
    assert sealed["identity_calibration_sha256"] == expected
    assert calibration == {
        "format": "bodyrig-photoreal-identity-calibration",
        "identity_calibration_sha256": "a" * 64,
    }


def test_calibration_provenance_seal_changes_with_inventory() -> None:
    calibration = {"identity_calibration_sha256": "a" * 64}

    first = bind_negative_inventory_provenance(calibration, "e" * 64)
    second = bind_negative_inventory_provenance(calibration, "f" * 64)

    assert first["identity_calibration_core_sha256"] == second["identity_calibration_core_sha256"]
    assert first["identity_calibration_sha256"] != second["identity_calibration_sha256"]


def test_calibration_provenance_seal_rejects_invalid_inventory_digest() -> None:
    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="negative inventory SHA-256"):
        bind_negative_inventory_provenance({"identity_calibration_sha256": "a" * 64}, "not-a-sha")


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

    def _authorized(bank, plan, observations, inventory):
        captured.update(
            {
                "bank": bank,
                "plan": plan,
                "observations": observations,
                "inventory": inventory,
            }
        )
        return {
            "format": "bodyrig-photoreal-identity-calibration",
            "identity_calibration_sha256": "a" * 64,
        }

    monkeypatch.setattr(provenance, "build_identity_calibration_authorized", _authorized)

    result = build_identity_calibration_provenance_files(
        bank_path,
        plan_path,
        observations_path,
        inventory_path,
        output_path,
    )

    assert captured["plan"] == {"negative_inventory_sha256": "e" * 64}
    assert result["identity_calibration_core_sha256"] == "a" * 64
    assert result["negative_inventory_sha256"] == "e" * 64
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
        lambda *_args: {"identity_calibration_sha256": "a" * 64},
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
        lambda *_args: {"identity_calibration_sha256": "a" * 64},
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
