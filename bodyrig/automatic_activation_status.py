from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, _read_json, _validate_gate_a, inspect_acceptance_dir
from .renderer_human_rejection import any_rejection_exists
from .automatic_release_gate import (
    AutomaticReleaseGateError,
    _assert_git_authority,
    _runtime_identity,
    _validate_deformation,
    _validate_probe,
    _validate_provenance,
    _validate_quality,
    _validate_skin_qa,
    validate_and_build,
)


@dataclass(frozen=True)
class AutomaticActivationStatus:
    state: str
    stage: str
    acceptance_dir: str
    release_output: str
    body_id: str
    bodyrig_revision: str
    message: str


def _renderer_contract(repo_root: Path) -> dict[str, Any]:
    contract = _read_json(repo_root / "reference-renderer" / "renderer-contract.json", "Reference renderer contract")
    if contract.get("format") != "bodyrig-reference-renderer-contract" or contract.get("version") != 1:
        raise AutomaticReleaseGateError("reference renderer contract format/version mismatch")
    if contract.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise AutomaticReleaseGateError("reference renderer deformation sequence mismatch")
    return contract


def _validate_platform(
    acceptance_dir: Path,
    *,
    prefix: str,
    platform: str,
    unity_platform: str,
    gate: Any,
    runtime_hash: str,
    avatar_hash: str,
    bodyprint_hash: str,
    contract: dict[str, Any],
) -> str:
    evidence = acceptance_dir / f"{prefix}-evidence"
    probe_path = evidence / f"{prefix}-probe.json"
    deformation_path = evidence / f"{prefix}-deformation-probe.json"
    quality_path = evidence / f"{prefix}-deformation-quality.json"
    paths = (probe_path, deformation_path, quality_path)
    present = tuple(path.is_file() and not path.is_symlink() for path in paths)
    any_path = evidence.exists() or any(path.exists() for path in paths)

    if not any_path:
        return "pending"
    if evidence.is_symlink() or not evidence.is_dir():
        raise AutomaticReleaseGateError(f"{prefix} automatic evidence path is not a canonical directory: {evidence}")
    for path in paths:
        if path.is_symlink():
            raise AutomaticReleaseGateError(f"{prefix} automatic evidence must not be symlinked: {path}")

    probe_present, deformation_present, quality_present = present
    if probe_present != deformation_present:
        raise AutomaticReleaseGateError(
            f"{prefix} automatic evidence is incomplete: probe/deformation must appear as one committed pair"
        )
    if not probe_present:
        raise AutomaticReleaseGateError(
            f"{prefix} automatic evidence directory exists without its committed probe/deformation pair"
        )

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
    deformation = _validate_deformation(
        deformation_path,
        platform=platform,
        revision=gate.revision,
        probe=probe,
    )
    if not quality_present:
        if prefix == "quest":
            return "quality-pending"
        raise AutomaticReleaseGateError(
            "windows automatic probe/deformation exists without its quality receipt; "
            "the transactional Windows proof is incomplete and cannot be reused automatically"
        )
    _validate_quality(
        quality_path,
        platform=platform,
        revision=gate.revision,
        probe=probe,
        deformation=deformation,
    )
    return "complete"


def _validate_release_receipt(
    release_output: Path,
    *,
    acceptance_dir: Path,
    repo_root: Path,
) -> None:
    if release_output.is_symlink():
        raise AutomaticReleaseGateError(f"automatic release receipt must not be a symlink: {release_output}")
    persisted = _read_json(release_output, "Automatic release receipt")
    if persisted.get("format") != "bodyrig-release-acceptance" or persisted.get("version") != 2:
        raise AutomaticReleaseGateError("existing release receipt is not automatic release acceptance v2")
    completed_at = str(persisted.get("completed_at") or "").strip()
    if not completed_at:
        raise AutomaticReleaseGateError("automatic release receipt has no completed_at timestamp")
    try:
        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomaticReleaseGateError("automatic release receipt completed_at is invalid") from exc
    if parsed.tzinfo is None:
        raise AutomaticReleaseGateError("automatic release receipt completed_at must be timezone-aware")

    expected = validate_and_build(acceptance_dir, repo_root, require_git_state=False)
    expected["completed_at"] = completed_at
    if persisted != expected:
        raise AutomaticReleaseGateError(
            "automatic release receipt no longer exactly matches the current hash-bound Gate A/Windows/Quest evidence"
        )


