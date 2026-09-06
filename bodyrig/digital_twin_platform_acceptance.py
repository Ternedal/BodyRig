from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .acceptance_status import (
    AcceptanceStatusError,
    PlatformPaths,
    _platform_stage,
    _read_json,
    _validate_gate_a,
)
from .digital_twin_composition_authority import (
    DigitalTwinCompositionAuthorityError,
    read_composition_authority,
)

INPUT_FORMAT = "bodyrig-digital-twin-platform-input"
INPUT_VERSION = 1
REALIZATION_FORMAT = "bodyrig-digital-twin-platform-realization"
REALIZATION_VERSION = 1
STATUS_FORMAT = "bodyrig-digital-twin-platform-status"
STATUS_VERSION = 1

PLATFORMS = {
    "windows-unity-univrm": {
        "prefix": "windows",
        "attestation": "bodyrig-renderer-acceptance-windows.json",
        "unity_platform": "WindowsPlayer",
        "evidence_dir": "digital-twin-windows-evidence",
        "command": "run-windows-digital-twin-probe.ps1",
    },
    "android-quest-class": {
        "prefix": "quest",
        "attestation": "bodyrig-renderer-acceptance-quest.json",
        "unity_platform": "Android",
        "evidence_dir": "digital-twin-quest-evidence",
        "command": "run-quest-digital-twin-probe.ps1",
    },
}

INPUT_FIELDS = {
    "format",
    "version",
    "platform",
    "bodyrig_revision",
    "body_id",
    "package_sha256",
    "runtime_manifest_sha256",
    "bodyprint_sha256",
    "composition_authority_id",
    "composition_authority_sha256",
    "embodiment_probe_sha256",
    "motor_state_sha256",
    "utterance_id",
    "motor_state_version",
    "renderer_probe_sha256",
    "deformation_probe_sha256",
    "renderer_attestation_sha256",
    "source_observed_embodiment_bound",
    "production_activation",
}

REALIZATION_FIELDS = INPUT_FIELDS | {
    "observed_at",
    "input_manifest_sha256",
    "unity_platform",
    "unity_version",
    "build_guid",
    "device_model",
    "graphics_device",
    "renderer_name",
    "renderer_version",
    "realization_frame_count",
    "motion_realized",
    "expression_realized",
    "gesture_realized",
    "gaze_realized",
    "posture_realized",
    "speech_timing_realized",
}
REALIZATION_FIELDS -= {"format", "version"}
REALIZATION_FIELDS |= {"format", "version"}


class DigitalTwinPlatformAcceptanceError(RuntimeError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise DigitalTwinPlatformAcceptanceError(f"Could not hash evidence file: {path}") from exc
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigitalTwinPlatformAcceptanceError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DigitalTwinPlatformAcceptanceError(f"{label} must be a JSON object: {path}")
    return value


def _platform(value: str) -> dict[str, str]:
    try:
        return dict(PLATFORMS[value])
    except KeyError as exc:
        raise DigitalTwinPlatformAcceptanceError(f"Unsupported digital-twin platform: {value}") from exc


def _composition_bundle(directory: Path, *, package_path: Path) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes]:
    authority_dir = directory.expanduser().resolve()
    if not authority_dir.is_dir():
        raise DigitalTwinPlatformAcceptanceError(f"M4 composition authority directory not found: {authority_dir}")
    try:
        if authority_dir.parents[2].name != "digital-twin-composition-authorities":
            raise IndexError
        root = authority_dir.parents[3]
    except IndexError as exc:
        raise DigitalTwinPlatformAcceptanceError("M4 composition authority path is not under the canonical authority root") from exc

    person_revision = authority_dir.parent.name
    person_id = authority_dir.parent.parent.name
    authority_id = authority_dir.name
    try:
        authority = read_composition_authority(
            root,
            person_id=person_id,
            person_revision=person_revision,
            authority_id=authority_id,
            body_package_path=package_path,
        )
    except (DigitalTwinCompositionAuthorityError, OSError, ValueError) as exc:
        raise DigitalTwinPlatformAcceptanceError(f"M4 composition authority is invalid: {exc}") from exc

    authority_path = authority_dir / "authority.json"
    probe_path = authority_dir / "embodiment-probe.json"
    try:
        authority_raw = authority_path.read_bytes()
        probe_raw = probe_path.read_bytes()
    except OSError as exc:
        raise DigitalTwinPlatformAcceptanceError("M4 composition authority evidence is unreadable") from exc
    probe = _json(probe_path, "M4 embodiment probe")
    if probe.get("format") != "bodyrig-digital-twin-embodiment-probe" or probe.get("version") != 1:
        raise DigitalTwinPlatformAcceptanceError("M4 embodiment probe format/version is invalid")
    motor = probe.get("motor_state")
    if not isinstance(motor, dict) or motor.get("type") != "bodyrig-motor-state" or motor.get("version") != 2:
        raise DigitalTwinPlatformAcceptanceError("M4 embodiment probe does not contain Motor State v2")
    if str(motor.get("body_id") or "") != str(authority.get("body_id") or ""):
        raise DigitalTwinPlatformAcceptanceError("M4 Motor State body id no longer matches composition authority")
    if not str(motor.get("utterance_id") or "").strip():
        raise DigitalTwinPlatformAcceptanceError("M4 Motor State has no utterance id")
    if not isinstance(motor.get("embodiment"), Mapping):
        raise DigitalTwinPlatformAcceptanceError("M4 Motor State has no source-observed embodiment receipt")
    return authority, authority_raw, probe, probe_raw


