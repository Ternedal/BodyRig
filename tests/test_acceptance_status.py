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


def evidence_path(fixture: GateFixture, prefix: str, name: str, *, legacy: bool = False) -> Path:
    return fixture.directory / name if legacy else fixture.directory / f"{prefix}-evidence" / name


def probe(
    fixture: GateFixture,
    prefix: str,
    platform: str,
    unity_platform: str,
    device: str,
    *,
    legacy: bool = False,
) -> Path:
    return write_json(
        evidence_path(fixture, prefix, f"{prefix}-probe.json", legacy=legacy),
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


def deformation(
    fixture: GateFixture,
    prefix: str,
    platform: str,
    unity_platform: str,
    device: str,
    *,
    legacy: bool = False,
) -> Path:
    return write_json(
        evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json", legacy=legacy),
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


def attestation(fixture: GateFixture, prefix: str, platform: str, *, legacy: bool = False) -> Path:
    name = "bodyrig-renderer-acceptance-windows.json" if prefix == "windows" else "bodyrig-renderer-acceptance-quest.json"
    probe_path = evidence_path(fixture, prefix, f"{prefix}-probe.json", legacy=legacy)
    deformation_path = evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json", legacy=legacy)
    probe_value = json.loads(probe_path.read_text(encoding="utf-8"))
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


def complete_windows(fixture: GateFixture, *, legacy: bool = False) -> None:
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig", legacy=legacy)
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig", legacy=legacy)
    attestation(fixture, "windows", "windows-unity-univrm", legacy=legacy)


def complete_quest(fixture: GateFixture, *, legacy: bool = False) -> None:
    probe(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2", legacy=legacy)
    deformation(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2", legacy=legacy)
    attestation(fixture, "quest", "android-quest-class", legacy=legacy)


def renderer_summary(fixture: GateFixture, prefix: str) -> dict:
    probe_path = evidence_path(fixture, prefix, f"{prefix}-probe.json")
    deformation_path = evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json")
    attestation_path = fixture.directory / f"bodyrig-renderer-acceptance-{prefix}.json"
    probe_value = json.loads(probe_path.read_text(encoding="utf-8"))
    deformation_value = json.loads(deformation_path.read_text(encoding="utf-8"))
    attestation_value = json.loads(attestation_path.read_text(encoding="utf-8"))
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
    gate_value = json.loads(fixture.gate_path.read_text(encoding="utf-8"))
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


def test_acceptance_state_machine_uses_atomic_evidence_directories(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-probe"

    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "windows-attestation"
    assert "windows-evidence" in (status.next_command or "")

    attestation(fixture, "windows", "windows-unity-univrm")
    assert inspect_acceptance_dir(tmp_path).gate == "quest-probe"

    probe(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    deformation(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-attestation"
    assert "quest-evidence" in (status.next_command or "")

    attestation(fixture, "quest", "android-quest-class")
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "release"
    assert "windows-evidence" in (status.next_command or "")
    assert "quest-evidence" in (status.next_command or "")


def test_complete_legacy_root_layout_remains_readable(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture, legacy=True)
    status = inspect_acceptance_dir(tmp_path)
    assert status.gate == "quest-probe"
    probe(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2", legacy=True)
    deformation(fixture, "quest", "android-quest-class", "Android", "Meta Quest 2", legacy=True)
    assert inspect_acceptance_dir(tmp_path).gate == "quest-attestation"


def test_dedicated_and_legacy_layout_together_is_ambiguous(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig", legacy=True)
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig", legacy=True)
    with pytest.raises(AcceptanceStatusError, match="Ambiguous windows evidence"):
        inspect_acceptance_dir(tmp_path)


def test_release_status_validates_exact_final_artifact_shape_and_evidence(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    write_release(fixture)

    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "complete"
    assert status.gate == "release"
    assert status.next_command is None


def test_release_status_rejects_old_wrong_renderer_revision_field_name(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    release_path = write_release(fixture)
    value = json.loads(release_path.read_text(encoding="utf-8"))
    summary = value["renderer_acceptance"]["windows_unity_univrm"]
    summary["renderer_bodyrig_revision"] = summary.pop("bodyrig_revision")
    write_json(release_path, value)

    with pytest.raises(AcceptanceStatusError, match="renderer summary fields are not canonical"):
        inspect_acceptance_dir(tmp_path)


def test_release_status_rejects_tampered_quality_summary(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    release_path = write_release(fixture)
    value = json.loads(release_path.read_text(encoding="utf-8"))
    value["renderer_acceptance"]["windows_unity_univrm"]["quality_review_pass"] = False
    write_json(release_path, value)

    with pytest.raises(AcceptanceStatusError, match="structured human quality summary is not a PASS"):
        inspect_acceptance_dir(tmp_path)


def test_release_status_rejects_tampered_automated_summary(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    complete_quest(fixture)
    release_path = write_release(fixture)
    value = json.loads(release_path.read_text(encoding="utf-8"))
    value["automated_acceptance"]["package_sha256"] = "0" * 64
    write_json(release_path, value)

    with pytest.raises(AcceptanceStatusError, match="package_sha256 no longer matches Gate A evidence"):
        inspect_acceptance_dir(tmp_path)


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
    probe_path = tmp_path / "windows-evidence" / "windows-probe.json"
    value = json.loads(probe_path.read_text(encoding="utf-8"))
    value["graphics_device"] = "mutated after attestation"
    write_json(probe_path, value)
    with pytest.raises(AcceptanceStatusError, match="no longer binds"):
        inspect_acceptance_dir(tmp_path)


def test_gate_a_package_tamper_fails_closed(tmp_path: Path) -> None:
    gate_a(tmp_path)
    (tmp_path / f"{BODY_ID}.mrbody").write_bytes(b"mutated package\n")
    with pytest.raises(AcceptanceStatusError, match="Accepted .mrbody bytes no longer match Gate A"):
        inspect_acceptance_dir(tmp_path)


def test_gate_a_skin_qa_tamper_fails_closed(tmp_path: Path) -> None:
    gate_a(tmp_path)
    write_json(tmp_path / "bodyrig-skin-qa.json", {"mutated": True})
    with pytest.raises(AcceptanceStatusError, match="Anatomical skin QA evidence bytes no longer match Gate A"):
        inspect_acceptance_dir(tmp_path)


def test_partial_dedicated_pair_is_inconsistent(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    with pytest.raises(AcceptanceStatusError, match="canonical evidence is incomplete"):
        inspect_acceptance_dir(tmp_path)
