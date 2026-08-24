from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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


class AcceptanceStatusError(RuntimeError):
    pass


@dataclass(frozen=True)
class AcceptanceStatus:
    state: str
    gate: str
    acceptance_dir: str | None
    body_id: str | None
    bodyrig_revision: str | None
    message: str
    next_command: str | None


@dataclass(frozen=True)
class GateAInfo:
    path: Path
    body_id: str
    revision: str
    package_hash: str
    runtime_hash: str


@dataclass(frozen=True)
class PlatformPaths:
    probe: Path
    deformation: Path
    attestation: Path
    layout: str


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AcceptanceStatusError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceStatusError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AcceptanceStatusError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AcceptanceStatusError(f"Could not hash evidence file: {path}") from exc
    return digest.hexdigest()


def _need_sha40(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if not SHA40.fullmatch(text):
        raise AcceptanceStatusError(f"{label} is not a canonical 40-character Git SHA.")
    return text


def _need_sha256(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if not SHA256.fullmatch(text):
        raise AcceptanceStatusError(f"{label} is not a canonical SHA-256.")
    return text


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise AcceptanceStatusError(f"{label} not found: {path}")
    if _sha256(path) != expected:
        raise AcceptanceStatusError(f"{label} bytes no longer match Gate A: {path}")


def _quote(path: Path) -> str:
    return f'"{path}"'


def _session_status(session_path: Path) -> AcceptanceStatus:
    session_path = session_path.expanduser().resolve()
    session = _read_json(session_path, "Physical clone session")
    if session.get("format") != "bodyrig-physical-clone-session" or session.get("version") != 1:
        raise AcceptanceStatusError("Unsupported physical clone session format/version.")
    body_id = str(session.get("body_id") or "") or None
    revision = _need_sha40(session.get("bodyrig_revision"), "session.bodyrig_revision")
    state = str(session.get("status") or "")
    stage = str(session.get("stage") or "")
    if state != "pass" or stage != "complete":
        return AcceptanceStatus(
            state="blocked" if state == "fail" else "incomplete",
            gate="physical-clone",
            acceptance_dir=None,
            body_id=body_id,
            bodyrig_revision=revision,
            message=f"Physical clone session is {state or 'unknown'}/{stage or 'unknown'}; Gate A cannot start.",
            next_command=None,
        )
    if session.get("bodyrig_checkout_clean") is not True:
        raise AcceptanceStatusError("Completed physical clone session was not bound to a clean checkout.")
    readiness_hash = _need_sha256(session.get("readiness_sha256"), "session.readiness_sha256")
    _need_sha256(session.get("rig_setup_sha256"), "session.rig_setup_sha256")
    _require_hash(session_path.with_suffix(".readiness.json"), readiness_hash, "Physical clone readiness evidence")
    clone_output = str(session.get("clone_output") or "")
    if not clone_output:
        raise AcceptanceStatusError("Completed physical clone session has no clone_output.")
    acceptance_dir = Path(clone_output).expanduser().resolve() / "acceptance"
    if not acceptance_dir.exists():
        return AcceptanceStatus(
            state="ready",
            gate="gate-a",
            acceptance_dir=str(acceptance_dir),
            body_id=body_id,
            bodyrig_revision=revision,
            message="Physical clone PASS exists; promote the exact clone bytes into high-fidelity Gate A.",
            next_command=f".\\accept-physical-clone.ps1 -SessionReport {_quote(session_path)}",
        )
    return inspect_acceptance_dir(acceptance_dir)


def _validate_gate_a(path: Path) -> GateAInfo:
    report = _read_json(path, "Gate A acceptance report")
    if report.get("format") != "bodyrig-rig-acceptance" or report.get("version") != 1:
        raise AcceptanceStatusError("Unsupported Gate A acceptance format/version.")
    if report.get("automated_pass") is not True or report.get("production_activation") is not False:
        raise AcceptanceStatusError("Gate A is not a valid non-activating automated PASS.")
    if report.get("physical_renderer_acceptance") != "pending":
        raise AcceptanceStatusError("Gate A physical_renderer_acceptance is not pending.")

    physical_clone = report.get("physical_clone") or {}
    if physical_clone.get("mode") != "stash-sith-high-fidelity":
        raise AcceptanceStatusError("Gate A does not contain Stash/SiTH high-fidelity lineage.")
    session_hash = _need_sha256(physical_clone.get("session_sha256"), "Gate A physical clone session SHA-256")
    readiness_hash = _need_sha256(physical_clone.get("readiness_sha256"), "Gate A readiness SHA-256")

    skin_qa = report.get("skin_qa") or {}
    skin_qa_hash = _need_sha256(skin_qa.get("report_sha256"), "Gate A skin QA SHA-256")
    if skin_qa.get("structural_pass") is not True or skin_qa.get("manual_review_required") is not True:
        raise AcceptanceStatusError("Gate A skin QA state is invalid.")

    package = report.get("package") or {}
    runtime = report.get("runtime") or {}
    if package.get("placeholder_avatar") is not False:
        raise AcceptanceStatusError("Gate A package is a placeholder avatar.")
    body_id = str(package.get("body_id") or "")
    if not body_id:
        raise AcceptanceStatusError("Gate A has no body id.")
    revision = _need_sha40(report.get("bodyrig_revision"), "Gate A bodyrig_revision")
    package_hash = _need_sha256(package.get("package_sha256"), "Gate A package SHA-256")
    runtime_hash = _need_sha256(runtime.get("manifest_sha256"), "Gate A runtime manifest SHA-256")

    directory = path.parent
    _require_hash(directory / f"{body_id}.mrbody", package_hash, "Accepted .mrbody")
    _require_hash(directory / "runtime" / "runtime-manifest.json", runtime_hash, "Materialized runtime manifest")
    _require_hash(directory / "bodyrig-physical-clone-session.json", session_hash, "Physical clone session evidence")
    _require_hash(directory / "bodyrig-rig-readiness.json", readiness_hash, "Physical clone readiness evidence")
    _require_hash(directory / "bodyrig-skin-qa.json", skin_qa_hash, "Anatomical skin QA evidence")
    return GateAInfo(path, body_id, revision, package_hash, runtime_hash)


def _platform_paths(acceptance_dir: Path, prefix: str, attestation_name: str) -> PlatformPaths:
    dedicated = acceptance_dir / f"{prefix}-evidence"
    dedicated_probe = dedicated / f"{prefix}-probe.json"
    dedicated_deformation = dedicated / f"{prefix}-deformation-probe.json"
    legacy_probe = acceptance_dir / f"{prefix}-probe.json"
    legacy_deformation = acceptance_dir / f"{prefix}-deformation-probe.json"
    attestation = acceptance_dir / attestation_name

    dedicated_any = dedicated.exists()
    legacy_any = legacy_probe.exists() or legacy_deformation.exists()
    if dedicated_any and legacy_any:
        raise AcceptanceStatusError(f"Ambiguous {prefix} evidence: both dedicated and legacy layouts exist.")
    if dedicated_any:
        if not dedicated.is_dir():
            raise AcceptanceStatusError(f"{prefix} evidence path is not a directory: {dedicated}")
        return PlatformPaths(dedicated_probe, dedicated_deformation, attestation, "dedicated")
    if legacy_any:
        return PlatformPaths(legacy_probe, legacy_deformation, attestation, "legacy")
    return PlatformPaths(dedicated_probe, dedicated_deformation, attestation, "pending")


def _validate_probe(path: Path, *, platform: str, gate: GateAInfo) -> dict[str, Any]:
    probe = _read_json(path, "Renderer machine probe")
    if probe.get("format") != "bodyrig-renderer-probe" or probe.get("version") != 1 or probe.get("platform") != platform:
        raise AcceptanceStatusError(f"Invalid renderer machine probe: {path}")
    if _need_sha40(probe.get("bodyrig_revision"), "probe.bodyrig_revision") != gate.revision:
        raise AcceptanceStatusError(f"Renderer machine probe was built from a different BodyRig revision: {path}")
    if str(probe.get("body_id") or "") != gate.body_id:
        raise AcceptanceStatusError(f"Renderer machine probe body id mismatch: {path}")
    if _need_sha256(probe.get("package_sha256"), "probe.package_sha256") != gate.package_hash:
        raise AcceptanceStatusError(f"Renderer machine probe package mismatch: {path}")
    if _need_sha256(probe.get("runtime_manifest_sha256"), "probe.runtime_manifest_sha256") != gate.runtime_hash:
        raise AcceptanceStatusError(f"Renderer machine probe runtime mismatch: {path}")
    if probe.get("vrm10_loaded") is not True or probe.get("humanoid_valid") is not True or probe.get("required_bones_valid") is not True:
        raise AcceptanceStatusError(f"Renderer machine probe did not pass VRM/Humanoid/bone checks: {path}")
    if not str(probe.get("build_guid") or "").strip():
        raise AcceptanceStatusError(f"Renderer machine probe has no build GUID: {path}")
    return probe


def _validate_deformation(path: Path, *, platform: str, probe: dict[str, Any], gate: GateAInfo) -> None:
    deformation = _read_json(path, "Deformation probe")
    if deformation.get("format") != "bodyrig-deformation-probe" or deformation.get("version") != 1 or deformation.get("platform") != platform:
        raise AcceptanceStatusError(f"Invalid deformation probe: {path}")
    if _need_sha40(deformation.get("bodyrig_revision"), "deformation.bodyrig_revision") != gate.revision:
        raise AcceptanceStatusError(f"Deformation probe was built from a different BodyRig revision: {path}")
    if str(deformation.get("body_id") or "") != gate.body_id:
        raise AcceptanceStatusError(f"Deformation probe body id mismatch: {path}")
    if _need_sha256(deformation.get("package_sha256"), "deformation.package_sha256") != gate.package_hash:
        raise AcceptanceStatusError(f"Deformation probe package mismatch: {path}")
    if _need_sha256(deformation.get("runtime_manifest_sha256"), "deformation.runtime_manifest_sha256") != gate.runtime_hash:
        raise AcceptanceStatusError(f"Deformation probe runtime mismatch: {path}")
    if deformation.get("sequence_revision") != "humanoid-muscle-sweep-v1" or deformation.get("pose_count") != 6:
        raise AcceptanceStatusError(f"Deformation probe sequence mismatch: {path}")
    pose_ids = tuple(str(item.get("id") or "") for item in (deformation.get("poses") or []) if isinstance(item, dict))
    if pose_ids != POSES:
        raise AcceptanceStatusError(f"Deformation probe pose order mismatch: {path}")
    for field in ("required_muscles_resolved", "restored_neutral", "complete", "manual_review_required"):
        if deformation.get(field) is not True:
            raise AcceptanceStatusError(f"Deformation probe field {field} is not true: {path}")
    for field in ("bodyrig_revision", "build_guid", "unity_platform", "unity_version", "device_model"):
        if str(deformation.get(field) or "") != str(probe.get(field) or ""):
            raise AcceptanceStatusError(f"Deformation probe does not match machine probe field {field}: {path}")


def _validate_attestation(path: Path, *, platform: str, gate: GateAInfo, paths: PlatformPaths) -> None:
    attestation = _read_json(path, "Renderer attestation")
    if attestation.get("format") != "bodyrig-renderer-acceptance" or attestation.get("version") != 1:
        raise AcceptanceStatusError(f"Invalid renderer attestation: {path}")
    if attestation.get("platform") != platform or attestation.get("result") != "pass":
        raise AcceptanceStatusError(f"Renderer attestation is not a PASS for {platform}: {path}")
    if attestation.get("machine_probe") is not True or attestation.get("deformation_probe") is not True or attestation.get("production_activation") is not False:
        raise AcceptanceStatusError(f"Renderer attestation gate flags are invalid: {path}")
    if _need_sha40(attestation.get("bodyrig_revision"), "attestation.bodyrig_revision") != gate.revision:
        raise AcceptanceStatusError(f"Renderer attestation revision mismatch: {path}")
    if str(attestation.get("body_id") or "") != gate.body_id:
        raise AcceptanceStatusError(f"Renderer attestation body id mismatch: {path}")
    if _need_sha256(attestation.get("package_sha256"), "attestation.package_sha256") != gate.package_hash:
        raise AcceptanceStatusError(f"Renderer attestation package mismatch: {path}")
    if _need_sha256(attestation.get("runtime_manifest_sha256"), "attestation.runtime_manifest_sha256") != gate.runtime_hash:
        raise AcceptanceStatusError(f"Renderer attestation runtime mismatch: {path}")
    for field, expected in {
        "automated_report_sha256": _sha256(gate.path),
        "probe_report_sha256": _sha256(paths.probe),
        "deformation_report_sha256": _sha256(paths.deformation),
    }.items():
        if _need_sha256(attestation.get(field), f"attestation.{field}") != expected:
            raise AcceptanceStatusError(f"Renderer attestation no longer binds the exact evidence file {field}: {path}")
    if attestation.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise AcceptanceStatusError(f"Renderer attestation deformation revision mismatch: {path}")
    if not str(attestation.get("quality_note") or "").strip():
        raise AcceptanceStatusError(f"Renderer attestation has no quality note: {path}")


def _platform_stage(acceptance_dir: Path, *, platform: str, prefix: str, attestation_name: str, gate: GateAInfo) -> tuple[str, PlatformPaths]:
    paths = _platform_paths(acceptance_dir, prefix, attestation_name)
    probe_exists = paths.probe.is_file()
    deformation_exists = paths.deformation.is_file()
    if paths.layout == "dedicated" and not probe_exists and not deformation_exists:
        raise AcceptanceStatusError(f"{prefix} canonical evidence directory exists without its committed machine/deformation pair.")
    if probe_exists != deformation_exists:
        raise AcceptanceStatusError(f"{prefix} canonical evidence is incomplete: machine/deformation must appear as one pair.")
    if paths.attestation.exists() and not (probe_exists and deformation_exists):
        raise AcceptanceStatusError(f"{prefix} attestation exists without complete machine/deformation evidence.")
    if not probe_exists:
        return "probe", paths
    probe = _validate_probe(paths.probe, platform=platform, gate=gate)
    _validate_deformation(paths.deformation, platform=platform, probe=probe, gate=gate)
    if not paths.attestation.exists():
        return "attestation", paths
    _validate_attestation(paths.attestation, platform=platform, gate=gate, paths=paths)
    return "complete", paths


def inspect_acceptance_dir(directory: Path) -> AcceptanceStatus:
    acceptance_dir = directory.expanduser().resolve()
    if not acceptance_dir.is_dir():
        raise AcceptanceStatusError(f"Acceptance directory not found: {acceptance_dir}")
    gate_a_path = acceptance_dir / "bodyrig-acceptance.json"
    gate = _validate_gate_a(gate_a_path)

    windows_stage, windows = _platform_stage(
        acceptance_dir, platform="windows-unity-univrm", prefix="windows",
        attestation_name="bodyrig-renderer-acceptance-windows.json", gate=gate,
    )
    if windows_stage == "probe":
        return AcceptanceStatus(
            "ready", "windows-probe", str(acceptance_dir), gate.body_id, gate.revision,
            "Gate A PASS exists; next physical gate is the built WindowsPlayer machine + deformation probe.",
            f".\\run-windows-renderer-probe.ps1 -AcceptanceDir {_quote(acceptance_dir)}",
        )
    if windows_stage == "attestation":
        return AcceptanceStatus(
            "human-review", "windows-attestation", str(acceptance_dir), gate.body_id, gate.revision,
            "Windows machine/deformation evidence is coherent. Human visual review and attestation are still required.",
            ".\\record-renderer-acceptance.ps1 "
            f"-AcceptanceReport {_quote(gate.path)} -RuntimeManifest {_quote(acceptance_dir / 'runtime' / 'runtime-manifest.json')} "
            f"-ProbeReport {_quote(windows.probe)} -DeformationReport {_quote(windows.deformation)} "
            '-Platform "windows-unity-univrm" -Pass -RendererName "BodyRig Reference Renderer" '
            '-RendererVersion "<exact version>" -QualityNote "<your physical review>"',
        )

    quest_stage, quest = _platform_stage(
        acceptance_dir, platform="android-quest-class", prefix="quest",
        attestation_name="bodyrig-renderer-acceptance-quest.json", gate=gate,
    )
    if quest_stage == "probe":
        return AcceptanceStatus(
            "ready", "quest-probe", str(acceptance_dir), gate.body_id, gate.revision,
            "Windows physical review is accepted; next gate is the same runtime on Quest-class hardware.",
            f".\\run-quest-renderer-probe.ps1 -AcceptanceDir {_quote(acceptance_dir)}",
        )
    if quest_stage == "attestation":
        return AcceptanceStatus(
            "human-review", "quest-attestation", str(acceptance_dir), gate.body_id, gate.revision,
            "Quest machine/deformation evidence is coherent. Human headset review and attestation are still required.",
            ".\\record-renderer-acceptance.ps1 "
            f"-AcceptanceReport {_quote(gate.path)} -RuntimeManifest {_quote(acceptance_dir / 'runtime' / 'runtime-manifest.json')} "
            f"-ProbeReport {_quote(quest.probe)} -DeformationReport {_quote(quest.deformation)} "
            '-Platform "android-quest-class" -Pass -RendererName "BodyRig Reference Renderer" '
            '-RendererVersion "<exact version>" -QualityNote "<your physical headset review>"',
        )

    release_path = acceptance_dir / "bodyrig-release-acceptance.json"
    if release_path.exists():
        release = _read_json(release_path, "Final release acceptance")
        if release.get("format") != "bodyrig-release-acceptance" or release.get("version") != 1:
            raise AcceptanceStatusError("Final release acceptance format/version is invalid.")
        if release.get("release_gate_pass") is not True or release.get("production_activation") is not True:
            raise AcceptanceStatusError("Final release artifact exists but is not an activating PASS.")
        if _need_sha40(release.get("bodyrig_revision"), "release.bodyrig_revision") != gate.revision:
            raise AcceptanceStatusError("Final release acceptance revision no longer matches Gate A.")
        renderers = release.get("renderer_acceptance") or {}
        for key, paths in (("windows_unity_univrm", windows), ("android_quest_class", quest)):
            summary = renderers.get(key) or {}
            if _need_sha40(summary.get("renderer_bodyrig_revision"), f"release.{key}.renderer_bodyrig_revision") != gate.revision:
                raise AcceptanceStatusError(f"Final release {key} renderer revision mismatch.")
            if _need_sha256(summary.get("report_sha256"), f"release.{key}.report_sha256") != _sha256(paths.attestation):
                raise AcceptanceStatusError(f"Final release {key} attestation hash no longer matches evidence.")
        return AcceptanceStatus(
            "complete", "release", str(acceptance_dir), gate.body_id, gate.revision,
            "Final BodyRig release acceptance is a production-activating PASS for the exact physical evidence chain.", None,
        )

    return AcceptanceStatus(
        "ready", "release", str(acceptance_dir), gate.body_id, gate.revision,
        "Windows and Quest physical attestations are coherent; final release gate is the next step.",
        ".\\complete-acceptance.ps1 "
        f"-AcceptanceReport {_quote(gate.path)} "
        f"-WindowsRendererReport {_quote(windows.attestation)} -WindowsProbeReport {_quote(windows.probe)} -WindowsDeformationReport {_quote(windows.deformation)} "
        f"-QuestRendererReport {_quote(quest.attestation)} -QuestProbeReport {_quote(quest.probe)} -QuestDeformationReport {_quote(quest.deformation)}",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only BodyRig physical acceptance status checker")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--session-report", type=Path, help="bodyrig-physical-clone-session JSON")
    inputs.add_argument("--acceptance-dir", type=Path, help="Gate A acceptance directory")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable status JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = _session_status(args.session_report) if args.session_report else inspect_acceptance_dir(args.acceptance_dir)
    except AcceptanceStatusError as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig acceptance status: ERROR | {exc}")
        return 2
    if args.json:
        print(json.dumps(asdict(status), ensure_ascii=False, sort_keys=True))
    else:
        print(f"BodyRig acceptance status: {status.state.upper()} | {status.gate}")
        print(status.message)
        if status.body_id:
            print(f"Body: {status.body_id}")
        if status.bodyrig_revision:
            print(f"Revision: {status.bodyrig_revision}")
        if status.acceptance_dir:
            print(f"Acceptance: {status.acceptance_dir}")
        if status.next_command:
            print("Next command:")
            print(status.next_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
