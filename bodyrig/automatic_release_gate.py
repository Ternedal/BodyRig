from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, _read_json, _sha256, _validate_gate_a, inspect_acceptance_dir
from .renderer_human_rejection import any_rejection_exists

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
POSES = (
    "neutral",
    "arms_abduction",
    "elbows_flexed",
    "arms_forward",
    "left_leg_lift",
    "knee_flexion",
)
PLATFORMS = {
    "windows": ("windows-unity-univrm", "WindowsPlayer"),
    "quest": ("android-quest-class", "Android"),
}
QUALITY_THRESHOLDS = {
    "min_changed_vertex_fraction": 0.005,
    "min_pose_max_displacement_ratio": 0.005,
    "max_pose_displacement_ratio": 1.25,
    "max_pose_rms_ratio": 0.5,
    "neutral_max_changed_vertex_fraction": 0.01,
    "neutral_max_rms_ratio": 0.001,
    "neutral_max_displacement_ratio": 0.005,
    "restore_max_rms_ratio": 0.001,
    "restore_max_displacement_ratio": 0.005,
    "min_reference_height_m": 0.5,
    "max_reference_height_m": 2.6,
    "min_vertex_count": 1000,
    "change_epsilon_height_ratio": 0.0001,
}


class AutomaticReleaseGateError(RuntimeError):
    pass


