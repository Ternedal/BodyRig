from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatusError, _session_status, inspect_acceptance_dir

REVISION = "a" * 40
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
QUALITY_REVIEW = {
    "revision": "bodyrig-human-quality-v1",
    "full_deformation_sequence_reviewed": True,
    "source_identity_texture_acceptable": True,
    "geometry_proportions_acceptable": True,
    "upper_body_deformation_acceptable": True,
    "lower_body_deformation_acceptable": True,
    "cross_limb_leakage_absent": True,
    "skin_qa_considered": True,
}


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_version(path: Path, value: object) -> None:
    payload = read_json(path)
    payload["version"] = value
    write_json(path, payload)


def session_report(tmp_path: Path, *, version: object) -> Path:
    clone_root = tmp_path / "clone-run"
    clone_root.mkdir()
    readiness = write_json(
        tmp_path / "physical.readiness.json",
        {"format": "bodyrig-rig-readiness", "version": 1, "ready": True},
    )
    return write_json(
        tmp_path / "physical.json",
        {
            "format": "bodyrig-physical-clone-session",
            "version": version,
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


def gate_a(directory: Path) -> GateFixture:
    directory.mkdir(parents=True, exist_ok=True)
    package_path = directory / f"{BODY_ID}.mrbody"
    package_path.write_bytes(b"exact accepted mrbody bytes\n")
    runtime_path = directory / "runtime" / "runtime-manifest.json"
    write_json(runtime_path, {"format": "bodyrig-runtime-assets", "version": 1, "body_id": BODY_ID})
    session_path = write_json(
        directory / "bodyrig-physical-clone-session.json",
        {"format": "bodyrig-physical-clone-session", "version": 1},
    )
    readiness_path = write_json(
        directory / "bodyrig-rig-readiness.json",
        {"format": "bodyrig-rig-readiness", "version": 1, "ready": True},
    )
    skin_path = write_json(
        directory / "bodyrig-skin-qa.json",
        {"format": "bodyrig-skin-qa", "version": 1, "structural_pass": True},
    )
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
                "automated_assessment": "low-risk",
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


def evidence_path(fixture: GateFixture, prefix: str, name: str) -> Path:
    return fixture.directory / f"{prefix}-evidence" / name


def probe(fixture: GateFixture, prefix: str, platform: str, unity_platform: str, device: str) -> Path:
    return write_json(
        evidence_path(fixture, prefix, f"{prefix}-probe.json"),
        {
            "format": "bodyrig-renderer-probe",
            "version": 1,
            "observed_at": f"2026-08-24T12:0{0 if prefix == 'windows' else 2}:00Z",
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
        evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json"),
        {
            "format": "bodyrig-deformation-probe",
            "version": 1,
            "observed_at": f"2026-08-24T12:0{1 if prefix == 'windows' else 3}:00Z",
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
    probe_path = evidence_path(fixture, prefix, f"{prefix}-probe.json")
    deformation_path = evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json")
    probe_value = read_json(probe_path)
    return write_json(
        fixture.directory / name,
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1,
            "attested_at": f"2026-08-24T12:1{0 if prefix == 'windows' else 1}:00Z",
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
            "renderer_name": probe_value["active_renderer"]["name"],
            "renderer_version": probe_value["active_renderer"]["version"],
            "unity_platform": probe_value["unity_platform"],
            "unity_version": probe_value["unity_version"],
            "graphics_device": probe_value["graphics_device"],
            "machine_probe": True,
            "deformation_probe": True,
            "result": "pass",
            "quality_review": dict(QUALITY_REVIEW),
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


def renderer_summary(fixture: GateFixture, prefix: str) -> dict:
    probe_path = evidence_path(fixture, prefix, f"{prefix}-probe.json")
    deformation_path = evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json")
    attestation_path = fixture.directory / f"bodyrig-renderer-acceptance-{prefix}.json"
    probe_value = read_json(probe_path)
    deformation_value = read_json(deformation_path)
    attestation_value = read_json(attestation_path)
    return {
        "bodyrig_revision": REVISION,
        "report_sha256": sha(attestation_path),
        "probe_report_sha256": sha(probe_path),
        "deformation_report_sha256": sha(deformation_path),
        "deformation_sequence_revision": deformation_value["sequence_revision"],
        "deformation_observed_at": deformation_value["observed_at"],
        "runtime_manifest_sha256": fixture.runtime_hash,
        "avatar_sha256": AVATAR,
        "bodyprint_sha256": BODYPRINT,
        "machine_probe": True,
        "result": "pass",
        "renderer_name": attestation_value["renderer_name"],
        "renderer_version": attestation_value["renderer_version"],
        "unity_platform": probe_value["unity_platform"],
        "unity_version": probe_value["unity_version"],
        "build_guid": probe_value["build_guid"],
        "device_model": probe_value["device_model"],
        "graphics_device": probe_value["graphics_device"],
        "quality_review_revision": "bodyrig-human-quality-v1",
        "quality_review_pass": True,
        "quality_note": attestation_value["quality_note"],
        "observed_at": probe_value["observed_at"],
        "attested_at": attestation_value["attested_at"],
    }


def write_release(fixture: GateFixture) -> Path:
    gate_value = read_json(fixture.gate_path)
    return write_json(
        fixture.directory / "bodyrig-release-acceptance.json",
        {
            "format": "bodyrig-release-acceptance",
            "version": 1,
            "completed_at": "2026-08-24T12:20:00Z",
            "bodyrig_revision": REVISION,
            "automated_acceptance": {
                "report_sha256": sha(fixture.gate_path),
                "package_sha256": fixture.package_hash,
                "body_id": BODY_ID,
                "automated_pass": True,
                "physical_clone_mode": "stash-sith-high-fidelity",
                "physical_clone_session_sha256": gate_value["physical_clone"]["session_sha256"],
                "physical_clone_readiness_sha256": gate_value["physical_clone"]["readiness_sha256"],
                "skin_qa_report_sha256": gate_value["skin_qa"]["report_sha256"],
                "skin_qa_assessment": gate_value["skin_qa"]["automated_assessment"],
                "skin_qa_manual_review_required": True,
            },
            "renderer_acceptance": {
                "windows_unity_univrm": renderer_summary(fixture, "windows"),
                "android_quest_class": renderer_summary(fixture, "quest"),
            },
            "release_gate_pass": True,
            "production_activation": True,
        },
    )


def test_boolean_session_version_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AcceptanceStatusError, match="Unsupported physical clone session format/version"):
        _session_status(session_report(tmp_path, version=True))


def test_numeric_float_session_version_remains_v1_compatible(tmp_path: Path) -> None:
    status = _session_status(session_report(tmp_path, version=1.0))
    assert status.state == "ready"
    assert status.gate == "gate-a"


def test_boolean_gate_a_version_is_rejected(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    set_version(fixture.gate_path, True)
    with pytest.raises(AcceptanceStatusError, match="Unsupported Gate A acceptance format/version"):
        inspect_acceptance_dir(tmp_path)


def test_numeric_float_gate_a_version_remains_v1_compatible(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    set_version(fixture.gate_path, 1.0)
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "ready"
    assert status.gate == "windows-probe"


def test_boolean_renderer_probe_version_is_rejected(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe_path = probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    set_version(probe_path, True)
    with pytest.raises(AcceptanceStatusError, match="Invalid renderer machine probe"):
        inspect_acceptance_dir(tmp_path)


def test_numeric_float_renderer_probe_version_remains_v1_compatible(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe_path = probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    set_version(probe_path, 1.0)
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "human-review"
    assert status.gate == "windows-attestation"


def test_boolean_deformation_probe_version_is_rejected(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation_path = deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    set_version(deformation_path, True)
    with pytest.raises(AcceptanceStatusError, match="Invalid deformation probe"):
        inspect_acceptance_dir(tmp_path)


def test_numeric_float_deformation_probe_version_remains_v1_compatible(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation_path = deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    set_version(deformation_path, 1.0)
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "human-review"
    assert status.gate == "windows-attestation"


def test_boolean_renderer_attestation_version_is_rejected(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    set_version(fixture.directory / "bodyrig-renderer-acceptance-windows.json", True)
    with pytest.raises(AcceptanceStatusError, match="Invalid renderer attestation"):
        inspect_acceptance_dir(tmp_path)


def test_numeric_float_renderer_attestation_version_remains_v1_compatible(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    set_version(fixture.directory / "bodyrig-renderer-acceptance-windows.json", 1.0)
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "ready"
    assert status.gate == "quest-probe"


def test_boolean_final_release_version_is_rejected(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    release_path = write_release(fixture)
    set_version(release_path, True)
    with pytest.raises(AcceptanceStatusError, match="Final release acceptance format/version is invalid"):
        inspect_acceptance_dir(tmp_path)


def test_numeric_float_final_release_version_remains_v1_compatible(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    release_path = write_release(fixture)
    set_version(release_path, 1.0)
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "complete"
    assert status.gate == "release"
