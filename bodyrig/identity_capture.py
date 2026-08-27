from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .identity import VisualIdentityError, bind_visual_identity_to_proof
from .logged_process import run_logged_process

ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class IdentityCaptureError(ValueError):
    pass


def run_identity_capture(
    command: Sequence[str],
    *,
    sources: Sequence[str | Path],
    proof: dict[str, Any],
    workspace: str | Path,
    adapter: str,
    revision: str,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run identity observation/capture behind a private file boundary.

    Source paths are process arguments only. They are not serialized into the
    metadata request or the returned portable identity profile. The adapter may
    place derived/private artifacts in `workspace`; BodyRig core only accepts a
    single strict `identity.json` from the ephemeral result directory.
    """

    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise IdentityCaptureError("identity capture command must contain non-empty argv entries")
    if not ADAPTER_RE.fullmatch(adapter):
        raise IdentityCaptureError("identity capture adapter id is invalid")
    if not isinstance(revision, str) or not revision.strip() or len(revision) > 160:
        raise IdentityCaptureError("identity capture revision is invalid")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 86_400:
        raise IdentityCaptureError("identity capture timeout_seconds must be in 1..86400")

    resolved_sources: list[Path] = []
    if not 1 <= len(sources) <= 10:
        raise IdentityCaptureError("identity capture requires 1..10 source files")
    for item in sources:
        source = Path(item).expanduser().resolve()
        if not source.is_file():
            raise IdentityCaptureError(f"identity capture source file not found: {source}")
        resolved_sources.append(source)
    if len(resolved_sources) != proof.get("source_count"):
        raise IdentityCaptureError("identity capture source count does not match recovery proof")

    workspace_path = Path(workspace).expanduser().resolve()
    if workspace_path.exists():
        raise IdentityCaptureError("identity capture workspace already exists; refusing cross-run reuse")
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_path.mkdir()

    request = {
        "format": "bodyrig-identity-capture-request",
        "version": 1,
        "adapter": adapter,
        "revision": revision,
        "source_count": proof["source_count"],
        "subject_track_id": proof["track_id"],
        "observed_frames": proof["observed_frames"],
    }

    success = False
    try:
        with tempfile.TemporaryDirectory(prefix="bodyrig-identity-capture-") as temp_name:
            temp = Path(temp_name)
            request_path = temp / "request.json"
            result_dir = temp / "result"
            log_path = temp / "adapter.log"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            result_dir.mkdir()

            invoke = [
                *argv,
                "--bodyrig-request",
                str(request_path),
                "--bodyrig-workspace",
                str(workspace_path),
                "--bodyrig-output",
                str(result_dir),
                "--bodyrig-adapter",
                adapter,
                "--bodyrig-revision",
                revision,
            ]
            for source in resolved_sources:
                invoke.extend(("--bodyrig-source", str(source)))

            try:
                completed = run_logged_process(
                    invoke,
                    log_path=log_path,
                    timeout_seconds=timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise IdentityCaptureError("identity capture process could not complete") from exc
            if completed.returncode != 0:
                raise IdentityCaptureError(
                    f"identity capture process failed with exit code {completed.returncode}"
                )

            children = list(result_dir.iterdir())
            if len(children) != 1 or children[0].name != "identity.json" or not children[0].is_file():
                raise IdentityCaptureError(
                    "identity capture result must contain exactly identity.json"
                )
            try:
                raw = json.loads(
                    children[0].read_text(encoding="utf-8"),
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise IdentityCaptureError("identity capture identity.json is invalid canonical JSON") from exc

            try:
                identity = bind_visual_identity_to_proof(raw, proof)
            except VisualIdentityError as exc:
                raise IdentityCaptureError(str(exc)) from exc
            if identity["adapter"] != adapter or identity["revision"] != revision:
                raise IdentityCaptureError(
                    "identity capture profile adapter/revision does not match selected adapter"
                )
            success = True
            return identity
    finally:
        if not success:
            shutil.rmtree(workspace_path, ignore_errors=True)
