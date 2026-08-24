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
    _need_sha256(session.get("readiness_sha256"), "session.readiness_sha256")
    _need_sha256(session.get("rig_setup_sha256"), "session.rig_setup_sha256")

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


def _validate_gate_a(path: Path) -> tuple[dict[str, Any], str, str, str]:
    report = _read_json(path, "Gate A acceptance report")
    if report.get("format") != "bodyrig-rig-acceptance" or report.get("version") != 1:
        raise AcceptanceStatusError("Unsupported Gate A acceptance format/version.")
    if report.get("automated_pass") is not True or report.get("production_activation") is not False:
        raise AcceptanceStatusError("Gate A is not a valid non-activating automated PASS.")
    if report.get("physical_renderer_acceptance") != "pending":
        raise AcceptanceStatusError("Gate A physical_renderer_acceptance is not pending.")
    if (report.get("physical_clone") or {}).get("mode") != "stash-sith-high-fidelity":
        raise AcceptanceStatusError("Gate A does not contain Stash/SiTH high-fidelity lineage.")
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
    return report, body_id, revision, package_hash + ":" + runtime_hash


def _validate_probe(
    path: Path,
    *,
    platform: str,
    body_id: str,
    revision: str,
    package_hash: str,
    runtime_hash: str,
) -> dict[str, Any]:
    probe = _read_json(path, "Renderer machine probe")
    if probe.get("format") != "bodyrig-renderer-probe" or probe.get("version") != 1:
        raise AcceptanceStatusError(f"Invalid renderer machine probe: {path}")
    if probe.get("platform") != platform:
        raise AcceptanceStatusError(f"Renderer machine probe platform mismatch: {path}")
    if _need_sha40(probe.get("bodyrig_revision"), "probe.bodyrig_revision") != revision:
        raise AcceptanceStatusError(f"Renderer machine probe was built from a different BodyRig revision: {path}")
    if str(probe.get("body_id") or "") != body_id:
        raise AcceptanceStatusError(f"Renderer machine probe body id mismatch: {path}")
    if _need_sha256(probe.get("package_sha256"), "probe.package_sha256") != package_hash:
        raise AcceptanceStatusError(f"Renderer machine probe package mismatch: {path}")
    if _need_sha256(probe.get("runtime_manifest_sha256"), "probe.runtime_manifest_sha256") != runtime_hash:
        raise AcceptanceStatusError(f"Renderer machine probe runtime mismatch: {path}")
    if probe.get("vrm10_loaded") is not True or probe.get("humanoid_valid") is not True or probe.get("required_bones_valid") is not True:
        raise AcceptanceStatusError(f"Renderer machine probe did not pass VRM/Humanoid/bone checks: {path}")
    build_guid = str(probe.get("build_guid") or "").strip()
    if not build_guid:
        raise AcceptanceStatusError(f"Renderer machine probe has no build GUID: {path}")
    return probe


def _validate_deformation(
    path: Path,
    *,
    platform: str,
    probe: dict[str, Any],
    revision: str,
    body_id: str,
    package_hash: str,
    runtime_hash: str,
) -> dict[str, Any]:
    deformation = _read_json(path, "Deformation probe")
    if deformation.get("format") != "bodyrig-deformation-probe" or deformation.get("version") != 1:
        raise AcceptanceStatusError(f"Invalid deformation probe: {path}")
    if deformation.get("platform") != platform:
        raise AcceptanceStatusError(f"Deformation probe platform mismatch: {path}")
    if _need_sha40(deformation.get("bodyrig_revision"), "deformation.bodyrig_revision") != revision:
        raise AcceptanceStatusError(f"Deformation probe was built from a different BodyRig revision: {path}")
    if str(deformation.get("body_id") or "") != body_id:
        raise AcceptanceStatusError(f"Deformation probe body id mismatch: {path}")
    if _need_sha256(deformation.get("package_sha256"), "deformation.package_sha256") != package_hash:
        raise AcceptanceStatusError(f"Deformation probe package mismatch: {path}")
    if _need_sha256(deformation.get("runtime_manifest_sha256"), "deformation.runtime_manifest_sha256") != runtime_hash:
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
    return deformation


