from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_platform_acceptance as m5


SHA = {
    "package": "1" * 64,
    "runtime": "2" * 64,
    "bodyprint": "3" * 64,
    "composition": "4" * 64,
    "embodiment": "5" * 64,
    "motor": "6" * 64,
    "renderer": "7" * 64,
    "deformation": "8" * 64,
    "attestation": "9" * 64,
}
REVISION = "a" * 40
BODY_ID = "body-test"
AUTHORITY_ID = "dtcomp-0123456789abcdef0123456789abcdef"
UTTERANCE_ID = "bodyrig-m4-embodiment-probe"
MOTOR_RAW = b'{"motor":2}'


def _expected(platform: str) -> dict:
    return {
        "format": m5.INPUT_FORMAT,
        "version": m5.INPUT_VERSION,
        "platform": platform,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": SHA["package"],
        "runtime_manifest_sha256": SHA["runtime"],
        "bodyprint_sha256": SHA["bodyprint"],
        "composition_authority_id": AUTHORITY_ID,
        "composition_authority_sha256": SHA["composition"],
        "embodiment_probe_sha256": SHA["embodiment"],
        "motor_state_sha256": SHA["motor"],
        "utterance_id": UTTERANCE_ID,
        "motor_state_version": 2,
        "renderer_probe_sha256": SHA["renderer"],
        "deformation_probe_sha256": SHA["deformation"],
        "renderer_attestation_sha256": SHA["attestation"],
        "source_observed_embodiment_bound": True,
        "production_activation": False,
    }


def _realization(expected: dict, manifest_path: Path, *, version: object) -> dict:
    platform = expected["platform"]
    quest = platform == "android-quest-class"
    return {
        "format": m5.REALIZATION_FORMAT,
        "version": version,
        **{key: value for key, value in expected.items() if key not in {"format", "version"}},
        "observed_at": "2026-09-12T12:00:00Z",
        "input_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "unity_platform": "Android" if quest else "WindowsPlayer",
        "unity_version": "6000.3.13f1",
        "build_guid": "quest-build-guid" if quest else "windows-build-guid",
        "device_model": "Meta Quest 2" if quest else "Windows test rig",
        "graphics_device": "fixture-gpu",
        "renderer_name": "BodyRig Reference Renderer",
        "renderer_version": "reference-v1/univrm-0.131.2",
        "realization_frame_count": 2,
        "motion_realized": True,
        "expression_realized": True,
        "gesture_realized": True,
        "gaze_realized": True,
        "posture_realized": True,
        "speech_timing_realized": True,
    }


def _write_evidence(root: Path, platform: str, *, version: object) -> Path:
    evidence = m5.platform_evidence_dir(root, platform)
    evidence.mkdir(parents=True)
    expected = _expected(platform)
    manifest = evidence / "platform-input.json"
    manifest.write_bytes(m5._canonical_json_bytes(expected))
    (evidence / "motor-state.json").write_bytes(MOTOR_RAW)
    (evidence / "realization.json").write_text(
        json.dumps(_realization(expected, manifest, version=version), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def test_realization_receipt_rejects_boolean_version(tmp_path: Path) -> None:
    expected = _expected("windows-unity-univrm")
    manifest = tmp_path / "platform-input.json"
    manifest.write_bytes(m5._canonical_json_bytes(expected))
    receipt = tmp_path / "realization.json"
    receipt.write_text(
        json.dumps(_realization(expected, manifest, version=True), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(m5.DigitalTwinPlatformAcceptanceError, match="format/version"):
        m5.validate_realization_receipt(
            receipt,
            expected_input=expected,
            input_manifest_path=manifest,
        )


def test_m5_status_fails_closed_on_boolean_realization_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_build(*, composition_authority_dir, acceptance_dir, platform):
        return _expected(platform), MOTOR_RAW

    monkeypatch.setattr(m5, "build_platform_input", fake_build)
    _write_evidence(tmp_path, "windows-unity-univrm", version=True)
    _write_evidence(tmp_path, "android-quest-class", version=1)

    status = m5.inspect_digital_twin_platform_acceptance(
        composition_authority_dir=tmp_path / "composition",
        acceptance_dir=tmp_path,
    )

    assert status["m5_ready"] is False
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["platforms"]["windows-unity-univrm"]["ready"] is False
    assert status["platforms"]["windows-unity-univrm"]["state"] == "invalid"
    assert "format/version" in status["platforms"]["windows-unity-univrm"]["message"]
    assert status["platforms"]["android-quest-class"]["ready"] is True


def test_m5_status_preserves_numeric_float_v1_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_build(*, composition_authority_dir, acceptance_dir, platform):
        return _expected(platform), MOTOR_RAW

    monkeypatch.setattr(m5, "build_platform_input", fake_build)
    _write_evidence(tmp_path, "windows-unity-univrm", version=1.0)
    _write_evidence(tmp_path, "android-quest-class", version=1.0)

    status = m5.inspect_digital_twin_platform_acceptance(
        composition_authority_dir=tmp_path / "composition",
        acceptance_dir=tmp_path,
    )

    assert status["m5_ready"] is True
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["next_gate"] == "digital_twin_final_release"
    assert status["platforms"]["windows-unity-univrm"]["ready"] is True
    assert status["platforms"]["android-quest-class"]["ready"] is True
