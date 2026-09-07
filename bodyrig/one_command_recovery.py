from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .interrupted_fit_recovery import (
    ADOPT_COMPLETE_PACKAGE,
    FORMAT as PLAN_FORMAT,
    RESUME_FIT_ONLY,
    VERSION as PLAN_VERSION,
    build_recovery_plan,
)
from .physical_session import validate_session

RUN_FORMAT = "bodyrig-one-command-production-authority"
RUN_VERSION = 1
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OneCommandRecoveryError(ValueError):
    pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OneCommandRecoveryError(f"{label} is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OneCommandRecoveryError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise OneCommandRecoveryError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise OneCommandRecoveryError(f"{label} is missing or symlinked: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise OneCommandRecoveryError(f"could not hash {label}: {path}") from exc
    return digest.hexdigest()


def _need_sha256(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256.fullmatch(text):
        raise OneCommandRecoveryError(f"{label} is not a canonical SHA-256")
    return text


def _same_path(value: Any, expected: Path, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise OneCommandRecoveryError(f"{label} is missing")
    try:
        actual = Path(text).expanduser().resolve(strict=False)
        wanted = expected.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OneCommandRecoveryError(f"{label} path is invalid") from exc
    if actual != wanted:
        raise OneCommandRecoveryError(f"{label} path differs from one-command authority")
    return actual


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def inspect_one_command_recovery(session_report: str | Path) -> dict[str, Any] | None:
    """Validate a producer-written interrupted-fit plan without reinterpreting it.

    This is intentionally structural/hash-bound so a historical run can be ranked
    before re-entering its producer revision. The producer revision performs the
    full semantic recovery-plan validation again before any mutating resume.
    """

    session_path = Path(session_report).expanduser().resolve(strict=False)
    run_root = session_path.parent
    authority_path = run_root / "run-authority.json"
    if not authority_path.exists():
        return None

    authority = _read_json(authority_path, "one-command run authority")
    if authority.get("format") != RUN_FORMAT or authority.get("version") != RUN_VERSION:
        return None
    plan_text = str(authority.get("interrupted_fit_recovery_plan") or "").strip()
    plan_hash_text = str(authority.get("interrupted_fit_recovery_plan_sha256") or "").strip()
    identity_text = str(authority.get("identity_workspace") or "").strip()
    if not (plan_text or plan_hash_text or identity_text):
        return None
    if not (plan_text and plan_hash_text and identity_text):
        raise OneCommandRecoveryError("one-command interrupted recovery authority is incomplete")

    revision = str(authority.get("bodyrig_revision") or "").strip().lower()
    if not SHA40.fullmatch(revision):
        raise OneCommandRecoveryError("one-command recovery has no canonical BodyRig revision")
    performer_id = str(authority.get("performer_id") or "").strip()
    body_id = str(authority.get("requested_body_alias") or "").strip()
    if not performer_id or not body_id:
        raise OneCommandRecoveryError("one-command recovery is missing performer/body scope")

    _same_path(authority.get("session_report"), session_path, "run session_report")
    clone_output = _same_path(authority.get("clone_output"), run_root / "clone-output", "run clone_output")
    plan_path = _same_path(plan_text, run_root / "interrupted-fit-recovery-plan.json", "recovery plan")
    expected_plan_hash = _need_sha256(plan_hash_text, "run interrupted_fit_recovery_plan_sha256")
    if _sha256(plan_path, "interrupted recovery plan") != expected_plan_hash:
        raise OneCommandRecoveryError("interrupted recovery plan bytes changed after producer publication")

    identity_workspace = Path(identity_text).expanduser().resolve(strict=False)
    if identity_workspace.is_symlink() or not identity_workspace.is_dir():
        raise OneCommandRecoveryError(f"private identity workspace is missing or symlinked: {identity_workspace}")

    session_raw = _read_json(session_path, "failed physical session")
    try:
        session = validate_session(session_raw)
    except ValueError as exc:
        raise OneCommandRecoveryError(str(exc)) from exc
    if session["status"] != "fail" or session["stage"] != "clone":
        raise OneCommandRecoveryError("one-command interrupted recovery requires a clone-stage failed session")
    if session["bodyrig_revision"] != revision or session["performer_id"] != performer_id or session["body_id"] != body_id:
        raise OneCommandRecoveryError("failed session scope/revision differs from one-command run authority")
    if session["bodyrig_checkout_clean"] is not True or session["readiness_sha256"] is None:
        raise OneCommandRecoveryError("failed session lacks clean-checkout/readiness authority")

    plan = _read_json(plan_path, "interrupted fit recovery plan")
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise OneCommandRecoveryError("interrupted fit recovery plan format/version mismatch")
    if str(plan.get("bodyrig_revision") or "").lower() != revision:
        raise OneCommandRecoveryError("recovery plan revision differs from run authority")
    if str(plan.get("performer_id") or "") != performer_id or str(plan.get("body_alias") or "") != body_id:
        raise OneCommandRecoveryError("recovery plan performer/body differs from run authority")

    paths = plan.get("paths")
    hashes = plan.get("authority")
    if not isinstance(paths, Mapping) or not isinstance(hashes, Mapping):
        raise OneCommandRecoveryError("interrupted fit recovery plan lacks paths/authority")

    clone_dir = clone_output / "clone"
    expected_paths = {
        "failed_session": session_path,
        "clone_output": clone_output,
        "clone_dir": clone_dir,
        "proof": clone_dir / "bodyrig-recovery-proof.json",
        "visual_identity": clone_dir / "bodyrig-visual-identity.json",
        "portable_identity": clone_dir / "bodyrig-portable-identity.json",
        "fitter_config": clone_output / "bodyrig-sith-fitter-config.json",
        "source_manifest": clone_output / "bodyrig-stash-source-manifest.json",
        "identity_workspace": identity_workspace,
        "reconstruction": identity_workspace / "sith-input-v1" / "reconstruction.json",
        "package": clone_dir / f"{body_id}.mrbody",
    }
    resolved_paths = {key: _same_path(paths.get(key), expected, f"recovery plan paths.{key}") for key, expected in expected_paths.items()}

    hash_bindings = {
        "failed_session_sha256": (resolved_paths["failed_session"], "failed session"),
        "recovery_proof_sha256": (resolved_paths["proof"], "recovery proof"),
        "visual_identity_sha256": (resolved_paths["visual_identity"], "visual identity"),
        "portable_identity_sha256": (resolved_paths["portable_identity"], "portable identity"),
        "fitter_config_sha256": (resolved_paths["fitter_config"], "fitter config"),
        "source_manifest_sha256": (resolved_paths["source_manifest"], "source manifest"),
    }
    for key, (path, label) in hash_bindings.items():
        expected = _need_sha256(hashes.get(key), f"recovery authority {key}")
        if _sha256(path, label) != expected:
            raise OneCommandRecoveryError(f"{label} bytes changed after producer recovery planning")

    mode = str(plan.get("recovery_mode") or "")
    if mode == ADOPT_COMPLETE_PACKAGE:
        if plan.get("package_already_complete") is not True:
            raise OneCommandRecoveryError("complete-package recovery mode is not bound to package_already_complete=true")
        package_sha = _need_sha256(plan.get("package_sha256"), "recovery plan package_sha256")
        if _sha256(resolved_paths["package"], "interrupted package") != package_sha:
            raise OneCommandRecoveryError("completed interrupted package changed after producer recovery planning")
        rank = 8
        fitter_rerun = False
    elif mode == RESUME_FIT_ONLY:
        if plan.get("package_already_complete") is not False:
            raise OneCommandRecoveryError("fit-only recovery mode is not bound to package_already_complete=false")
        reconstruction_sha = _need_sha256(hashes.get("reconstruction_sha256"), "recovery authority reconstruction_sha256")
        if _sha256(resolved_paths["reconstruction"], "SiTH reconstruction") != reconstruction_sha:
            raise OneCommandRecoveryError("SiTH reconstruction changed after producer recovery planning")
        rank = 5
        fitter_rerun = True
    else:
        raise OneCommandRecoveryError(f"unsupported interrupted recovery mode: {mode}")

    return {
        "state": "ready",
        "gate": "interrupted-fit-recovery",
        "progress_rank": rank,
        "recovery_mode": mode,
        "fitter_rerun": fitter_rerun,
        "expensive_reconstruction_rerun": False,
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "body_id": body_id,
        "run_root": str(run_root),
        "session_report": str(session_path),
        "clone_output": str(clone_output),
        "identity_workspace": str(identity_workspace),
        "recovery_plan": str(plan_path),
        "recovery_plan_sha256": expected_plan_hash,
    }


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except OSError as exc:
        raise OneCommandRecoveryError("Git executable unavailable for one-command recovery status") from exc


def build_live_recovery_status(session_report: str | Path, repo_root: str | Path) -> dict[str, Any] | None:
    structural = inspect_one_command_recovery(session_report)
    if structural is None:
        return None
    root = Path(repo_root).expanduser().resolve()
    head_result = _git(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip().lower()
    if head_result.returncode != 0 or not SHA40.fullmatch(head):
        raise OneCommandRecoveryError("could not resolve current checkout revision")
    if head != structural["bodyrig_revision"]:
        raise OneCommandRecoveryError(
            f"one-command recovery belongs to {structural['bodyrig_revision']}, not current checkout {head}"
        )
    dirty = _git(root, "status", "--porcelain")
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise OneCommandRecoveryError("one-command recovery requires an exact clean producer checkout")

    try:
        live = build_recovery_plan(
            failed_session_path=structural["session_report"],
            stash_clone_output=structural["clone_output"],
            identity_workspace=structural["identity_workspace"],
            current_revision=head,
        )
    except ValueError as exc:
        raise OneCommandRecoveryError(f"producer recovery plan no longer validates: {exc}") from exc
    if str(live.get("recovery_mode") or "") != structural["recovery_mode"]:
        raise OneCommandRecoveryError("producer recovery mode changed since the persisted recovery plan")

    command = (
        ".\\resume-interrupted-physical-fit.ps1 "
        f"-FailedSessionReport {_ps_quote(structural['session_report'])} "
        f"-CloneOutput {_ps_quote(structural['clone_output'])} "
        f"-IdentityWorkspace {_ps_quote(structural['identity_workspace'])}"
    )
    mode = structural["recovery_mode"]
    if mode == ADOPT_COMPLETE_PACKAGE:
        message = "A complete verified package survived the failed one-command clone; adopt it without reconstruction or fitter rerun."
    else:
        message = "A completed SiTH reconstruction survived the failed one-command clone; rerun only the fitter against the same reconstruction authority."
    return {
        **structural,
        "message": message,
        "next_command": command,
        "read_only": True,
        "policy_scope": "producer-revision-one-command-recovery",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only producer-bound one-command interrupted fit recovery status")
    parser.add_argument("--session-report", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = build_live_recovery_status(args.session_report, args.repo_root)
    except (OneCommandRecoveryError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"BodyRig one-command recovery status: ERROR | {exc}", file=sys.stderr)
        return 2
    if status is None:
        return 3
    if args.json:
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    else:
        print(f"BodyRig one-command recovery status: READY | {status['recovery_mode']}")
        print(status["message"])
        print(f"Revision: {status['bodyrig_revision']}")
        print(f"Run root: {status['run_root']}")
        print("Next command:")
        print(status["next_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
