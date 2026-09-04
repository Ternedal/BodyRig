from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .external_fitter_cli import validate_external_fitter_config
from .identity import bind_visual_identity_to_proof
from .package import validate_package
from .physical_session import validate_session
from .portable_identity import bind_portable_identity_to_evidence, load_portable_identity
from .proof import load_recovery_proof, read_canonical_json

FORMAT = "bodyrig-interrupted-fit-recovery-plan"
VERSION = 1
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class InterruptedFitRecoveryError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise InterruptedFitRecoveryError(f"required recovery artifact not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise InterruptedFitRecoveryError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InterruptedFitRecoveryError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise InterruptedFitRecoveryError(f"{label} must be a JSON object")
    return value


def build_recovery_plan(
    *,
    failed_session_path: str | os.PathLike[str],
    stash_clone_output: str | os.PathLike[str],
    identity_workspace: str | os.PathLike[str],
    current_revision: str,
) -> dict[str, Any]:
    if not isinstance(current_revision, str) or not GIT_RE.fullmatch(current_revision):
        raise InterruptedFitRecoveryError("current_revision must be a lowercase Git SHA")

    failed_path = Path(failed_session_path).expanduser().resolve()
    try:
        failed = validate_session(_read_json(failed_path, label="failed physical session"))
    except ValueError as exc:
        raise InterruptedFitRecoveryError(str(exc)) from exc
    if failed["status"] != "fail" or failed["stage"] != "clone":
        raise InterruptedFitRecoveryError("only a physical session that failed in clone stage can be resumed")
    if failed["bodyrig_revision"] != current_revision:
        raise InterruptedFitRecoveryError("failed physical session belongs to a different BodyRig revision")
    if failed["bodyrig_checkout_clean"] is not True:
        raise InterruptedFitRecoveryError("failed physical session was not bound to a clean checkout")
    if failed["readiness_sha256"] is None:
        raise InterruptedFitRecoveryError("failed clone session is missing readiness evidence binding")

    outer = Path(stash_clone_output).expanduser().resolve()
    if not outer.is_dir():
        raise InterruptedFitRecoveryError(f"Stash clone output not found: {outer}")
    clone = outer / "clone"
    if not clone.is_dir():
        raise InterruptedFitRecoveryError("interrupted Stash clone is missing the nested clone directory")

    workspace = Path(identity_workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise InterruptedFitRecoveryError(f"private identity workspace not found: {workspace}")
    reconstruction = workspace / "sith-input-v1" / "reconstruction.json"
    if not reconstruction.is_file():
        raise InterruptedFitRecoveryError(
            "private identity workspace has no completed SiTH reconstruction authority; expensive fit cannot be safely resumed"
        )

    proof_path = clone / "bodyrig-recovery-proof.json"
    identity_path = clone / "bodyrig-visual-identity.json"
    portable_identity_path = clone / "bodyrig-portable-identity.json"
    fitter_config = outer / "bodyrig-sith-fitter-config.json"
    source_manifest = outer / "bodyrig-stash-source-manifest.json"
    package = clone / f"{failed['body_id']}.mrbody"

    try:
        proof = load_recovery_proof(proof_path)
        identity = bind_visual_identity_to_proof(
            read_canonical_json(identity_path, label="visual identity profile"),
            proof,
        )
        portable = bind_portable_identity_to_evidence(
            load_portable_identity(portable_identity_path),
            proof=proof,
            visual_identity=identity,
            requested_alias=failed["body_id"],
        )
        config = validate_external_fitter_config(
            read_canonical_json(fitter_config, label="external fitter config")
        )
    except ValueError as exc:
        raise InterruptedFitRecoveryError(str(exc)) from exc
    if config["adapter"] != "sith-smplx-vrm" or config["revision"] != "1":
        raise InterruptedFitRecoveryError("interrupted fit does not use the production SiTH SMPL-X fitter")

    manifest = _read_json(source_manifest, label="Stash source manifest")
    if manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise InterruptedFitRecoveryError("unsupported Stash source manifest format/version")
    if manifest.get("source_kind") != "stash-local":
        raise InterruptedFitRecoveryError("interrupted physical recovery requires a stash-local source manifest")
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        raise InterruptedFitRecoveryError("Stash source manifest must contain 1..10 selected sources")
    performer = manifest.get("performer")
    if not isinstance(performer, Mapping):
        raise InterruptedFitRecoveryError("Stash source manifest performer binding is missing")
    if str(performer.get("id", "")) != failed["performer_id"]:
        raise InterruptedFitRecoveryError("Stash source manifest performer differs from failed physical session")
    display_name = str(performer.get("name", "")).strip()
    if not display_name or len(display_name) > 160:
        raise InterruptedFitRecoveryError("Stash source manifest display name is invalid")

    package_complete = package.is_file()
    package_sha = None
    if package_complete:
        try:
            validated = validate_package(package)
        except ValueError as exc:
            raise InterruptedFitRecoveryError(f"existing interrupted package is invalid: {exc}") from exc
        if validated.manifest["id"] != portable["body_id"]:
            raise InterruptedFitRecoveryError("existing interrupted package canonical body identity mismatch")
        package_sha = _sha256(package)

    authority = {
        "failed_session_sha256": _sha256(failed_path),
        "recovery_proof_sha256": _sha256(proof_path),
        "visual_identity_sha256": _sha256(identity_path),
        "portable_identity_sha256": _sha256(portable_identity_path),
        "fitter_config_sha256": _sha256(fitter_config),
        "source_manifest_sha256": _sha256(source_manifest),
        "reconstruction_sha256": _sha256(reconstruction),
    }
    if any(not SHA_RE.fullmatch(value) for value in authority.values()):
        raise InterruptedFitRecoveryError("recovery authority produced an invalid SHA-256")

    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": current_revision,
        "performer_id": failed["performer_id"],
        "body_alias": failed["body_id"],
        "display_name": display_name,
        "failed_session_id": failed["session_id"],
        "package_already_complete": package_complete,
        "package_sha256": package_sha,
        "authority": authority,
        "paths": {
            "clone_output": str(outer),
            "clone_dir": str(clone),
            "proof": str(proof_path),
            "visual_identity": str(identity_path),
            "portable_identity": str(portable_identity_path),
            "fitter_config": str(fitter_config),
            "identity_workspace": str(workspace),
            "reconstruction": str(reconstruction),
            "package": str(package),
            "source_manifest": str(source_manifest),
        },
        "expensive_reconstruction_rerun": False,
        "production_activation": False,
    }


def verify_recovered_package(plan: Mapping[str, Any], package_path: str | os.PathLike[str]) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or plan.get("format") != FORMAT or plan.get("version") != VERSION:
        raise InterruptedFitRecoveryError("unsupported interrupted fit recovery plan")
    authority = plan.get("authority")
    paths = plan.get("paths")
    if not isinstance(authority, Mapping) or not isinstance(paths, Mapping):
        raise InterruptedFitRecoveryError("interrupted fit recovery plan is incomplete")

    reconstruction = Path(str(paths.get("reconstruction", ""))).expanduser().resolve()
    expected_reconstruction = str(authority.get("reconstruction_sha256", ""))
    if _sha256(reconstruction) != expected_reconstruction:
        raise InterruptedFitRecoveryError(
            "SiTH reconstruction authority changed during recovery; refusing no-reconstruction-rerun claim"
        )

    proof_path = Path(str(paths.get("proof", ""))).expanduser().resolve()
    identity_path = Path(str(paths.get("visual_identity", ""))).expanduser().resolve()
    portable_identity_path = Path(str(paths.get("portable_identity", ""))).expanduser().resolve()
    try:
        proof = load_recovery_proof(proof_path)
        identity = bind_visual_identity_to_proof(
            read_canonical_json(identity_path, label="visual identity profile"), proof
        )
        portable = bind_portable_identity_to_evidence(
            load_portable_identity(portable_identity_path),
            proof=proof,
            visual_identity=identity,
            requested_alias=str(plan.get("body_alias", "")),
        )
    except ValueError as exc:
        raise InterruptedFitRecoveryError(str(exc)) from exc

    package = Path(package_path).expanduser().resolve()
    try:
        validated = validate_package(package)
    except ValueError as exc:
        raise InterruptedFitRecoveryError(f"recovered package failed strict validation: {exc}") from exc
    if validated.manifest["id"] != portable["body_id"]:
        raise InterruptedFitRecoveryError("recovered package canonical body identity mismatch")
    return {
        "package_sha256": _sha256(package),
        "reconstruction_sha256": expected_reconstruction,
        "canonical_body_id": validated.manifest["id"],
        "expensive_reconstruction_rerun": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and verify recovery of an interrupted production SiTH fit.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--failed-session", required=True)
    plan.add_argument("--clone-output", required=True)
    plan.add_argument("--identity-workspace", required=True)
    plan.add_argument("--current-revision", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--package", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = build_recovery_plan(
                failed_session_path=args.failed_session,
                stash_clone_output=args.clone_output,
                identity_workspace=args.identity_workspace,
                current_revision=args.current_revision,
            )
        else:
            plan_value = _read_json(Path(args.plan).expanduser().resolve(), label="interrupted fit recovery plan")
            value = verify_recovered_package(plan_value, args.package)
    except (InterruptedFitRecoveryError, OSError, ValueError) as exc:
        print(f"BodyRig interrupted fit recovery: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