def _platform_paths(acceptance_dir: Path, platform: str) -> tuple[Any, PlatformPaths, dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = _platform(platform)
    try:
        gate = _validate_gate_a(acceptance_dir / "bodyrig-acceptance.json")
        stage, paths = _platform_stage(
            acceptance_dir,
            platform=platform,
            prefix=config["prefix"],
            attestation_name=config["attestation"],
            gate=gate,
        )
    except AcceptanceStatusError as exc:
        raise DigitalTwinPlatformAcceptanceError(f"canonical physical acceptance is invalid: {exc}") from exc
    if stage != "complete":
        raise DigitalTwinPlatformAcceptanceError(
            f"canonical {platform} physical acceptance is not complete; current stage is {stage}"
        )
    try:
        probe = _read_json(paths.probe, "Renderer machine probe")
        deformation = _read_json(paths.deformation, "Deformation probe")
        attestation = _read_json(paths.attestation, "Renderer attestation")
    except AcceptanceStatusError as exc:
        raise DigitalTwinPlatformAcceptanceError(str(exc)) from exc
    return gate, paths, probe, deformation, attestation


def build_platform_input(
    *,
    composition_authority_dir: str | os.PathLike[str],
    acceptance_dir: str | os.PathLike[str],
    platform: str,
) -> tuple[dict[str, Any], bytes]:
    config = _platform(platform)
    acceptance = Path(acceptance_dir).expanduser().resolve()
    if not acceptance.is_dir():
        raise DigitalTwinPlatformAcceptanceError(f"physical acceptance directory not found: {acceptance}")

    gate, paths, renderer_probe, _deformation, _attestation = _platform_paths(acceptance, platform)
    package_path = acceptance / f"{gate.body_id}.mrbody"
    authority, authority_raw, probe, probe_raw = _composition_bundle(
        Path(composition_authority_dir),
        package_path=package_path,
    )
    if str(authority.get("body_id") or "") != gate.body_id:
        raise DigitalTwinPlatformAcceptanceError("M4 composition body id differs from physical Gate A")
    if str(authority.get("body_package_sha256") or "") != gate.package_hash:
        raise DigitalTwinPlatformAcceptanceError("M4 composition package differs from physical Gate A")
    if str(authority.get("bodyrig_revision") or "") != gate.revision:
        raise DigitalTwinPlatformAcceptanceError("M4 composition and physical Gate A were not finalized from the same BodyRig revision")

    runtime_manifest = acceptance / "runtime" / "runtime-manifest.json"
    runtime_bodyprint = acceptance / "runtime" / "bodyprint.json"
    if _sha256_file(runtime_manifest) != gate.runtime_hash:
        raise DigitalTwinPlatformAcceptanceError("physical runtime manifest bytes changed after Gate A")
    bodyprint_sha = _sha256_file(runtime_bodyprint)
    if bodyprint_sha != str(authority.get("bodyprint_sha256") or ""):
        raise DigitalTwinPlatformAcceptanceError("physical runtime BodyPrint differs from exact M4 BodyPrint")
    if str(renderer_probe.get("bodyprint_sha256") or "") != bodyprint_sha:
        raise DigitalTwinPlatformAcceptanceError("canonical renderer probe BodyPrint differs from exact M4 BodyPrint")

    motor = probe["motor_state"]
    motor_raw = _canonical_json_bytes(motor)
    expected_probe_sha = str(authority.get("embodiment_probe_sha256") or "")
    if _sha256_bytes(probe_raw) != expected_probe_sha:
        raise DigitalTwinPlatformAcceptanceError("M4 embodiment-probe bytes no longer match composition authority")

    result = {
        "format": INPUT_FORMAT,
        "version": INPUT_VERSION,
        "platform": platform,
        "bodyrig_revision": gate.revision,
        "body_id": gate.body_id,
        "package_sha256": gate.package_hash,
        "runtime_manifest_sha256": gate.runtime_hash,
        "bodyprint_sha256": bodyprint_sha,
        "composition_authority_id": str(authority["authority_id"]),
        "composition_authority_sha256": _sha256_bytes(authority_raw),
        "embodiment_probe_sha256": expected_probe_sha,
        "motor_state_sha256": _sha256_bytes(motor_raw),
        "utterance_id": str(motor["utterance_id"]),
        "motor_state_version": 2,
        "renderer_probe_sha256": _sha256_file(paths.probe),
        "deformation_probe_sha256": _sha256_file(paths.deformation),
        "renderer_attestation_sha256": _sha256_file(paths.attestation),
        "source_observed_embodiment_bound": True,
        "production_activation": False,
    }
    if str(renderer_probe.get("platform") or "") != platform or str(renderer_probe.get("unity_platform") or "") != config["unity_platform"]:
        raise DigitalTwinPlatformAcceptanceError("canonical renderer evidence platform identity is invalid")
    return result, motor_raw


def write_platform_input(
    output_dir: str | os.PathLike[str],
    *,
    composition_authority_dir: str | os.PathLike[str],
    acceptance_dir: str | os.PathLike[str],
    platform: str,
) -> dict[str, Any]:
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise DigitalTwinPlatformAcceptanceError(f"digital-twin platform input is create-only: {target}")
    manifest, motor_raw = build_platform_input(
        composition_authority_dir=composition_authority_dir,
        acceptance_dir=acceptance_dir,
        platform=platform,
    )
    target.mkdir(parents=True, exist_ok=False)
    try:
        manifest_raw = _canonical_json_bytes(manifest)
        (target / "platform-input.json").write_bytes(manifest_raw)
        (target / "motor-state.json").write_bytes(motor_raw)
    except Exception:
        for child in target.iterdir() if target.exists() else ():
            try:
                child.unlink()
            except OSError:
                pass
        try:
            target.rmdir()
        except OSError:
            pass
        raise
    return {
        **manifest,
        "input_manifest_sha256": _sha256_bytes(manifest_raw),
        "input_dir": str(target),
        "input_manifest_path": str(target / "platform-input.json"),
        "motor_state_path": str(target / "motor-state.json"),
    }


def _expected_input_files(
    evidence_dir: Path,
    *,
    expected: Mapping[str, Any],
    motor_raw: bytes,
) -> tuple[Path, Path]:
    manifest_path = evidence_dir / "platform-input.json"
    motor_path = evidence_dir / "motor-state.json"
    if not manifest_path.is_file() or not motor_path.is_file():
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform evidence is missing frozen input files")
    if manifest_path.read_bytes() != _canonical_json_bytes(expected):
        raise DigitalTwinPlatformAcceptanceError("frozen platform-input.json no longer matches exact M4/physical evidence")
    if motor_path.read_bytes() != motor_raw:
        raise DigitalTwinPlatformAcceptanceError("frozen motor-state.json no longer matches exact M4 Motor State v2")
    return manifest_path, motor_path


def validate_realization_receipt(
    receipt_path: str | os.PathLike[str],
    *,
    expected_input: Mapping[str, Any],
    input_manifest_path: str | os.PathLike[str],
) -> dict[str, Any]:
    path = Path(receipt_path).expanduser().resolve()
    value = _json(path, "digital-twin platform realization receipt")
    if set(value) != REALIZATION_FIELDS:
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform realization fields are not canonical")
    if value.get("format") != REALIZATION_FORMAT or value.get("version") != REALIZATION_VERSION:
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform realization format/version is invalid")

    for field in INPUT_FIELDS - {"format", "version"}:
        if value.get(field) != expected_input.get(field):
            raise DigitalTwinPlatformAcceptanceError(f"digital-twin platform realization no longer matches input field {field}")
    manifest_path = Path(input_manifest_path).expanduser().resolve()
    if value.get("input_manifest_sha256") != _sha256_file(manifest_path):
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform realization no longer binds exact platform input bytes")

    platform = str(expected_input["platform"])
    config = _platform(platform)
    if value.get("unity_platform") != config["unity_platform"]:
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform realization came from the wrong Unity platform")
    if platform == "android-quest-class":
        device = str(value.get("device_model") or "")
        if "quest" not in device.lower() and "oculus" not in device.lower():
            raise DigitalTwinPlatformAcceptanceError("Quest digital-twin realization does not identify a Quest/Oculus device")
    for field in ("observed_at", "unity_version", "build_guid", "device_model", "graphics_device", "renderer_name", "renderer_version"):
        if not str(value.get(field) or "").strip():
            raise DigitalTwinPlatformAcceptanceError(f"digital-twin platform realization is missing {field}")
    if not isinstance(value.get("realization_frame_count"), int) or int(value["realization_frame_count"]) < 2:
        raise DigitalTwinPlatformAcceptanceError("digital-twin platform realization did not survive two physical realization frames")
    for field in (
        "motion_realized",
        "expression_realized",
        "gesture_realized",
        "gaze_realized",
        "posture_realized",
        "speech_timing_realized",
        "source_observed_embodiment_bound",
    ):
        if value.get(field) is not True:
            raise DigitalTwinPlatformAcceptanceError(f"digital-twin platform realization did not pass {field}")
    if value.get("production_activation") is not False:
        raise DigitalTwinPlatformAcceptanceError("M5 platform realization cannot activate production")
    return value


def platform_evidence_dir(acceptance_dir: str | os.PathLike[str], platform: str) -> Path:
    config = _platform(platform)
    return Path(acceptance_dir).expanduser().resolve() / config["evidence_dir"]


def inspect_digital_twin_platform_acceptance(
    *,
    composition_authority_dir: str | os.PathLike[str],
    acceptance_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    acceptance = Path(acceptance_dir).expanduser().resolve()
    platforms: dict[str, Any] = {}
    blockers: list[str] = []

    for platform, config in PLATFORMS.items():
        evidence = platform_evidence_dir(acceptance, platform)
        try:
            expected, motor_raw = build_platform_input(
                composition_authority_dir=composition_authority_dir,
                acceptance_dir=acceptance,
                platform=platform,
            )
        except DigitalTwinPlatformAcceptanceError as exc:
            message = str(exc)
            platforms[platform] = {
                "ready": False,
                "state": "blocked",
                "evidence_dir": str(evidence),
                "message": message,
                "next_command": None,
            }
            blockers.append(f"{platform}: {message}")
            continue

        if not evidence.exists():
            command = (
                f".\\{config['command']} -AcceptanceDir '{acceptance}' "
                f"-CompositionAuthorityDir '{Path(composition_authority_dir).expanduser().resolve()}'"
            )
            platforms[platform] = {
                "ready": False,
                "state": "required",
                "evidence_dir": str(evidence),
                "message": "exact M4 composition has not been physically realized on this platform",
                "next_command": command,
            }
            blockers.append(f"{platform}: digital-twin realization evidence is required")
            continue
        if not evidence.is_dir():
            message = "digital-twin platform evidence path is not a directory"
            platforms[platform] = {
                "ready": False,
                "state": "invalid",
                "evidence_dir": str(evidence),
                "message": message,
                "next_command": None,
            }
            blockers.append(f"{platform}: {message}")
            continue

        try:
            manifest_path, _motor_path = _expected_input_files(evidence, expected=expected, motor_raw=motor_raw)
            receipt = validate_realization_receipt(
                evidence / "realization.json",
                expected_input=expected,
                input_manifest_path=manifest_path,
            )
        except (DigitalTwinPlatformAcceptanceError, OSError) as exc:
            message = str(exc)
            platforms[platform] = {
                "ready": False,
                "state": "invalid",
                "evidence_dir": str(evidence),
                "message": message,
                "next_command": None,
            }
            blockers.append(f"{platform}: {message}")
            continue

        platforms[platform] = {
            "ready": True,
            "state": "complete",
            "evidence_dir": str(evidence),
            "message": "exact M4 composition is physically realized and bound to canonical renderer acceptance",
            "next_command": None,
            "realization_sha256": _sha256_file(evidence / "realization.json"),
            "build_guid": receipt["build_guid"],
            "device_model": receipt["device_model"],
        }

    ready = all(value.get("ready") is True for value in platforms.values()) and len(platforms) == len(PLATFORMS)
    next_platform = None
    for platform in ("windows-unity-univrm", "android-quest-class"):
        if platforms.get(platform, {}).get("ready") is not True:
            next_platform = platform
            break
    return {
        "format": STATUS_FORMAT,
        "version": STATUS_VERSION,
        "m5_ready": ready,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": platforms,
        "blockers": blockers,
        "next_gate": "digital_twin_final_release" if ready else f"m5:{next_platform}",
        "message": (
            "Windows and Quest have physically realized the exact M4 composition; canonical M6 release is still required."
            if ready
            else "M5 requires exact M4 composition realization on both real WindowsPlayer and Quest-class runtimes."
        ),
    }
