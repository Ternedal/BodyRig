from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .avatar import AvatarError, AvatarFitResult, validate_vrm1
from .bridges.bodyprint_shape_adjust import (
    BodyprintAdjustmentError,
    validate_adjustment_payload,
)
from .identity import validate_visual_identity
from .logged_process import run_logged_process
from .package import validate_bodyprint

REQUEST_FORMAT = "bodyrig-avatar-fit-request"
RESULT_FORMAT = "bodyrig-avatar-fit-result"
VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ExternalFitterError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalFitterResult:
    fit: AvatarFitResult
    visual_identity: str


def _read_log_tail(path: Path, limit: int = 4000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def build_external_fit_request(
    *,
    bodyprint: Mapping[str, Any],
    name: str,
    identity: Mapping[str, Any],
    bodyprint_adjustment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build metadata passed to an isolated reconstruction engine.

    The private identity workspace path is deliberately *not* part of the JSON
    request. An invoker passes that path separately to the process, and BodyRig
    never writes it to provenance or the portable package. A reviewed BodyPrint
    adjustment contains only bounded semantic deltas and a feedback hash; no raw
    operator comment or source-media path crosses the fitter boundary.
    """

    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise ExternalFitterError("avatar name must contain 1..160 characters")
    validated_bodyprint = validate_bodyprint(dict(bodyprint))
    validated_identity = validate_visual_identity(identity)
    request: dict[str, Any] = {
        "format": REQUEST_FORMAT,
        "version": VERSION,
        "name": name.strip(),
        "bodyprint": validated_bodyprint,
        "visual_identity": validated_identity,
    }
    if bodyprint_adjustment is not None:
        try:
            request["bodyprint_adjustment"] = validate_adjustment_payload(dict(bodyprint_adjustment))
        except BodyprintAdjustmentError as exc:
            raise ExternalFitterError(str(exc)) from exc
    return request


def validate_external_fit_output(
    output_dir: str | Path,
    *,
    expected_adapter: str,
    expected_revision: str,
) -> ExternalFitterResult:
    """Validate an isolated fitter result before BodyRig can package it.

    The external environment may be arbitrary research code; the trust boundary
    is the files it returns. BodyRig accepts only fixed filenames, strict JSON,
    exact hashes, a valid VRM 1.0 avatar and a real PNG thumbnail.
    """

    if not ADAPTER_RE.fullmatch(expected_adapter):
        raise ExternalFitterError("expected adapter id is invalid")
    if not isinstance(expected_revision, str) or not expected_revision.strip() or len(expected_revision) > 160:
        raise ExternalFitterError("expected adapter revision is invalid")

    root = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise ExternalFitterError(f"external fitter output directory not found: {root}")
    expected_names = {"result.json", "avatar.vrm", "thumbnail.png"}
    children = list(root.iterdir())
    actual_names = {path.name for path in children}
    if actual_names != expected_names or any(not path.is_file() for path in children):
        raise ExternalFitterError("external fitter output must contain exactly result.json, avatar.vrm and thumbnail.png")

    try:
        result = json.loads(
            (root / "result.json").read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExternalFitterError("external fitter result.json is invalid canonical JSON") from exc

    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "visual_identity",
        "avatar_sha256",
        "thumbnail_sha256",
    }
    if not isinstance(result, dict) or set(result) != required:
        raise ExternalFitterError("external fitter result fields must match v1 exactly")
    if result["format"] != RESULT_FORMAT or result["version"] != VERSION:
        raise ExternalFitterError("unsupported external fitter result format/version")
    if result["adapter"] != expected_adapter or result["revision"] != expected_revision:
        raise ExternalFitterError("external fitter adapter/revision does not match the selected adapter")
    if result["visual_identity"] != "source-derived":
        raise ExternalFitterError("external fitter must explicitly report source-derived visual identity")

    avatar = (root / "avatar.vrm").read_bytes()
    thumbnail = (root / "thumbnail.png").read_bytes()
    avatar_hash = hashlib.sha256(avatar).hexdigest()
    thumbnail_hash = hashlib.sha256(thumbnail).hexdigest()
    for field, actual in (("avatar_sha256", avatar_hash), ("thumbnail_sha256", thumbnail_hash)):
        expected = result[field]
        if not isinstance(expected, str) or not SHA_RE.fullmatch(expected) or expected != actual:
            raise ExternalFitterError(f"external fitter {field} mismatch")

    try:
        validate_vrm1(avatar)
    except AvatarError as exc:
        raise ExternalFitterError(f"external fitter avatar is not valid VRM 1.0: {exc}") from exc
    if not thumbnail.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ExternalFitterError("external fitter thumbnail is not PNG")

    return ExternalFitterResult(
        fit=AvatarFitResult(
            avatar_vrm=avatar,
            thumbnail_png=thumbnail,
            adapter=expected_adapter,
            revision=expected_revision,
        ),
        visual_identity="source-derived",
    )


def run_external_fitter(
    command: Sequence[str],
    *,
    workspace: str | Path,
    bodyprint: Mapping[str, Any],
    name: str,
    identity: Mapping[str, Any],
    adapter: str,
    revision: str,
    bodyprint_adjustment: Mapping[str, Any] | None = None,
    timeout_seconds: int = 3600,
) -> ExternalFitterResult:
    """Run an operator-selected high-fidelity engine behind a file boundary.

    `command` is executed directly with `shell=False`; no command string is
    interpreted by a shell and no executable path can come from `.mrbody` data.
    The private workspace may contain derived source frames, but its path is only
    supplied as a process argument and is absent from request/result/provenance.
    """

    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ExternalFitterError("external fitter command must contain non-empty argv entries")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 86_400:
        raise ExternalFitterError("external fitter timeout_seconds must be in 1..86400")
    if not ADAPTER_RE.fullmatch(adapter):
        raise ExternalFitterError("external fitter adapter id is invalid")
    if not isinstance(revision, str) or not revision.strip() or len(revision) > 160:
        raise ExternalFitterError("external fitter revision is invalid")

    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ExternalFitterError(f"visual identity workspace not found: {workspace_path}")

    request = build_external_fit_request(
        bodyprint=bodyprint,
        name=name,
        identity=identity,
        bodyprint_adjustment=bodyprint_adjustment,
    )
    with tempfile.TemporaryDirectory(prefix="bodyrig-external-fit-") as temp_name:
        temp = Path(temp_name)
        request_path = temp / "request.json"
        output_dir = temp / "output"
        log_path = temp / "adapter.log"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        output_dir.mkdir()

        invoke = [
            *argv,
            "--bodyrig-request",
            str(request_path),
            "--bodyrig-workspace",
            str(workspace_path),
            "--bodyrig-output",
            str(output_dir),
            "--bodyrig-adapter",
            adapter,
            "--bodyrig-revision",
            revision,
        ]
        try:
            completed = run_logged_process(
                invoke,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ExternalFitterError(
                f"external fitter timed out after {timeout_seconds} seconds{suffix}"
            ) from exc
        except OSError as exc:
            detail = _read_log_tail(log_path)
            suffix = f" | log tail: {detail}" if detail else ""
            raise ExternalFitterError(
                f"external fitter process could not complete: {exc}{suffix}"
            ) from exc
        if completed.returncode != 0:
            detail = _read_log_tail(log_path)
            suffix = f": {detail}" if detail else ""
            raise ExternalFitterError(
                f"external fitter process failed with exit code {completed.returncode}{suffix}"
            )

        return validate_external_fit_output(
            output_dir,
            expected_adapter=adapter,
            expected_revision=revision,
        )
