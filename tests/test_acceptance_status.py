from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatusError, _session_status, inspect_acceptance_dir

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
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


@dataclass(frozen=True)
class GateFixture:
    directory: Path
    gate_path: Path
    package_hash: str
    runtime_hash: str


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_a(directory: Path) -> GateFixture:
    directory.mkdir(parents=True, exist_ok=True)
    package_path = directory / f"{BODY_ID}.mrbody"
    package_path.write_bytes(b"exact accepted mrbody bytes\n")
    runtime_path = directory / "runtime" / "runtime-manifest.json"
    write_json(runtime_path, {"format": "bodyrig-runtime-assets", "version": 1, "body_id": BODY_ID})
    session_path = write_json(directory / "bodyrig-physical-clone-session.json", {"format": "bodyrig-physical-clone-session", "version": 1})
    readiness_path = write_json(directory / "bodyrig-rig-readiness.json", {"format": "bodyrig-rig-readiness", "version": 1, "ready": True})
    skin_path = write_json(directory / "bodyrig-skin-qa.json", {"format": "bodyrig-skin-qa", "version": 1, "structural_pass": True})
    package_hash = sha(package_path)
    runtime_hash = sha(runtime_path)
    gate_path = write_json(
        directory / "bodyrig-acceptance.json",
        {
            "format": "bodyrig-rig-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "automated_pass": True,
            "physical_renderer_acceptance": "pending",
            "production_activation": False,
            "physical_clone": {
                "mode": "stash-sith-high-fidelity",
                "session_sha256": sha(session_path),
                "readiness_sha256": sha(readiness_path),
            },
            "skin_qa": {
                "report_sha256": sha(skin_path),
                "structural_pass": True,
                "manual_review_required": True,
            },
            "package": {
                "body_id": BODY_ID,
                "package_sha256": package_hash,
                "placeholder_avatar": False,
            },
            "runtime": {"manifest_sha256": runtime_hash},
        },
    )
    return GateFixture(directory, gate_path, package_hash, runtime_hash)


def probe(fixture: GateFixture, prefix: str, platform: str, unity_platform: str, device: str) -> Path:
    return write_json(
        fixture.directory / f"{prefix}-probe.json",
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
            "package_sha256": fixture.package_hash,
            "runtime_manifest_sha256": fixture.runtime_hash,
            "avatar_sha256": AVATAR,
            "bodyprint_sha256": BODYPRINT,
            "vrm10_loaded": True,
            "humanoid_valid": True,
            "required_bones_valid": True,
            "active_renderer": {"name": "BodyRig Reference Renderer", "version": "test"},
        },
    )


def deformation(fixture: GateFixture, prefix: str, platform: str, unity_platform: str, device: str) -> Path:
    return write_json(
        fixture.directory / f"{prefix}-deformation-probe.json",
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
            "package_sha256": fixture.package_hash,
            "runtime_manifest_sha256": fixture.runtime_hash,
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


def attestation(fixture: GateFixture, prefix: str, platform: str) -> Path:
    name = "bodyrig-renderer-acceptance-windows.json" if prefix == "windows" else "bodyrig-renderer-acceptance-quest.json"
    probe_path = fixture.directory / f"{prefix}-probe.json"
    deformation_path = fixture.directory / f"{prefix}-deformation-probe.json"
    return write_json(
        fixture.directory / name,
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "automated_report_sha256": sha(fixture.gate_path),
            "probe_report_sha256": sha(probe_path),
            "deformation_report_sha256": sha(deformation_path),
            "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
            "package_sha256": fixture.package_hash,
            "runtime_manifest_sha256": fixture.runtime_hash,
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


def complete_windows(fixture: GateFixture) -> None:
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    attestation(fixture, "windows", "windows-unity-univrm")


def complete_quest(fixture: GateFixture) -> None:
    probe(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    deformation(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    attestation(fixture, "quest", "android-quest-class")


def test_session_pass_points_to_gate_a_without_mutating(tmp_path: Path) -> None:
    clone_root = tmp_path / "clone-run"
    clone_root.mkdir()
    readiness = write_json(tmp_path / "physical.readiness.json", {"format": "bodyrig-rig-readiness", "version": 1, "ready": True})
    session = write_json(
        tmp_path / "physical.json",
        {
            "format": "bodyrig-physical-clone-session",
            "version": 1,
            "body_id": BODY_ID,
            "bodyrig_revision": REVISION,
            "bodyrig_checkout_clean": True,
            "rig_setup_sha256": "5" * 64,
            "readiness_sha256": sha(readiness),
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
    fixture = gate_a(tmp_path)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-probe"
    assert "run-windows-renderer-probe.ps1" in (status.next_command or "")

    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-attestation"
    assert "-DeformationReport" in (status.next_command or "")

    attestation(fixture, "windows", "windows-unity-univrm")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-probe"

    probe(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    deformation(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-attestation"

    attestation(fixture, "quest", "android-quest-class")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "release"
    assert status.state == "ready"
    assert "complete-acceptance.ps1" in (status.next_command or "")


def test_release_status_verifies_attestation_hashes_and_renderer_revision(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    windows_att = tmp_path / "bodyrig-renderer-acceptance-windows.json"
    quest_att = tmp_path / "bodyrig-renderer-acceptance-quest.json"
    write_json(
        tmp_path / "bodyrig-release-acceptance.json",
        {
            "format": "bodyrig-release-acceptance",
            "version": 1,
            "bodyrig_revision": REVISION,
            "renderer_acceptance": {
                "windows_unity_univrm": {"renderer_bodyrig_revision": REVISION, "report_sha256": sha(windows_att)},
                "android_quest_class": {"renderer_bodyrig_revision": REVISION, "report_sha256": sha(quest_att)},
            },
            "release_gate_pass": True,
            "production_activation": True,
        },
    )
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "complete"
    assert status.next_command is None


def test_wrong_embedded_renderer_revision_fails_closed(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    path = probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["bodyrig_revision"] = OTHER_REVISION
    write_json(path, value)
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    with pytest.raises(AcceptanceStatusError, match="different BodyRig revision"):
        inspect_acceptance_dir(tmp_path)


def test_attestation_hash_tamper_fails_closed(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    probe_path = tmp_path / "windows-probe.json"
    value = json.loads(probe_path.read_text(encoding="utf-8"))
    value["graphics_device"] = "mutated after attestation"
    write_json(probe_path, value)
    with pytest.raises(AcceptanceStatusError, match="no longer binds"):
        inspect_acceptance_dir(tmp_path)


def test_gate_a_package_tamper_fails_closed(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    (tmp_path / f"{BODY_ID}.mrbody").write_bytes(b"mutated package\n")
    with pytest.raises(AcceptanceStatusError, match="Accepted .mrbody bytes no longer match Gate A"):
        inspect_acceptance_dir(tmp_path)


def test_gate_a_skin_qa_tamper_fails_closed(tmp_path: Path) -> None:
    gate_a(tmp_path)
    write_json(tmp_path / "bodyrig-skin-qa.json", {"mutated": True})
    with pytest.raises(AcceptanceStatusError, match="Anatomical skin QA evidence bytes no longer match Gate A"):
        inspect_acceptance_dir(tmp_path)


def test_deformation_without_machine_probe_is_inconsistent(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    with pytest.raises(AcceptanceStatusError, match="without its machine probe"):
        inspect_acceptance_dir(tmp_path)