def inspect_automatic_activation(
    acceptance_dir: Path,
    repo_root: Path,
    *,
    release_output: Path | None = None,
    require_git_state: bool = True,
) -> AutomaticActivationStatus:
    acceptance_dir = acceptance_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    if not acceptance_dir.is_dir():
        raise AutomaticReleaseGateError(f"acceptance directory not found: {acceptance_dir}")
    if not repo_root.is_dir():
        raise AutomaticReleaseGateError(f"BodyRig repo root not found: {repo_root}")
    release_output = (release_output or (acceptance_dir / "bodyrig-release-acceptance.json")).expanduser().resolve()

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
            f"renderer human rejection blocks automatic production activation: {rejection_status.message}"
        )
    if require_git_state:
        _assert_git_authority(repo_root, gate.revision)

    avatar_hash, bodyprint_hash = _runtime_identity(acceptance_dir, gate)
    _validate_provenance(acceptance_dir, gate, avatar_hash, bodyprint_hash)
    _validate_skin_qa(acceptance_dir, gate_report, gate, avatar_hash)
    contract = _renderer_contract(repo_root)

    for attestation in (
        acceptance_dir / "bodyrig-renderer-acceptance-windows.json",
        acceptance_dir / "bodyrig-renderer-acceptance-quest.json",
    ):
        if attestation.exists():
            raise AutomaticReleaseGateError(
                "automatic production activation refuses to mix machine-only automatic evidence with legacy human attestation evidence"
            )

    windows = _validate_platform(
        acceptance_dir,
        prefix="windows",
        platform="windows-unity-univrm",
        unity_platform="WindowsPlayer",
        gate=gate,
        runtime_hash=gate.runtime_hash,
        avatar_hash=avatar_hash,
        bodyprint_hash=bodyprint_hash,
        contract=contract,
    )
    quest = _validate_platform(
        acceptance_dir,
        prefix="quest",
        platform="android-quest-class",
        unity_platform="Android",
        gate=gate,
        runtime_hash=gate.runtime_hash,
        avatar_hash=avatar_hash,
        bodyprint_hash=bodyprint_hash,
        contract=contract,
    )

    release_exists = release_output.exists()
    if windows == "pending":
        if quest != "pending" or release_exists:
            raise AutomaticReleaseGateError("downstream automatic evidence exists without a valid Windows automatic PASS")
        return AutomaticActivationStatus(
            "ready", "windows", str(acceptance_dir), str(release_output), gate.body_id, gate.revision,
            "Gate A is valid and automatic production activation must start with Windows machine-quality proof.",
        )
    if windows != "complete":
        raise AutomaticReleaseGateError(f"unsupported Windows automatic evidence state: {windows}")

    if quest == "pending":
        if release_exists:
            raise AutomaticReleaseGateError("automatic release receipt exists without a valid Quest automatic PASS")
        return AutomaticActivationStatus(
            "ready", "quest", str(acceptance_dir), str(release_output), gate.body_id, gate.revision,
            "Windows automatic PASS is reusable; continue directly with Quest automatic proof.",
        )
    if quest == "quality-pending":
        if release_exists:
            raise AutomaticReleaseGateError("automatic release receipt exists while Quest quality evidence is incomplete")
        return AutomaticActivationStatus(
            "ready", "quest-quality", str(acceptance_dir), str(release_output), gate.body_id, gate.revision,
            "Quest probe/deformation PASS is reusable; recover the matching Quest quality receipt without rebuilding Windows.",
        )
    if quest != "complete":
        raise AutomaticReleaseGateError(f"unsupported Quest automatic evidence state: {quest}")

    if release_exists:
        _validate_release_receipt(
            release_output,
            acceptance_dir=acceptance_dir,
            repo_root=repo_root,
        )
        return AutomaticActivationStatus(
            "complete", "complete", str(acceptance_dir), str(release_output), gate.body_id, gate.revision,
            "Automatic Windows + Quest evidence and the final production-activating release receipt are valid.",
        )

    return AutomaticActivationStatus(
        "ready", "release", str(acceptance_dir), str(release_output), gate.body_id, gate.revision,
        "Windows and Quest automatic PASS evidence is reusable; only the final automatic release gate remains.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only BodyRig automatic production activation resume status")
    parser.add_argument("--acceptance-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--release-output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = inspect_automatic_activation(
            args.acceptance_dir,
            args.repo_root,
            release_output=args.release_output,
            require_git_state=True,
        )
    except (AutomaticReleaseGateError, AcceptanceStatusError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BODYRIG AUTOMATIC ACTIVATION STATUS: ERROR | {exc}")
        return 1

    if args.json:
        print(json.dumps(asdict(status), ensure_ascii=False, sort_keys=True))
    else:
        print(f"BODYRIG AUTOMATIC ACTIVATION STATUS: {status.state.upper()} | {status.stage}")
        print(status.message)
        print(f"Revision: {status.bodyrig_revision}")
        print(f"Acceptance: {status.acceptance_dir}")
        print(f"Release: {status.release_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
