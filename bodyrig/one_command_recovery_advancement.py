from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .interrupted_fit_recovery import ADOPT_COMPLETE_PACKAGE, RESUME_FIT_ONLY
from .package import validate_package
from .physical_session import validate_session

SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORMAT = "bodyrig-interrupted-physical-fit-recovery"
VERSION = 1


class OneCommandRecoveryAdvancementError(ValueError):
    pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OneCommandRecoveryAdvancementError(f"{label} is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OneCommandRecoveryAdvancementError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise OneCommandRecoveryAdvancementError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise OneCommandRecoveryAdvancementError(f"{label} is missing or symlinked: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise OneCommandRecoveryAdvancementError(f"could not hash {label}: {path}") from exc
    return digest.hexdigest()


def _need_sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256.fullmatch(text):
        raise OneCommandRecoveryAdvancementError(f"{label} is not a canonical SHA-256")
    return text


def _require_hash(path: Path, expected: Any, label: str) -> str:
    wanted = _need_sha(expected, label)
    actual = _sha256(path, label)
    if actual != wanted:
        raise OneCommandRecoveryAdvancementError(f"{label} bytes changed after recovery publication")
    return actual


def inspect_completed_recovery(structural: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate a completed interrupted-fit recovery published after a one-command failure.

    `structural` must come from the producer-bound one-command recovery validator.
    The recovered session/receipt do not become a new trust root: all identity,
    package and session hashes are rebound here before the planner may advance.
    """

    clone_output = Path(str(structural.get("clone_output") or "")).expanduser().resolve(strict=False)
    failed_session = Path(str(structural.get("session_report") or "")).expanduser().resolve(strict=False)
    identity_workspace = Path(str(structural.get("identity_workspace") or "")).expanduser().resolve(strict=False)
    recovered_session = clone_output / "physical-session-recovered.json"
    recovery_receipt = clone_output / "interrupted-fit-recovery.json"

    session_exists = recovered_session.exists()
    receipt_exists = recovery_receipt.exists()
    if not session_exists and not receipt_exists:
        return None
    if session_exists != receipt_exists:
        raise OneCommandRecoveryAdvancementError(
            "completed interrupted recovery is incomplete: recovered session and recovery receipt must exist together"
        )

    receipt = _read_json(recovery_receipt, "interrupted fit recovery receipt")
    if receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise OneCommandRecoveryAdvancementError("interrupted fit recovery receipt format/version mismatch")

    failed_raw = _read_json(failed_session, "failed physical session")
    recovered_raw = _read_json(recovered_session, "recovered physical session")
    try:
        failed = validate_session(failed_raw)
        recovered = validate_session(recovered_raw)
    except ValueError as exc:
        raise OneCommandRecoveryAdvancementError(str(exc)) from exc

    revision = str(structural.get("bodyrig_revision") or "").strip().lower()
    performer_id = str(structural.get("performer_id") or "")
    body_id = str(structural.get("body_id") or "")
    mode = str(structural.get("recovery_mode") or "")
    if failed["status"] != "fail" or failed["stage"] != "clone":
        raise OneCommandRecoveryAdvancementError("producer session is no longer a clone-stage failure")
    if recovered["status"] != "pass" or recovered["stage"] != "complete":
        raise OneCommandRecoveryAdvancementError("recovered physical session is not a completed PASS")
    for label, session in (("failed", failed), ("recovered", recovered)):
        if session["bodyrig_revision"] != revision:
            raise OneCommandRecoveryAdvancementError(f"{label} session revision differs from producer recovery authority")
        if session["performer_id"] != performer_id or session["body_id"] != body_id:
            raise OneCommandRecoveryAdvancementError(f"{label} session scope differs from producer recovery authority")
        if session["bodyrig_checkout_clean"] is not True:
            raise OneCommandRecoveryAdvancementError(f"{label} session was not bound to a clean checkout")
    recovered_clone = Path(str(recovered.get("clone_output") or "")).expanduser().resolve(strict=False)
    if recovered_clone != clone_output:
        raise OneCommandRecoveryAdvancementError("recovered session clone_output differs from one-command recovery authority")

    if str(receipt.get("bodyrig_revision") or "").lower() != revision:
        raise OneCommandRecoveryAdvancementError("recovery receipt revision differs from producer recovery authority")
    if str(receipt.get("performer_id") or "") != performer_id or str(receipt.get("body_alias") or "") != body_id:
        raise OneCommandRecoveryAdvancementError("recovery receipt scope differs from producer recovery authority")
    if str(receipt.get("recovery_mode") or "") != mode:
        raise OneCommandRecoveryAdvancementError("recovery receipt mode differs from producer recovery plan")
    if receipt.get("expensive_reconstruction_rerun") is not False:
        raise OneCommandRecoveryAdvancementError("recovery receipt does not preserve no-reconstruction-rerun authority")
    expected_fitter = mode == RESUME_FIT_ONLY
    if receipt.get("fitter_rerun") is not expected_fitter:
        raise OneCommandRecoveryAdvancementError("recovery receipt fitter-rerun flag is inconsistent with recovery mode")
    if receipt.get("resumed_fit_only") is not expected_fitter:
        raise OneCommandRecoveryAdvancementError("recovery receipt resumed-fit-only flag is inconsistent")
    if receipt.get("adopted_complete_package") is not (mode == ADOPT_COMPLETE_PACKAGE):
        raise OneCommandRecoveryAdvancementError("recovery receipt package-adoption flag is inconsistent")
    if receipt.get("production_activation") is not False:
        raise OneCommandRecoveryAdvancementError("interrupted fit recovery receipt cannot activate production")

    if str(receipt.get("failed_session_id") or "") != failed["session_id"]:
        raise OneCommandRecoveryAdvancementError("recovery receipt failed-session id mismatch")
    if str(receipt.get("recovered_session_id") or "") != recovered["session_id"]:
        raise OneCommandRecoveryAdvancementError("recovery receipt recovered-session id mismatch")
    _require_hash(failed_session, receipt.get("failed_session_sha256"), "failed session")
    _require_hash(recovered_session, receipt.get("recovered_session_sha256"), "recovered session")

    clone_dir = clone_output / "clone"
    bound_files = {
        "recovery_proof_sha256": (clone_dir / "bodyrig-recovery-proof.json", "recovery proof"),
        "visual_identity_sha256": (clone_dir / "bodyrig-visual-identity.json", "visual identity"),
        "portable_identity_sha256": (clone_dir / "bodyrig-portable-identity.json", "portable identity"),
        "fitter_config_sha256": (clone_output / "bodyrig-sith-fitter-config.json", "fitter config"),
        "source_manifest_sha256": (clone_output / "bodyrig-stash-source-manifest.json", "source manifest"),
    }
    for field, (path, label) in bound_files.items():
        _require_hash(path, receipt.get(field), label)

    package = clone_dir / f"{body_id}.mrbody"
    package_sha = _require_hash(package, receipt.get("package_sha256"), "recovered package")
    try:
        validated_package = validate_package(package)
    except ValueError as exc:
        raise OneCommandRecoveryAdvancementError(f"recovered package is invalid: {exc}") from exc
    canonical_body = str(receipt.get("canonical_body_id") or "")
    if not canonical_body or validated_package.manifest["id"] != canonical_body:
        raise OneCommandRecoveryAdvancementError("recovery receipt canonical body id differs from recovered package")

    reconstruction_hash = receipt.get("reconstruction_authority_sha256")
    if mode == RESUME_FIT_ONLY:
        expected_reconstruction = _need_sha(reconstruction_hash, "reconstruction authority")
        reconstruction = identity_workspace / "sith-input-v1" / "reconstruction.json"
        if _sha256(reconstruction, "SiTH reconstruction") != expected_reconstruction:
            raise OneCommandRecoveryAdvancementError("SiTH reconstruction changed after completed recovery")
    elif mode == ADOPT_COMPLETE_PACKAGE:
        if reconstruction_hash not in (None, ""):
            raise OneCommandRecoveryAdvancementError("complete-package recovery unexpectedly claims reconstruction authority")
    else:
        raise OneCommandRecoveryAdvancementError(f"unsupported recovery mode: {mode}")

    return {
        "state": "complete",
        "gate": "physical-clone",
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "body_id": body_id,
        "recovery_mode": mode,
        "failed_session": str(failed_session),
        "recovered_session": str(recovered_session),
        "recovery_receipt": str(recovery_receipt),
        "clone_output": str(clone_output),
        "acceptance_dir": str(clone_output / "acceptance"),
        "package_sha256": package_sha,
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": False,
    }
