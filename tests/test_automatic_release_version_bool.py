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
POSE_IDS = (
    "neutral",
    "arms_abduction",
    "elbows_flexed",
    "arms_forward",
    "left_leg_lift",
    "knee_flexion",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _quality(platform: str, unity_platform: str, build_guid: str, device: str, hashes: dict[str, str]) -> dict:
    poses = []
    for index, pose_id in enumerate(POSE_IDS):
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


def _fixture(root: Path) -> tuple[Path, Path]:
    acceptance = root / "acceptance"
    runtime = acceptance / "runtime"
    runtime.mkdir(parents=True)
    avatar = runtime / "avatar.vrm"
    bodyprint = runtime / "bodyprint.json"
    avatar.write_bytes(b"vrm-bytes")
    bodyprint.write_text('{"shape":"fixture"}\n', encoding="utf-8")
    avatar_hash = _sha(avatar)
    bodyprint_hash = _sha(bodyprint)

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
    package_hash = _sha(package)

    manifest = runtime / "runtime-manifest.json"
    _write(
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
    runtime_hash = _sha(manifest)

    session = acceptance / "bodyrig-physical-clone-session.json"
    readiness = acceptance / "bodyrig-rig-readiness.json"
    session.write_text("session\n", encoding="utf-8")
    readiness.write_text("readiness\n", encoding="utf-8")

    skin = acceptance / "bodyrig-skin-qa.json"
    _write(
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
    _write(
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
                "session_sha256": _sha(session),
                "readiness_sha256": _sha(readiness),
            },
            "skin_qa": {
                "report_sha256": _sha(skin),
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
    _write(
        repo / "reference-renderer" / "renderer-contract.json",
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
        _write(
            evidence / f"{prefix}-probe.json",
            {
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
                "active_renderer": {
                    "name": "BodyRig Reference Renderer",
                    "version": "reference-v1/univrm-0.131.2",
                },
            },
        )
        _write(
            evidence / f"{prefix}-deformation-probe.json",
            {
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
                "poses": [{"id": pose, "hold_seconds": 1.5, "applied": True} for pose in POSE_IDS],
                "required_muscles_resolved": True,
                "restored_neutral": True,
                "complete": True,
                "manual_review_required": True,
            },
        )
        _write(
            evidence / f"{prefix}-deformation-quality.json",
            _quality(platform, unity_platform, build_guid, device, hashes),
        )
    return acceptance, repo


def _set_version(path: Path, version: object) -> None:
    value = _read(path)
    value["version"] = version
    _write(path, value)


def _rebind_runtime(acceptance: Path) -> str:
    runtime_path = acceptance / "runtime" / "runtime-manifest.json"
    runtime_hash = _sha(runtime_path)
    gate_path = acceptance / "bodyrig-acceptance.json"
    gate = _read(gate_path)
    gate["runtime"]["manifest_sha256"] = runtime_hash
    _write(gate_path, gate)
    return runtime_hash


def _rebind_skin(acceptance: Path) -> None:
    skin_path = acceptance / "bodyrig-skin-qa.json"
    gate_path = acceptance / "bodyrig-acceptance.json"
    gate = _read(gate_path)
    gate["skin_qa"]["report_sha256"] = _sha(skin_path)
    _write(gate_path, gate)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("runtime", "runtime manifest format/version mismatch"),
        ("skin", "skin QA format/version mismatch"),
        ("probe", "renderer probe format/version mismatch"),
        ("deformation", "deformation probe format/platform mismatch"),
        ("quality", "quality format/version mismatch"),
        ("contract", "reference renderer contract format/version mismatch"),
    ],
)
def test_automatic_release_rejects_boolean_versions_at_direct_v1_boundaries(
    tmp_path: Path,
    target: str,
    message: str,
) -> None:
    acceptance, repo = _fixture(tmp_path)
    if target == "runtime":
        _set_version(acceptance / "runtime" / "runtime-manifest.json", True)
        _rebind_runtime(acceptance)
    elif target == "skin":
        _set_version(acceptance / "bodyrig-skin-qa.json", True)
        _rebind_skin(acceptance)
    elif target == "probe":
        _set_version(acceptance / "windows-evidence" / "windows-probe.json", True)
    elif target == "deformation":
        _set_version(acceptance / "windows-evidence" / "windows-deformation-probe.json", True)
    elif target == "quality":
        _set_version(acceptance / "windows-evidence" / "windows-deformation-quality.json", True)
    else:
        _set_version(repo / "reference-renderer" / "renderer-contract.json", True)

    with pytest.raises(AutomaticReleaseGateError, match=message):
        validate_and_build(acceptance, repo, require_git_state=False)


def test_automatic_release_preserves_numeric_float_v1_across_full_production_path(tmp_path: Path) -> None:
    acceptance, repo = _fixture(tmp_path)

    _set_version(acceptance / "runtime" / "runtime-manifest.json", 1.0)
    runtime_hash = _rebind_runtime(acceptance)
    _set_version(acceptance / "bodyrig-skin-qa.json", 1.0)
    _rebind_skin(acceptance)
    _set_version(repo / "reference-renderer" / "renderer-contract.json", 1.0)

    for prefix in ("windows", "quest"):
        for name in (
            f"{prefix}-probe.json",
            f"{prefix}-deformation-probe.json",
            f"{prefix}-deformation-quality.json",
        ):
            path = acceptance / f"{prefix}-evidence" / name
            value = _read(path)
            value["version"] = 1.0
            value["runtime_manifest_sha256"] = runtime_hash
            _write(path, value)

    report = validate_and_build(acceptance, repo, require_git_state=False)

    assert report["release_gate_pass"] is True
    assert report["production_activation"] is True
    assert report["version"] == 2
