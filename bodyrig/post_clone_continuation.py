from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from .package import validate_package
from .physical_session import validate_session

FORMAT = "bodyrig-post-clone-continuation-plan"
VERSION = 1
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PostCloneContinuationError(ValueError):
    pass


def _sha256(path: Path, *, label: str) -> str:
    if not path.is_file():
        raise PostCloneContinuationError(f"{label} not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    value = digest.hexdigest()
    if not SHA_RE.fullmatch(value):
        raise PostCloneContinuationError(f"{label} produced an invalid SHA-256")
    return value


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PostCloneContinuationError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PostCloneContinuationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PostCloneContinuationError(f"{label} must be a JSON object")
    return value


def build_post_clone_plan(
    *,
    session_report: str | os.PathLike[str],
    clone_output: str | os.PathLike[str],
    current_revision: str,
) -> dict[str, Any]:
    if not isinstance(current_revision, str) or not GIT_RE.fullmatch(current_revision):
        raise PostCloneContinuationError("current_revision must be a lowercase Git SHA")

    session_path = Path(session_report).expanduser().resolve()
    try:
        session = validate_session(_read_json(session_path, label="physical clone session"))
    except ValueError as exc:
        raise PostCloneContinuationError(str(exc)) from exc
    if session["status"] != "pass" or session["stage"] != "complete":
        raise PostCloneContinuationError("post-clone continuation requires a completed PASS physical clone session")
    if session["bodyrig_revision"] != current_revision:
        raise PostCloneContinuationError("physical clone session belongs to a different BodyRig revision")
    if session["bodyrig_checkout_clean"] is not True:
        raise PostCloneContinuationError("physical clone session was not bound to a clean checkout")

    outer = Path(clone_output).expanduser().resolve()
    if not outer.is_dir():
        raise PostCloneContinuationError(f"physical clone output not found: {outer}")
    session_clone_output = Path(str(session.get("clone_output") or "")).expanduser().resolve()
    if session_clone_output != outer:
        raise PostCloneContinuationError("persisted UI job clone output differs from the completed physical session")

    readiness_path = session_path.with_suffix(".readiness.json")
    readiness_sha = _sha256(readiness_path, label="physical clone readiness report")
    if readiness_sha != str(session.get("readiness_sha256") or ""):
        raise PostCloneContinuationError("physical clone readiness bytes no longer match the completed session")

    source_manifest_path = outer / "bodyrig-stash-source-manifest.json"
    source_manifest = _read_json(source_manifest_path, label="Stash source manifest")
    if source_manifest.get("format") != "bodyrig-stash-source-manifest" or source_manifest.get("version") != 1:
        raise PostCloneContinuationError("unsupported Stash source manifest format/version")
    if source_manifest.get("source_kind") != "stash-local":
        raise PostCloneContinuationError("post-clone continuation requires a stash-local source manifest")
    performer = source_manifest.get("performer")
    if not isinstance(performer, Mapping) or str(performer.get("id") or "") != session["performer_id"]:
        raise PostCloneContinuationError("Stash source manifest performer differs from the completed physical session")
    selected = source_manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        raise PostCloneContinuationError("Stash source manifest must contain 1..10 selected sources")

    clone_dir = outer / "clone"
    if not clone_dir.is_dir():
        raise PostCloneContinuationError("completed physical clone is missing the nested clone directory")
    required = {
        "recovery_preflight": clone_dir / "bodyrig-recovery-preflight.json",
        "recovery_proof": clone_dir / "bodyrig-recovery-proof.json",
        "visual_identity": clone_dir / "bodyrig-visual-identity.json",
        "portable_identity": clone_dir / "bodyrig-portable-identity.json",
    }
    authority: dict[str, str] = {
        "session_sha256": _sha256(session_path, label="physical clone session"),
        "readiness_sha256": readiness_sha,
        "source_manifest_sha256": _sha256(source_manifest_path, label="Stash source manifest"),
    }
    for key, path in required.items():
        authority[f"{key}_sha256"] = _sha256(path, label=key.replace("_", " "))

    package_path = clone_dir / f"{session['body_id']}.mrbody"
    try:
        package = validate_package(package_path)
    except (OSError, ValueError) as exc:
        raise PostCloneContinuationError(f"completed physical clone package is invalid: {exc}") from exc
    package_sha = _sha256(package_path, label="physical clone package")
    authority["package_sha256"] = package_sha

    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": current_revision,
        "performer_id": session["performer_id"],
        "body_alias": session["body_id"],
        "session_id": session["session_id"],
        "canonical_body_id": package.manifest["id"],
        "package_sha256": package_sha,
        "source_count": len(selected),
        "authority": authority,
        "paths": {
            "session_report": str(session_path),
            "readiness": str(readiness_path),
            "clone_output": str(outer),
            "clone_dir": str(clone_dir),
            "source_manifest": str(source_manifest_path),
            "package": str(package_path),
            **{key: str(path) for key, path in required.items()},
        },
        "recovery_rerun": False,
        "fitter_rerun": False,
        "gate_a_rerun": True,
        "fidelity_rerun": True,
        "production_activation": False,
    }