def _validate_attestation(
    path: Path,
    *,
    platform: str,
    gate_a_path: Path,
    probe_path: Path,
    deformation_path: Path,
    revision: str,
    body_id: str,
    package_hash: str,
    runtime_hash: str,
) -> dict[str, Any]:
    attestation = _read_json(path, "Renderer attestation")
    if attestation.get("format") != "bodyrig-renderer-acceptance" or attestation.get("version") != 1:
        raise AcceptanceStatusError(f"Invalid renderer attestation: {path}")
    if attestation.get("platform") != platform or attestation.get("result") != "pass":
        raise AcceptanceStatusError(f"Renderer attestation is not a PASS for {platform}: {path}")
    if attestation.get("machine_probe") is not True or attestation.get("deformation_probe") is not True or attestation.get("production_activation") is not False:
        raise AcceptanceStatusError(f"Renderer attestation gate flags are invalid: {path}")
    if _need_sha40(attestation.get("bodyrig_revision"), "attestation.bodyrig_revision") != revision:
        raise AcceptanceStatusError(f"Renderer attestation revision mismatch: {path}")
    if str(attestation.get("body_id") or "") != body_id:
        raise AcceptanceStatusError(f"Renderer attestation body id mismatch: {path}")
    if _need_sha256(attestation.get("package_sha256"), "attestation.package_sha256") != package_hash:
        raise AcceptanceStatusError(f"Renderer attestation package mismatch: {path}")
    if _need_sha256(attestation.get("runtime_manifest_sha256"), "attestation.runtime_manifest_sha256") != runtime_hash:
        raise AcceptanceStatusError(f"Renderer attestation runtime mismatch: {path}")
    expected_hashes = {
        "automated_report_sha256": _sha256(gate_a_path),
        "probe_report_sha256": _sha256(probe_path),
        "deformation_report_sha256": _sha256(deformation_path),
    }
    for field, expected in expected_hashes.items():
        if _need_sha256(attestation.get(field), f"attestation.{field}") != expected:
            raise AcceptanceStatusError(f"Renderer attestation no longer binds the exact evidence file {field}: {path}")
    if attestation.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise AcceptanceStatusError(f"Renderer attestation deformation revision mismatch: {path}")
    if not str(attestation.get("quality_note") or "").strip():
        raise AcceptanceStatusError(f"Renderer attestation has no quality note: {path}")
    return attestation


def _platform_stage(
    acceptance_dir: Path,
    *,
    platform: str,
    prefix: str,
    attestation_name: str,
    gate_a_path: Path,
    body_id: str,
    revision: str,
    package_hash: str,
    runtime_hash: str,
) -> str:
    probe_path = acceptance_dir / f"{prefix}-probe.json"
    deformation_path = acceptance_dir / f"{prefix}-deformation-probe.json"
    attestation_path = acceptance_dir / attestation_name

    if deformation_path.exists() and not probe_path.exists():
        raise AcceptanceStatusError(f"{prefix} deformation evidence exists without its machine probe.")
    if attestation_path.exists() and (not probe_path.exists() or not deformation_path.exists()):
        raise AcceptanceStatusError(f"{prefix} attestation exists without complete machine/deformation evidence.")
    if not probe_path.exists():
        return "probe"
    probe = _validate_probe(
        probe_path,
        platform=platform,
        body_id=body_id,
        revision=revision,
        package_hash=package_hash,
        runtime_hash=runtime_hash,
    )
    if not deformation_path.exists():
        raise AcceptanceStatusError(f"{prefix} machine probe exists without its required deformation probe.")
    _validate_deformation(
        deformation_path,
        platform=platform,
        probe=probe,
        revision=revision,
        body_id=body_id,
        package_hash=package_hash,
        runtime_hash=runtime_hash,
    )
    if not attestation_path.exists():
        return "attestation"
    _validate_attestation(
        attestation_path,
        platform=platform,
        gate_a_path=gate_a_path,
        probe_path=probe_path,
        deformation_path=deformation_path,
        revision=revision,
        body_id=body_id,
        package_hash=package_hash,
        runtime_hash=runtime_hash,
    )
    return "complete"


