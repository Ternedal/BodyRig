from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from bodyrig.automatic_release_gate import (
    AutomaticReleaseGateError,
    QUALITY_THRESHOLDS,
    validate_and_build,
)

REVISION = "a" * 40
BODY_ID = "auto-proof"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def quality(platform: str, unity_platform: str, build_guid: str, device: str, hashes: dict[str, str]) -> dict:
    poses = []
    for index, pose_id in enumerate(("neutral", "arms_abduction", "elbows_flexed", "arms_forward", "left_leg_lift", "knee_flexion")):
        poses.append(
            {
                "id": pose_id,
                "vertex_count": 10000,
                "nonfinite_vertex_count": 0,
                "changed_vertex_fraction": 0.0 if index == 0 else 0.1,
                "rms_displacement_ratio": 0.0 if index == 0 else 0.1,
                "max_displacement_ratio": 0.0 if index == 0 else 0.2,
                "machine_pass": True,
            }
        )
    return {
        "format": "bodyrig-deformation-quality",
        "version": 1,
        "observed_at": "2026-09-07T12:00:02Z",
        "bodyrig_revision": REVISION,
        "platform": platform,
        "unity_platform": unity_platform,
        "unity_version": "6000.3.13f1",
        "build_guid": build_guid,
        "device_model": device,
        "body_id": BODY_ID,
        **hashes,
        "sequence_revision": "humanoid-muscle-sweep-v1",
        "metric_revision": "skinned-mesh-geometry-v1",
        "renderer_count": 1,
        "vertex_count": 10000,
        "reference_height_m": 1.8,
        "poses": poses,
        "restored_neutral_rms_ratio": 0.0,
        "restored_neutral_max_displacement_ratio": 0.0,
        "thresholds": dict(QUALITY_THRESHOLDS),
        "machine_quality_pass": True,
        "production_activation": False,
    }


