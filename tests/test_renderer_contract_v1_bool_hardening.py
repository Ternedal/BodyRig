import json
from pathlib import Path

import pytest

from bodyrig import automatic_activation_status as activation_status
from bodyrig import high_fidelity_release_readiness_cli as high_fidelity_cli
from bodyrig import reference_acceptance_policy as reference_policy
from bodyrig.automatic_release_gate import AutomaticReleaseGateError


def _contract(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-reference-renderer-contract",
        "version": version,
        "renderer_name": "BodyRigReferenceRenderer",
        "renderer_version": "1.0.0",
        "unity_editor_version": "6000.3.1f1",
        "univrm_version": "0.129.0",
        "univrm_revision": "a" * 40,
        "application_id": "dk.ternedal.bodyrig.reference",
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
    }


def _write_contract(root: Path, version: object) -> Path:
    path = root / "reference-renderer" / "renderer-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_contract(version)), encoding="utf-8")
    return path


def test_reference_policy_rejects_boolean_v1_and_accepts_numeric_v1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_contract(tmp_path, True)
    monkeypatch.setattr(reference_policy, "CONTRACT_PATH", path)
    assert reference_policy._load_contract() is None

    _write_contract(tmp_path, 1.0)
    loaded = reference_policy._load_contract()
    assert loaded is not None
    assert loaded["version"] == 1.0


def test_automatic_activation_rejects_boolean_v1_and_accepts_numeric_v1(tmp_path: Path) -> None:
    _write_contract(tmp_path, True)
    with pytest.raises(AutomaticReleaseGateError, match="format/version mismatch"):
        activation_status._renderer_contract(tmp_path)

    _write_contract(tmp_path, 1.0)
    loaded = activation_status._renderer_contract(tmp_path)
    assert loaded["version"] == 1.0


def test_high_fidelity_quest_adb_rejects_boolean_v1_before_toolchain_lookup(tmp_path: Path) -> None:
    _write_contract(tmp_path, True)
    with pytest.raises(high_fidelity_cli.HighFidelityReleaseReadinessCliError, match="format/version is non-canonical"):
        high_fidelity_cli._quest_adb(tmp_path)

    _write_contract(tmp_path, 1.0)
    with pytest.raises(high_fidelity_cli.HighFidelityReleaseReadinessCliError, match="pinned Unity Android adb is unavailable"):
        high_fidelity_cli._quest_adb(tmp_path)
