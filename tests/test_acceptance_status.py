from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatusError, inspect_acceptance_dir, _session_status

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
PACKAGE = "1" * 64
RUNTIME = "2" * 64
AVATAR = "3" * 64
BODYPRINT = "4" * 64
BODY_ID = "performer-123"
POSES = [
    "neutral",
    "arms_abduction",
    "elbows_flexed",
    "arms_forward",
    "left_leg_lift",
    "knee_flexion",
]


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_a(directory: Path) -> Path:
    (directory / "runtime").mkdir(parents=True, exist_ok=True)
    return write_json(
        directory / "bodyrig-acceptance.json",
        {
            "format": "bodyrig-rig-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "automated_pass": True,
            "physical_renderer_acceptance": "pending",
            "production_activation": False,
            "physical_clone": {"mode": "stash-sith-high-fidelity"},
            "package": {
                "body_id": BODY_ID,
                "package_sha256": PACKAGE,
                "placeholder_avatar": False,
            },
            "runtime": {"manifest_sha256": RUNTIME},
        },
    )


def probe(directory: Path, prefix: str, platform: str, unity_platform: str, device: str) -> Path:
    return write_json(
        directory / f"{prefix}-probe.json",
        {
            "format": "bodyrig-renderer-probe",
            "version": 1,
            "bodyrig_revision": REVISION,
            "platform": platform,
            "unity_platform": unity_platform,
            "unity_version": "6000.3.13f1",
            "build_guid": f"{prefix}-build-guid",
            "device_model": device,
            "graphics_device": "test-gpu",
            "body_id": BODY_ID,
            "package_sha256": PACKAGE,
            "runtime_manifest_sha256": RUNTIME,
            "avatar_sha256": AVATAR,
            "bodyprint_sha256": BODYPRINT,
            "vrm10_loaded": True,
            "humanoid_valid": True,
            "required_bones_valid": True,
            "active_renderer": {"name": "BodyRig Reference Renderer", "version": "test"},
        },
    )


def deformation(directory: Path, prefix: str, platform: str, unity_platform: str, device: str) -> Path:
    return write_json(
        directory / f"{prefix}-deformation-probe.json",
        {
            "format": "bodyrig-deformation-probe",
            "version": 1,
            "bodyrig_revision": REVISION,
            "platform": platform,
            "unity_platform": unity_platform,
            "unity_version": "6000.3.13f1",
            "build_guid": f"{prefix}-build-guid",
            "device_model": device,
            "body_id": BODY_ID,
            "package_sha256": PACKAGE,
            "runtime_manifest_sha256": RUNTIME,
            "avatar_sha256": AVATAR,
            "bodyprint_sha256": BODYPRINT,
            "sequence_revision": "humanoid-muscle-sweep-v1",
            "pose_count": 6,
            "poses": [{"id": pose, "hold_seconds": 1.5, "applied": True} for pose in POSES],
            "required_muscles_resolved": True,
            "restored_neutral": True,
            "complete": True,
            "manual_review_required": True,
        },
    )


def attestation(directory: Path, prefix: str, platform: str, gate_path: Path) -> Path:
    name = (
        "bodyrig-renderer-acceptance-windows.json"
        if prefix == "windows"
        else "bodyrig-renderer-acceptance-quest.json"
    )
    probe_path = directory / f"{prefix}-probe.json"
    deformation_path = directory / f"{prefix}-deformation-probe.json"
    return write_json(
        directory / name,
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "automated_report_sha256": sha(gate_path),
            "probe_report_sha256": sha(probe_path),
            "deformation_report_sha256": sha(deformation_path),
            "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
            "package_sha256": PACKAGE,
            "runtime_manifest_sha256": RUNTIME,
            "avatar_sha256": AVATAR,
            "bodyprint_sha256": BODYPRINT,
            "body_id": BODY_ID,
            "platform": platform,
            "machine_probe": True,
            "deformation_probe": True,
            "result": "pass",
            "quality_note": "physical review acceptable",
            "production_activation": False,
        },
    )