def build_fixture(root: Path) -> tuple[Path, Path]:
    acceptance = root / "acceptance"
    runtime = acceptance / "runtime"
    runtime.mkdir(parents=True)
    avatar = runtime / "avatar.vrm"
    bodyprint = runtime / "bodyprint.json"
    avatar.write_bytes(b"vrm-bytes")
    bodyprint.write_text('{"shape":"fixture"}\n', encoding="utf-8")
    avatar_hash = sha(avatar)
    bodyprint_hash = sha(bodyprint)

    package = acceptance / f"{BODY_ID}.mrbody"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("checksums.json", json.dumps({"avatar.vrm": avatar_hash, "bodyprint.json": bodyprint_hash}))
        archive.writestr(
            "provenance.json",
            json.dumps(
                {
                    "pipeline": [
                        {"stage": "visual-identity-capture", "adapter": "fixture", "revision": "1"},
                        {"stage": "avatar-fitting", "adapter": "sith-smplx-vrm", "revision": "1"},
                    ]
                }
            ),
        )
    package_hash = sha(package)

    manifest = runtime / "runtime-manifest.json"
    write_json(
        manifest,
        {
            "format": "bodyrig-runtime-assets",
            "version": 1,
            "body_id": BODY_ID,
            "package_sha256": package_hash,
            "avatar_sha256": avatar_hash,
            "bodyprint_sha256": bodyprint_hash,
        },
    )
    runtime_hash = sha(manifest)

    session = acceptance / "bodyrig-physical-clone-session.json"
    readiness = acceptance / "bodyrig-rig-readiness.json"
    session.write_text("session\n", encoding="utf-8")
    readiness.write_text("readiness\n", encoding="utf-8")

    skin = acceptance / "bodyrig-skin-qa.json"
    write_json(
        skin,
        {
            "format": "bodyrig-skin-qa",
            "version": 1,
            "body_id": BODY_ID,
            "package_sha256": package_hash,
            "avatar_sha256": avatar_hash,
            "structural_pass": True,
            "automated_assessment": "low-risk",
        },
    )

    gate = acceptance / "bodyrig-acceptance.json"
    write_json(
        gate,
        {
            "format": "bodyrig-rig-acceptance",
            "version": 1,
            "automated_pass": True,
            "production_activation": False,
            "physical_renderer_acceptance": "pending",
            "bodyrig_revision": REVISION,
            "physical_clone": {
                "mode": "stash-sith-high-fidelity",
                "session_sha256": sha(session),
                "readiness_sha256": sha(readiness),
            },
            "skin_qa": {
                "report_sha256": sha(skin),
                "structural_pass": True,
                "manual_review_required": True,
                "automated_assessment": "low-risk",
            },
            "package": {
                "body_id": BODY_ID,
                "package_sha256": package_hash,
                "placeholder_avatar": False,
            },
            "runtime": {"manifest_sha256": runtime_hash},
        },
    )

    repo = root / "repo"
    contract = repo / "reference-renderer" / "renderer-contract.json"
    write_json(
        contract,
        {
            "format": "bodyrig-reference-renderer-contract",
            "version": 1,
            "renderer_name": "BodyRig Reference Renderer",
            "renderer_version": "reference-v1/univrm-0.131.2",
            "unity_editor_version": "6000.3.13f1",
            "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        },
    )

    hashes = {
        "package_sha256": package_hash,
        "runtime_manifest_sha256": runtime_hash,
        "avatar_sha256": avatar_hash,
        "bodyprint_sha256": bodyprint_hash,
    }
    for prefix, platform, unity_platform, build_guid, device in (
        ("windows", "windows-unity-univrm", "WindowsPlayer", "win-build", "Windows rig"),
        ("quest", "android-quest-class", "Android", "quest-build", "Meta Quest 2"),
    ):
        evidence = acceptance / f"{prefix}-evidence"
        probe = {
            "format": "bodyrig-renderer-probe",
            "version": 1,
            "observed_at": "2026-09-07T12:00:00Z",
            "bodyrig_revision": REVISION,
            "platform": platform,
            "unity_platform": unity_platform,
            "unity_version": "6000.3.13f1",
            "build_guid": build_guid,
            "device_model": device,
            "graphics_device": "fixture-gpu",
            "body_id": BODY_ID,
            **hashes,
            "vrm10_loaded": True,
            "humanoid_valid": True,
            "required_bones_valid": True,
            "active_renderer": {"name": "BodyRig Reference Renderer", "version": "reference-v1/univrm-0.131.2"},
        }
        deformation = {
            "format": "bodyrig-deformation-probe",
            "version": 1,
            "observed_at": "2026-09-07T12:00:01Z",
            "bodyrig_revision": REVISION,
            "platform": platform,
            "unity_platform": unity_platform,
            "unity_version": "6000.3.13f1",
            "build_guid": build_guid,
            "device_model": device,
            "body_id": BODY_ID,
            **hashes,
            "sequence_revision": "humanoid-muscle-sweep-v1",
            "pose_count": 6,
            "poses": [{"id": p, "hold_seconds": 1.5, "applied": True} for p in ("neutral", "arms_abduction", "elbows_flexed", "arms_forward", "left_leg_lift", "knee_flexion")],
            "required_muscles_resolved": True,
            "restored_neutral": True,
            "complete": True,
            "manual_review_required": True,
        }
        write_json(evidence / f"{prefix}-probe.json", probe)
        write_json(evidence / f"{prefix}-deformation-probe.json", deformation)
        write_json(evidence / f"{prefix}-deformation-quality.json", quality(platform, unity_platform, build_guid, device, hashes))
    return acceptance, repo


def test_automatic_gate_passes_without_human_attestation(tmp_path: Path) -> None:
    acceptance, repo = build_fixture(tmp_path)
    report = validate_and_build(acceptance, repo, require_git_state=False)
    assert report["production_activation"] is True
    assert report["release_gate_pass"] is True
    assert report["version"] == 2
    assert report["automated_acceptance"]["skin_qa_assessment"] == "low-risk"


def test_automatic_gate_rejects_fake_machine_pass_when_pose_did_not_move(tmp_path: Path) -> None:
    acceptance, repo = build_fixture(tmp_path)
    path = acceptance / "windows-evidence" / "windows-deformation-quality.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["poses"][1]["changed_vertex_fraction"] = 0.0
    write_json(path, value)
    with pytest.raises(AutomaticReleaseGateError, match="did not deform enough vertices"):
        validate_and_build(acceptance, repo, require_git_state=False)


def test_automatic_gate_requires_low_risk_skin_qa(tmp_path: Path) -> None:
    acceptance, repo = build_fixture(tmp_path)
    skin = acceptance / "bodyrig-skin-qa.json"
    value = json.loads(skin.read_text(encoding="utf-8"))
    value["automated_assessment"] = "review"
    write_json(skin, value)
    gate = acceptance / "bodyrig-acceptance.json"
    gate_value = json.loads(gate.read_text(encoding="utf-8"))
    gate_value["skin_qa"]["report_sha256"] = sha(skin)
    gate_value["skin_qa"]["automated_assessment"] = "review"
    write_json(gate, gate_value)
    with pytest.raises(AutomaticReleaseGateError, match="requires skin QA low-risk"):
        validate_and_build(acceptance, repo, require_git_state=False)


def test_unity_quality_probe_is_geometry_based_and_top_wrapper_has_no_human_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigAutomaticDeformationQuality.cs").read_text(encoding="utf-8")
    top = (root / "run-automatic-production-activation.ps1").read_text(encoding="utf-8")
    assert "BakeMesh" in source
    assert "changed_vertex_fraction" in source
    assert "restored_neutral_rms_ratio" in source
    assert "BODYRIG_AUTO_EXIT_AFTER_QUALITY" in source
    assert "ConfirmQualityChecklist" not in top
    assert "QualityNote" not in top
    assert "record-reference-renderer-acceptance.ps1" not in top