def inspect_acceptance_dir(directory: Path) -> AcceptanceStatus:
    acceptance_dir = directory.expanduser().resolve()
    if not acceptance_dir.is_dir():
        raise AcceptanceStatusError(f"Acceptance directory not found: {acceptance_dir}")
    gate_a_path = acceptance_dir / "bodyrig-acceptance.json"
    if not gate_a_path.is_file():
        raise AcceptanceStatusError(f"Gate A acceptance report not found: {gate_a_path}")
    _, body_id, revision, hashes = _validate_gate_a(gate_a_path)
    package_hash, runtime_hash = hashes.split(":", 1)

    release_path = acceptance_dir / "bodyrig-release-acceptance.json"
    windows_stage = _platform_stage(
        acceptance_dir,
        platform="windows-unity-univrm",
        prefix="windows",
        attestation_name="bodyrig-renderer-acceptance-windows.json",
        gate_a_path=gate_a_path,
        body_id=body_id,
        revision=revision,
        package_hash=package_hash,
        runtime_hash=runtime_hash,
    )
    if windows_stage == "probe":
        return AcceptanceStatus(
            state="ready", gate="windows-probe", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
            message="Gate A PASS exists; next physical gate is the built WindowsPlayer machine + deformation probe.",
            next_command=f".\\run-windows-renderer-probe.ps1 -AcceptanceDir {_quote(acceptance_dir)}",
        )
    if windows_stage == "attestation":
        return AcceptanceStatus(
            state="human-review", gate="windows-attestation", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
            message="Windows machine/deformation evidence is coherent. Human visual review and attestation are still required.",
            next_command=(
                ".\\record-renderer-acceptance.ps1 "
                f"-AcceptanceReport {_quote(gate_a_path)} "
                f"-RuntimeManifest {_quote(acceptance_dir / 'runtime' / 'runtime-manifest.json')} "
                f"-ProbeReport {_quote(acceptance_dir / 'windows-probe.json')} "
                f"-DeformationReport {_quote(acceptance_dir / 'windows-deformation-probe.json')} "
                '-Platform "windows-unity-univrm" -Pass -RendererName "BodyRig Reference Renderer" '
                '-RendererVersion "<exact version>" -QualityNote "<your physical review>"'
            ),
        )

    quest_stage = _platform_stage(
        acceptance_dir,
        platform="android-quest-class",
        prefix="quest",
        attestation_name="bodyrig-renderer-acceptance-quest.json",
        gate_a_path=gate_a_path,
        body_id=body_id,
        revision=revision,
        package_hash=package_hash,
        runtime_hash=runtime_hash,
    )
    if quest_stage == "probe":
        return AcceptanceStatus(
            state="ready", gate="quest-probe", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
            message="Windows physical review is accepted; next gate is the same runtime on Quest-class hardware.",
            next_command=f".\\run-quest-renderer-probe.ps1 -AcceptanceDir {_quote(acceptance_dir)}",
        )
    if quest_stage == "attestation":
        return AcceptanceStatus(
            state="human-review", gate="quest-attestation", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
            message="Quest machine/deformation evidence is coherent. Human headset review and attestation are still required.",
            next_command=(
                ".\\record-renderer-acceptance.ps1 "
                f"-AcceptanceReport {_quote(gate_a_path)} "
                f"-RuntimeManifest {_quote(acceptance_dir / 'runtime' / 'runtime-manifest.json')} "
                f"-ProbeReport {_quote(acceptance_dir / 'quest-probe.json')} "
                f"-DeformationReport {_quote(acceptance_dir / 'quest-deformation-probe.json')} "
                '-Platform "android-quest-class" -Pass -RendererName "BodyRig Reference Renderer" '
                '-RendererVersion "<exact version>" -QualityNote "<your physical headset review>"'
            ),
        )

    if release_path.exists():
        release = _read_json(release_path, "Final release acceptance")
        if release.get("format") != "bodyrig-release-acceptance" or release.get("version") != 1:
            raise AcceptanceStatusError("Final release acceptance format/version is invalid.")
        if release.get("release_gate_pass") is not True or release.get("production_activation") is not True:
            raise AcceptanceStatusError("Final release artifact exists but is not an activating PASS.")
        if _need_sha40(release.get("bodyrig_revision"), "release.bodyrig_revision") != revision:
            raise AcceptanceStatusError("Final release acceptance revision no longer matches Gate A.")
        renderers = release.get("renderer_acceptance") or {}
        for key, attestation_name in (
            ("windows_unity_univrm", "bodyrig-renderer-acceptance-windows.json"),
            ("android_quest_class", "bodyrig-renderer-acceptance-quest.json"),
        ):
            summary = renderers.get(key) or {}
            if _need_sha40(summary.get("renderer_bodyrig_revision"), f"release.{key}.renderer_bodyrig_revision") != revision:
                raise AcceptanceStatusError(f"Final release {key} renderer revision mismatch.")
            if _need_sha256(summary.get("report_sha256"), f"release.{key}.report_sha256") != _sha256(acceptance_dir / attestation_name):
                raise AcceptanceStatusError(f"Final release {key} attestation hash no longer matches evidence.")
        return AcceptanceStatus(
            state="complete", gate="release", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
            message="Final BodyRig release acceptance is a production-activating PASS for the exact physical evidence chain.", next_command=None,
        )

    return AcceptanceStatus(
        state="ready", gate="release", acceptance_dir=str(acceptance_dir), body_id=body_id, bodyrig_revision=revision,
        message="Windows and Quest physical attestations are coherent; final release gate is the next step.",
        next_command=(
            ".\\complete-acceptance.ps1 "
            f"-AcceptanceReport {_quote(gate_a_path)} "
            f"-WindowsRendererReport {_quote(acceptance_dir / 'bodyrig-renderer-acceptance-windows.json')} "
            f"-WindowsProbeReport {_quote(acceptance_dir / 'windows-probe.json')} "
            f"-WindowsDeformationReport {_quote(acceptance_dir / 'windows-deformation-probe.json')} "
            f"-QuestRendererReport {_quote(acceptance_dir / 'bodyrig-renderer-acceptance-quest.json')} "
            f"-QuestProbeReport {_quote(acceptance_dir / 'quest-probe.json')} "
            f"-QuestDeformationReport {_quote(acceptance_dir / 'quest-deformation-probe.json')}"
        ),
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