def _need_sha(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if not SHA256.fullmatch(text):
        raise AutomaticReleaseGateError(f"{label} is not canonical SHA-256")
    return text


def _need_revision(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if not SHA40.fullmatch(text):
        raise AutomaticReleaseGateError(f"{label} is not a canonical Git revision")
    return text


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise AutomaticReleaseGateError(f"{label} fields drifted; missing={missing}, extra={extra}")


def _require_hash(path: Path, expected: str, label: str) -> None:
    if path.is_symlink():
        raise AutomaticReleaseGateError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise AutomaticReleaseGateError(f"{label} not found: {path}")
    if _sha256(path) != expected:
        raise AutomaticReleaseGateError(f"{label} bytes changed: {path}")


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AutomaticReleaseGateError(f"git {' '.join(args)} failed: {result.stderr.strip()[-400:]}")
    return result.stdout.strip()


def _assert_git_authority(repo_root: Path, expected_revision: str) -> None:
    head = _need_revision(_git(repo_root, "rev-parse", "HEAD"), "BodyRig HEAD")
    if head != expected_revision:
        raise AutomaticReleaseGateError(f"BodyRig HEAD mismatch: expected {expected_revision}, got {head}")
    if _git(repo_root, "status", "--porcelain"):
        raise AutomaticReleaseGateError("BodyRig checkout is dirty; automatic production activation requires exact clean authority")


def _read_package_json(package: Path, name: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            raw = archive.read(name)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise AutomaticReleaseGateError(f"accepted .mrbody {name} is unavailable/invalid") from exc
    if not isinstance(value, dict):
        raise AutomaticReleaseGateError(f"accepted .mrbody {name} must be a JSON object")
    return value


def _runtime_identity(acceptance_dir: Path, gate: Any) -> tuple[str, str]:
    manifest_path = acceptance_dir / "runtime" / "runtime-manifest.json"
    manifest = _read_json(manifest_path, "Runtime manifest")
    if manifest.get("format") != "bodyrig-runtime-assets" or manifest.get("version") != 1:
        raise AutomaticReleaseGateError("runtime manifest format/version mismatch")
    if str(manifest.get("body_id") or "") != gate.body_id:
        raise AutomaticReleaseGateError("runtime body_id does not match Gate A")
    if _need_sha(manifest.get("package_sha256"), "runtime.package_sha256") != gate.package_hash:
        raise AutomaticReleaseGateError("runtime package hash does not match Gate A")
    avatar_hash = _need_sha(manifest.get("avatar_sha256"), "runtime.avatar_sha256")
    bodyprint_hash = _need_sha(manifest.get("bodyprint_sha256"), "runtime.bodyprint_sha256")
    _require_hash(acceptance_dir / "runtime" / "avatar.vrm", avatar_hash, "materialized avatar")
    _require_hash(acceptance_dir / "runtime" / "bodyprint.json", bodyprint_hash, "materialized bodyprint")
    return avatar_hash, bodyprint_hash


def _validate_provenance(acceptance_dir: Path, gate: Any, avatar_hash: str, bodyprint_hash: str) -> None:
    package = acceptance_dir / f"{gate.body_id}.mrbody"
    _require_hash(package, gate.package_hash, "accepted .mrbody")
    checksums = _read_package_json(package, "checksums.json")
    if _need_sha(checksums.get("avatar.vrm"), "checksums.avatar.vrm") != avatar_hash:
        raise AutomaticReleaseGateError("package avatar checksum does not match runtime")
    if _need_sha(checksums.get("bodyprint.json"), "checksums.bodyprint.json") != bodyprint_hash:
        raise AutomaticReleaseGateError("package bodyprint checksum does not match runtime")
    provenance = _read_package_json(package, "provenance.json")
    pipeline = provenance.get("pipeline")
    if not isinstance(pipeline, list):
        raise AutomaticReleaseGateError("package provenance has no canonical pipeline")
    visual = [item for item in pipeline if isinstance(item, dict) and item.get("stage") == "visual-identity-capture"]
    fitting = [item for item in pipeline if isinstance(item, dict) and item.get("stage") == "avatar-fitting"]
    if len(visual) != 1:
        raise AutomaticReleaseGateError("production activation requires exactly one visual-identity-capture provenance stage")
    if len(fitting) != 1 or fitting[0].get("adapter") != "sith-smplx-vrm" or str(fitting[0].get("revision")) != "1":
        raise AutomaticReleaseGateError("production activation requires built-in sith-smplx-vrm v1 fitting provenance")


def _validate_skin_qa(acceptance_dir: Path, gate_report: dict[str, Any], gate: Any, avatar_hash: str) -> tuple[str, str]:
    gate_skin = gate_report.get("skin_qa")
    if not isinstance(gate_skin, dict):
        raise AutomaticReleaseGateError("Gate A has no skin_qa object")
    skin_hash = _need_sha(gate_skin.get("report_sha256"), "Gate A skin QA hash")
    skin_path = acceptance_dir / "bodyrig-skin-qa.json"
    _require_hash(skin_path, skin_hash, "skin QA report")
    skin = _read_json(skin_path, "Skin QA report")
    if skin.get("format") != "bodyrig-skin-qa" or skin.get("version") != 1:
        raise AutomaticReleaseGateError("skin QA format/version mismatch")
    if skin.get("structural_pass") is not True:
        raise AutomaticReleaseGateError("skin QA structural_pass is not true")
    assessment = str(skin.get("automated_assessment") or "")
    if assessment != "low-risk":
        raise AutomaticReleaseGateError(f"automatic production activation requires skin QA low-risk, got {assessment or 'missing'}")
    if str(skin.get("body_id") or "") != gate.body_id:
        raise AutomaticReleaseGateError("skin QA body_id mismatch")
    if _need_sha(skin.get("package_sha256"), "skin.package_sha256") != gate.package_hash:
        raise AutomaticReleaseGateError("skin QA package hash mismatch")
    if _need_sha(skin.get("avatar_sha256"), "skin.avatar_sha256") != avatar_hash:
        raise AutomaticReleaseGateError("skin QA avatar hash mismatch")
    return skin_hash, assessment


def _validate_probe(
    path: Path,
    *,
    platform: str,
    unity_platform: str,
    revision: str,
    body_id: str,
    package_hash: str,
    runtime_hash: str,
    avatar_hash: str,
    bodyprint_hash: str,
    renderer_contract: dict[str, Any],
) -> dict[str, Any]:
    value = _read_json(path, f"{platform} renderer probe")
    if value.get("format") != "bodyrig-renderer-probe" or value.get("version") != 1:
        raise AutomaticReleaseGateError(f"{platform} renderer probe format/version mismatch")
    if value.get("platform") != platform or value.get("unity_platform") != unity_platform:
        raise AutomaticReleaseGateError(f"{platform} renderer probe platform mismatch")
    if _need_revision(value.get("bodyrig_revision"), "probe.bodyrig_revision") != revision:
        raise AutomaticReleaseGateError(f"{platform} renderer probe revision mismatch")
    if value.get("vrm10_loaded") is not True or value.get("humanoid_valid") is not True or value.get("required_bones_valid") is not True:
        raise AutomaticReleaseGateError(f"{platform} renderer probe did not prove VRM/Humanoid/bones")
    expected = {
        "body_id": body_id,
        "package_sha256": package_hash,
        "runtime_manifest_sha256": runtime_hash,
        "avatar_sha256": avatar_hash,
        "bodyprint_sha256": bodyprint_hash,
    }
    for key, expected_value in expected.items():
        actual = str(value.get(key) or "")
        if key.endswith("sha256"):
            actual = _need_sha(actual, f"probe.{key}")
        if actual != expected_value:
            raise AutomaticReleaseGateError(f"{platform} renderer probe {key} mismatch")
    renderer = value.get("active_renderer")
    if not isinstance(renderer, dict):
        raise AutomaticReleaseGateError(f"{platform} renderer identity missing")
    if renderer.get("name") != renderer_contract.get("renderer_name") or renderer.get("version") != renderer_contract.get("renderer_version"):
        raise AutomaticReleaseGateError(f"{platform} renderer identity differs from renderer contract")
    if value.get("unity_version") != renderer_contract.get("unity_editor_version"):
        raise AutomaticReleaseGateError(f"{platform} Unity version differs from renderer contract")
    if platform == "android-quest-class" and not re.search(r"quest|oculus", str(value.get("device_model") or ""), re.I):
        raise AutomaticReleaseGateError("Quest renderer probe does not identify Quest/Oculus hardware")
    for field in ("observed_at", "build_guid", "device_model", "graphics_device"):
        if not str(value.get(field) or "").strip():
            raise AutomaticReleaseGateError(f"{platform} renderer probe missing {field}")
    return value


def _validate_deformation(path: Path, *, platform: str, revision: str, probe: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(path, f"{platform} deformation probe")
    if value.get("format") != "bodyrig-deformation-probe" or value.get("version") != 1 or value.get("platform") != platform:
        raise AutomaticReleaseGateError(f"{platform} deformation probe format/platform mismatch")
    if _need_revision(value.get("bodyrig_revision"), "deformation.bodyrig_revision") != revision:
        raise AutomaticReleaseGateError(f"{platform} deformation revision mismatch")
    if value.get("sequence_revision") != "humanoid-muscle-sweep-v1" or value.get("pose_count") != 6:
        raise AutomaticReleaseGateError(f"{platform} deformation sequence mismatch")
    if value.get("required_muscles_resolved") is not True or value.get("restored_neutral") is not True or value.get("complete") is not True:
        raise AutomaticReleaseGateError(f"{platform} deformation probe incomplete")
    pose_ids = tuple(str(item.get("id") or "") for item in value.get("poses", []) if isinstance(item, dict))
    if pose_ids != POSES:
        raise AutomaticReleaseGateError(f"{platform} deformation pose order mismatch")
    for field in ("body_id", "package_sha256", "runtime_manifest_sha256", "avatar_sha256", "bodyprint_sha256", "build_guid", "unity_platform", "unity_version", "device_model"):
        if str(value.get(field) or "") != str(probe.get(field) or ""):
            raise AutomaticReleaseGateError(f"{platform} deformation/probe {field} mismatch")
    return value


def _float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AutomaticReleaseGateError(f"{label} is not numeric") from exc
    if not (number == number and abs(number) != float("inf")):
        raise AutomaticReleaseGateError(f"{label} is not finite")
    return number


def _validate_quality(path: Path, *, platform: str, revision: str, probe: dict[str, Any], deformation: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(path, f"{platform} automatic deformation quality")
    expected_fields = {
        "format","version","observed_at","bodyrig_revision","platform","unity_platform","unity_version","build_guid","device_model",
        "body_id","package_sha256","runtime_manifest_sha256","avatar_sha256","bodyprint_sha256","sequence_revision","metric_revision",
        "renderer_count","vertex_count","reference_height_m","poses","restored_neutral_rms_ratio","restored_neutral_max_displacement_ratio",
        "thresholds","machine_quality_pass","production_activation",
    }
    _require_exact_keys(value, expected_fields, f"{platform} quality receipt")
    if value.get("format") != "bodyrig-deformation-quality" or value.get("version") != 1:
        raise AutomaticReleaseGateError(f"{platform} quality format/version mismatch")
    if value.get("platform") != platform or _need_revision(value.get("bodyrig_revision"), "quality.bodyrig_revision") != revision:
        raise AutomaticReleaseGateError(f"{platform} quality platform/revision mismatch")
    if value.get("sequence_revision") != "humanoid-muscle-sweep-v1" or value.get("metric_revision") != "skinned-mesh-geometry-v1":
        raise AutomaticReleaseGateError(f"{platform} quality revision mismatch")
    if value.get("machine_quality_pass") is not True or value.get("production_activation") is not False:
        raise AutomaticReleaseGateError(f"{platform} machine quality is not a non-activating PASS")
    for field in ("body_id", "package_sha256", "runtime_manifest_sha256", "avatar_sha256", "bodyprint_sha256", "build_guid", "unity_platform", "unity_version", "device_model"):
        if str(value.get(field) or "") != str(probe.get(field) or "") or str(value.get(field) or "") != str(deformation.get(field) or ""):
            raise AutomaticReleaseGateError(f"{platform} quality identity mismatch: {field}")
    thresholds = value.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(QUALITY_THRESHOLDS):
        raise AutomaticReleaseGateError(f"{platform} quality thresholds drifted")
    for key, expected in QUALITY_THRESHOLDS.items():
        if abs(_float(thresholds.get(key), f"quality.thresholds.{key}") - float(expected)) > 1e-9:
            raise AutomaticReleaseGateError(f"{platform} quality threshold {key} drifted")
    vertex_count = int(value.get("vertex_count") or 0)
    if vertex_count < int(QUALITY_THRESHOLDS["min_vertex_count"]):
        raise AutomaticReleaseGateError(f"{platform} quality vertex count below production threshold")
    height = _float(value.get("reference_height_m"), "quality.reference_height_m")
    if not QUALITY_THRESHOLDS["min_reference_height_m"] <= height <= QUALITY_THRESHOLDS["max_reference_height_m"]:
        raise AutomaticReleaseGateError(f"{platform} reference height outside production envelope")
    poses = value.get("poses")
    if not isinstance(poses, list) or len(poses) != 6:
        raise AutomaticReleaseGateError(f"{platform} quality pose metrics are incomplete")
    if tuple(str(item.get("id") or "") for item in poses if isinstance(item, dict)) != POSES:
        raise AutomaticReleaseGateError(f"{platform} quality pose order mismatch")
    for index, item in enumerate(poses):
        if not isinstance(item, dict) or item.get("machine_pass") is not True or int(item.get("nonfinite_vertex_count") or 0) != 0:
            raise AutomaticReleaseGateError(f"{platform} quality pose {POSES[index]} did not machine-pass")
        if int(item.get("vertex_count") or 0) != vertex_count:
            raise AutomaticReleaseGateError(f"{platform} quality pose vertex count drifted")
        changed = _float(item.get("changed_vertex_fraction"), f"quality.{POSES[index]}.changed")
        rms = _float(item.get("rms_displacement_ratio"), f"quality.{POSES[index]}.rms")
        maximum = _float(item.get("max_displacement_ratio"), f"quality.{POSES[index]}.max")
        if index == 0:
            if changed > QUALITY_THRESHOLDS["neutral_max_changed_vertex_fraction"] or rms > QUALITY_THRESHOLDS["neutral_max_rms_ratio"] or maximum > QUALITY_THRESHOLDS["neutral_max_displacement_ratio"]:
                raise AutomaticReleaseGateError(f"{platform} neutral pose is not stable")
        else:
            if changed < QUALITY_THRESHOLDS["min_changed_vertex_fraction"]:
                raise AutomaticReleaseGateError(f"{platform} {POSES[index]} did not deform enough vertices")
            if maximum < QUALITY_THRESHOLDS["min_pose_max_displacement_ratio"] or maximum > QUALITY_THRESHOLDS["max_pose_displacement_ratio"] or rms > QUALITY_THRESHOLDS["max_pose_rms_ratio"]:
                raise AutomaticReleaseGateError(f"{platform} {POSES[index]} displacement metrics are outside production bounds")
    if _float(value.get("restored_neutral_rms_ratio"), "quality.restore.rms") > QUALITY_THRESHOLDS["restore_max_rms_ratio"]:
        raise AutomaticReleaseGateError(f"{platform} avatar did not restore neutral RMS")
    if _float(value.get("restored_neutral_max_displacement_ratio"), "quality.restore.max") > QUALITY_THRESHOLDS["restore_max_displacement_ratio"]:
        raise AutomaticReleaseGateError(f"{platform} avatar did not restore neutral maximum displacement")
    return value


def _renderer_entry(prefix: str, probe_path: Path, deformation_path: Path, quality_path: Path, probe: dict[str, Any], deformation: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "bodyrig_revision": str(probe["bodyrig_revision"]),
        "probe_report_sha256": _sha256(probe_path),
        "deformation_report_sha256": _sha256(deformation_path),
        "quality_report_sha256": _sha256(quality_path),
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "machine_quality_revision": "skinned-mesh-geometry-v1",
        "machine_quality_pass": True,
        "runtime_manifest_sha256": str(probe["runtime_manifest_sha256"]),
        "avatar_sha256": str(probe["avatar_sha256"]),
        "bodyprint_sha256": str(probe["bodyprint_sha256"]),
        "renderer_name": str(probe["active_renderer"]["name"]),
        "renderer_version": str(probe["active_renderer"]["version"]),
        "unity_platform": str(probe["unity_platform"]),
        "unity_version": str(probe["unity_version"]),
        "build_guid": str(probe["build_guid"]),
        "device_model": str(probe["device_model"]),
        "graphics_device": str(probe["graphics_device"]),
        "probe_observed_at": str(probe["observed_at"]),
        "deformation_observed_at": str(deformation["observed_at"]),
        "quality_observed_at": str(quality["observed_at"]),
    }


def validate_and_build(acceptance_dir: Path, repo_root: Path, *, require_git_state: bool = True) -> dict[str, Any]:
    acceptance_dir = acceptance_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    gate_path = acceptance_dir / "bodyrig-acceptance.json"
    try:
        gate = _validate_gate_a(gate_path)
    except AcceptanceStatusError as exc:
        raise AutomaticReleaseGateError(str(exc)) from exc
    gate_report = _read_json(gate_path, "Gate A acceptance")
    if any_rejection_exists(acceptance_dir):
        try:
            rejection_status = inspect_acceptance_dir(acceptance_dir)
        except AcceptanceStatusError as exc:
            raise AutomaticReleaseGateError(f"renderer human rejection is invalid: {exc}") from exc
        if rejection_status.state != "blocked" or not rejection_status.gate.endswith("-rejected"):
            raise AutomaticReleaseGateError("renderer human rejection exists without canonical blocked authority")
        raise AutomaticReleaseGateError(
            f"renderer human rejection blocks automatic release: {rejection_status.message}"
        )
    if require_git_state:
        _assert_git_authority(repo_root, gate.revision)

    runtime_hash = gate.runtime_hash
    avatar_hash, bodyprint_hash = _runtime_identity(acceptance_dir, gate)
    _validate_provenance(acceptance_dir, gate, avatar_hash, bodyprint_hash)
    skin_hash, skin_assessment = _validate_skin_qa(acceptance_dir, gate_report, gate, avatar_hash)

    contract = _read_json(repo_root / "reference-renderer" / "renderer-contract.json", "Reference renderer contract")
    if contract.get("format") != "bodyrig-reference-renderer-contract" or contract.get("version") != 1:
        raise AutomaticReleaseGateError("reference renderer contract format/version mismatch")
    if contract.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise AutomaticReleaseGateError("reference renderer deformation sequence mismatch")

    renderer_entries: dict[str, dict[str, Any]] = {}
    for prefix, (platform, unity_platform) in PLATFORMS.items():
        evidence = acceptance_dir / f"{prefix}-evidence"
        probe_path = evidence / f"{prefix}-probe.json"
        deformation_path = evidence / f"{prefix}-deformation-probe.json"
        quality_path = evidence / f"{prefix}-deformation-quality.json"
        for path, label in ((probe_path, "probe"), (deformation_path, "deformation"), (quality_path, "quality")):
            if path.is_symlink() or not path.is_file():
                raise AutomaticReleaseGateError(f"{prefix} {label} evidence missing or symlinked: {path}")
        probe = _validate_probe(
            probe_path,
            platform=platform,
            unity_platform=unity_platform,
            revision=gate.revision,
            body_id=gate.body_id,
            package_hash=gate.package_hash,
            runtime_hash=runtime_hash,
            avatar_hash=avatar_hash,
            bodyprint_hash=bodyprint_hash,
            renderer_contract=contract,
        )
        deformation = _validate_deformation(deformation_path, platform=platform, revision=gate.revision, probe=probe)
        quality = _validate_quality(quality_path, platform=platform, revision=gate.revision, probe=probe, deformation=deformation)
        renderer_entries["windows_unity_univrm" if prefix == "windows" else "android_quest_class"] = _renderer_entry(prefix, probe_path, deformation_path, quality_path, probe, deformation, quality)

    windows = renderer_entries["windows_unity_univrm"]
    quest = renderer_entries["android_quest_class"]
    for field in ("bodyrig_revision", "runtime_manifest_sha256", "avatar_sha256", "bodyprint_sha256", "renderer_name", "renderer_version", "unity_version"):
        if windows[field] != quest[field]:
            raise AutomaticReleaseGateError(f"cross-platform renderer authority mismatch: {field}")

    physical_clone = gate_report.get("physical_clone") or {}
    report = {
        "format": "bodyrig-release-acceptance",
        "version": 2,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "bodyrig_revision": gate.revision,
        "automated_acceptance": {
            "report_sha256": _sha256(gate_path),
            "package_sha256": gate.package_hash,
            "body_id": gate.body_id,
            "automated_pass": True,
            "physical_clone_mode": "stash-sith-high-fidelity",
            "physical_clone_session_sha256": _need_sha(physical_clone.get("session_sha256"), "physical clone session hash"),
            "physical_clone_readiness_sha256": _need_sha(physical_clone.get("readiness_sha256"), "physical clone readiness hash"),
            "skin_qa_report_sha256": skin_hash,
            "skin_qa_assessment": skin_assessment,
        },
        "renderer_acceptance": renderer_entries,
        "release_gate_pass": True,
        "production_activation": True,
    }
    return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output = output.expanduser().resolve()
    if output.exists():
        raise AutomaticReleaseGateError(f"automatic release receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed automatic BodyRig physical production activation gate")
    parser.add_argument("--acceptance-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    acceptance_dir = args.acceptance_dir.expanduser().resolve()
    output = args.output or acceptance_dir / "bodyrig-release-acceptance.json"
    try:
        report = validate_and_build(acceptance_dir, args.repo_root, require_git_state=True)
        write_report(report, output)
    except (AutomaticReleaseGateError, AcceptanceStatusError, OSError, ValueError) as exc:
        print(f"BODYRIG AUTOMATIC PRODUCTION GATE: FAIL | {exc}")
        return 1
    print(f"BODYRIG AUTOMATIC PRODUCTION GATE: PASS | revision {report['bodyrig_revision']}")
    print(f"production_activation=true | {Path(output).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
