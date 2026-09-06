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


def _realization(expected: dict, manifest_path: Path) -> dict:
    platform = expected["platform"]
    quest = platform == "android-quest-class"
    return {
        "format": m5.REALIZATION_FORMAT,
        "version": m5.REALIZATION_VERSION,
        **{key: value for key, value in expected.items() if key not in {"format", "version"}},
        "observed_at": "2026-09-06T10:00:00Z",
        "input_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "unity_platform": "Android" if quest else "WindowsPlayer",
        "unity_version": "6000.3.13f1",
        "build_guid": "quest-build-guid" if quest else "windows-build-guid",
        "device_model": "Meta Quest 2" if quest else "Windows test rig",
        "graphics_device": "test-gpu",
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


def _write_platform_evidence(root: Path, platform: str, *, motor_raw: bytes = b'{"motor":2}') -> Path:
    evidence = m5.platform_evidence_dir(root, platform)
    evidence.mkdir(parents=True)
    expected = _expected(platform)
    manifest_path = evidence / "platform-input.json"
    manifest_path.write_bytes(m5._canonical_json_bytes(expected))
    (evidence / "motor-state.json").write_bytes(motor_raw)
    (evidence / "realization.json").write_text(
        json.dumps(_realization(expected, manifest_path), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def test_validate_realization_requires_full_motor_surface(tmp_path: Path) -> None:
    expected = _expected("windows-unity-univrm")
    manifest = tmp_path / "platform-input.json"
    manifest.write_bytes(m5._canonical_json_bytes(expected))
    receipt = _realization(expected, manifest)
    receipt["expression_realized"] = False
    path = tmp_path / "realization.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(m5.DigitalTwinPlatformAcceptanceError, match="expression_realized"):
        m5.validate_realization_receipt(path, expected_input=expected, input_manifest_path=manifest)


def test_validate_quest_receipt_requires_real_quest_identity(tmp_path: Path) -> None:
    expected = _expected("android-quest-class")
    manifest = tmp_path / "platform-input.json"
    manifest.write_bytes(m5._canonical_json_bytes(expected))
    receipt = _realization(expected, manifest)
    receipt["device_model"] = "Generic Android Device"
    path = tmp_path / "realization.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(m5.DigitalTwinPlatformAcceptanceError, match="Quest/Oculus"):
        m5.validate_realization_receipt(path, expected_input=expected, input_manifest_path=manifest)


def test_validate_realization_is_non_activating(tmp_path: Path) -> None:
    expected = _expected("windows-unity-univrm")
    manifest = tmp_path / "platform-input.json"
    manifest.write_bytes(m5._canonical_json_bytes(expected))
    receipt = _realization(expected, manifest)
    receipt["production_activation"] = True
    path = tmp_path / "realization.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(m5.DigitalTwinPlatformAcceptanceError, match="production_activation"):
        m5.validate_realization_receipt(path, expected_input=expected, input_manifest_path=manifest)


def test_m5_status_requires_both_platforms(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    motor_raw = b'{"motor":2}'

    def fake_build(*, composition_authority_dir, acceptance_dir, platform):
        return _expected(platform), motor_raw

    monkeypatch.setattr(m5, "build_platform_input", fake_build)
    _write_platform_evidence(tmp_path, "windows-unity-univrm", motor_raw=motor_raw)

    status = m5.inspect_digital_twin_platform_acceptance(
        composition_authority_dir=tmp_path / "composition",
        acceptance_dir=tmp_path,
    )
    assert status["m5_ready"] is False
    assert status["production_activation"] is False
    assert status["platforms"]["windows-unity-univrm"]["ready"] is True
    assert status["platforms"]["android-quest-class"]["state"] == "required"
    assert status["next_gate"] == "m5:android-quest-class"


def test_m5_status_is_complete_but_never_final_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    motor_raw = b'{"motor":2}'

    def fake_build(*, composition_authority_dir, acceptance_dir, platform):
        return _expected(platform), motor_raw

    monkeypatch.setattr(m5, "build_platform_input", fake_build)
    _write_platform_evidence(tmp_path, "windows-unity-univrm", motor_raw=motor_raw)
    _write_platform_evidence(tmp_path, "android-quest-class", motor_raw=motor_raw)

    status = m5.inspect_digital_twin_platform_acceptance(
        composition_authority_dir=tmp_path / "composition",
        acceptance_dir=tmp_path,
    )
    assert status["m5_ready"] is True
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["next_gate"] == "digital_twin_final_release"
    assert not status["blockers"]


def test_m5_status_revokes_on_frozen_input_tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    motor_raw = b'{"motor":2}'

    def fake_build(*, composition_authority_dir, acceptance_dir, platform):
        return _expected(platform), motor_raw

    monkeypatch.setattr(m5, "build_platform_input", fake_build)
    evidence = _write_platform_evidence(tmp_path, "windows-unity-univrm", motor_raw=motor_raw)
    _write_platform_evidence(tmp_path, "android-quest-class", motor_raw=motor_raw)
    (evidence / "motor-state.json").write_bytes(motor_raw + b"\n")

    status = m5.inspect_digital_twin_platform_acceptance(
        composition_authority_dir=tmp_path / "composition",
        acceptance_dir=tmp_path,
    )
    assert status["m5_ready"] is False
    assert status["platforms"]["windows-unity-univrm"]["state"] == "invalid"
    assert "Motor State v2" in status["platforms"]["windows-unity-univrm"]["message"]


def test_m5_operator_wrappers_are_physical_and_create_only() -> None:
    root = Path(__file__).resolve().parents[1]
    windows = (root / "run-windows-digital-twin-probe.ps1").read_text(encoding="utf-8")
    quest = (root / "run-quest-digital-twin-probe.ps1").read_text(encoding="utf-8")

    for source in (windows, quest):
        assert "[System.Environment]::OSVersion.Platform" in source
        assert "PowerShell 7+" in source
        assert "git -C $script:RepoRoot rev-parse HEAD" in source
        assert "git -C $script:RepoRoot status --porcelain" in source
        assert "production" not in source.lower() or "non-activating" in source.lower()
    assert "digital-twin-windows-evidence" in windows
    assert "digital-twin-quest-evidence" in quest
    assert "Quest/Oculus" in quest
    assert "pinned Unity Android SDK adb.exe" in quest


def test_reference_renderer_realizes_entire_m4_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    driver = (root / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs").read_text(encoding="utf-8")
    probe = (root / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigDigitalTwinProbe.cs").read_text(encoding="utf-8")
    bootstrap = (root / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").read_text(encoding="utf-8")

    for token in (
        "ExpressionRealized",
        "GestureRealized",
        "GazeRealized",
        "PostureRealized",
        "SpeechTimingRealized",
        '_state.gesture.id == "present"',
        "ExpressionKey.Aa",
    ):
        assert token in driver
    for token in (
        "source_observed_embodiment_bound",
        "realization_frame_count",
        "motion_realized",
        "expression_realized",
        "gesture_realized",
        "gaze_realized",
        "posture_realized",
        "speech_timing_realized",
        "production_activation = false",
    ):
        assert token in probe
    assert "digital-twin" in bootstrap
    assert "Path.Combine(defaultRoot, \"digital-twin\")" in bootstrap