def complete_windows(directory: Path, gate_path: Path) -> None:
    probe(directory, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(directory, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    attestation(directory, "windows", "windows-unity-univrm", gate_path)


def complete_quest(directory: Path, gate_path: Path) -> None:
    probe(directory, "quest", "android-quest-class", "Android", "Meta Quest 2")
    deformation(directory, "quest", "android-quest-class", "Android", "Meta Quest 2")
    attestation(directory, "quest", "android-quest-class", gate_path)


def test_session_pass_points_to_gate_a_without_mutating(tmp_path: Path) -> None:
    clone_root = tmp_path / "clone-run"
    clone_root.mkdir()
    session = write_json(
        tmp_path / "physical.json",
        {
            "format": "bodyrig-physical-clone-session",
            "version": 1,
            "body_id": BODY_ID,
            "bodyrig_revision": REVISION,
            "bodyrig_checkout_clean": True,
            "rig_setup_sha256": "5" * 64,
            "readiness_sha256": "6" * 64,
            "clone_output": str(clone_root),
            "status": "pass",
            "stage": "complete",
        },
    )
    status = _session_status(session)
    assert status.gate == "gate-a"
    assert status.state == "ready"
    assert "accept-physical-clone.ps1" in (status.next_command or "")
    assert not (clone_root / "acceptance").exists()


def test_acceptance_state_machine_reports_exact_next_gate(tmp_path: Path) -> None:
    gate_path = gate_a(tmp_path)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-probe"
    assert "run-windows-renderer-probe.ps1" in (status.next_command or "")

    probe(tmp_path, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(tmp_path, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-attestation"
    assert "-DeformationReport" in (status.next_command or "")

    attestation(tmp_path, "windows", "windows-unity-univrm", gate_path)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-probe"

    probe(tmp_path, "quest", "android-quest-class", "Android", "Meta Quest 2")
    deformation(tmp_path, "quest", "android-quest-class", "Android", "Meta Quest 2")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-attestation"

    attestation(tmp_path, "quest", "android-quest-class", gate_path)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "release"
    assert status.state == "ready"
    assert "complete-acceptance.ps1" in (status.next_command or "")


def test_release_status_verifies_attestation_hashes_and_renderer_revision(tmp_path: Path) -> None:
    gate_path = gate_a(tmp_path)
    complete_windows(tmp_path, gate_path)
    complete_quest(tmp_path, gate_path)
    windows_att = tmp_path / "bodyrig-renderer-acceptance-windows.json"
    quest_att = tmp_path / "bodyrig-renderer-acceptance-quest.json"
    write_json(
        tmp_path / "bodyrig-release-acceptance.json",
        {
            "format": "bodyrig-release-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "renderer_acceptance": {
                "windows_unity_univrm": {
                    "renderer_bodyrig_revision": REVISION,
                    "report_sha256": sha(windows_att),
                },
                "android_quest_class": {
                    "renderer_bodyrig_revision": REVISION,
                    "report_sha256": sha(quest_att),
                },
            },
            "release_gate_pass": True,
            "production_activation": True,
        },
    )
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "complete"
    assert status.next_command is None


def test_wrong_embedded_renderer_revision_fails_closed(tmp_path: Path) -> None:
    gate_a(tmp_path)
    path = probe(tmp_path, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["bodyrig_revision"] = OTHER_REVISION
    write_json(path, value)
    deformation(tmp_path, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    with pytest.raises(AcceptanceStatusError, match="different BodyRig revision"):
        inspect_acceptance_dir(tmp_path)


def test_attestation_hash_tamper_fails_closed(tmp_path: Path) -> None:
    gate_path = gate_a(tmp_path)
    complete_windows(tmp_path, gate_path)
    probe_path = tmp_path / "windows-probe.json"
    value = json.loads(probe_path.read_text(encoding="utf-8"))
    value["graphics_device"] = "mutated after attestation"
    write_json(probe_path, value)
    with pytest.raises(AcceptanceStatusError, match="no longer binds"):
        inspect_acceptance_dir(tmp_path)


def test_deformation_without_machine_probe_is_inconsistent(tmp_path: Path) -> None:
    gate_a(tmp_path)
    deformation(tmp_path, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    with pytest.raises(AcceptanceStatusError, match="without its machine probe"):
        inspect_acceptance_dir(tmp_path)
