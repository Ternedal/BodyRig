from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from .identity_capture import IdentityCaptureError, run_identity_capture
from .proof import ProofError, load_recovery_proof, read_canonical_json

CONFIG_FORMAT = "bodyrig-identity-capture-config"
CONFIG_VERSION = 1
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class IdentityCaptureConfigError(ValueError):
    pass


def validate_identity_capture_config(value: Any) -> dict[str, Any]:
    required = {"format", "version", "adapter", "revision", "command", "timeout_seconds"}
    if not isinstance(value, dict) or set(value) != required:
        raise IdentityCaptureConfigError("identity capture config fields must match v1 exactly")
    if value["format"] != CONFIG_FORMAT or value["version"] != CONFIG_VERSION:
        raise IdentityCaptureConfigError("unsupported identity capture config format/version")
    adapter = value["adapter"]
    if not isinstance(adapter, str) or not ADAPTER_RE.fullmatch(adapter):
        raise IdentityCaptureConfigError("identity capture config adapter is invalid")
    revision = value["revision"]
    if not isinstance(revision, str) or not revision.strip() or len(revision) > 160:
        raise IdentityCaptureConfigError("identity capture config revision is invalid")
    command = value["command"]
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 32
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in command)
    ):
        raise IdentityCaptureConfigError(
            "identity capture config command must be 1..32 non-empty argv strings"
        )
    timeout = value["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86_400:
        raise IdentityCaptureConfigError("identity capture timeout_seconds must be in 1..86400")
    return value


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise IdentityCaptureError(f"identity profile output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a strict BodyRig visual identity profile from local source video."
    )
    parser.add_argument("proof", help="bodyrig-recovery-proof.json for the selected subject")
    parser.add_argument("sources", nargs="+", help="1..10 local source video files used by recovery")
    parser.add_argument("--config", required=True, help="bodyrig-identity-capture-config v1 JSON")
    parser.add_argument(
        "--workspace",
        required=True,
        help="New private workspace for source-derived identity artifacts; must not already exist",
    )
    parser.add_argument("--out", required=True, help="New bodyrig-visual-identity JSON path")
    args = parser.parse_args(argv)

    try:
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            raise IdentityCaptureError(f"identity profile output already exists: {output}")
        proof = load_recovery_proof(args.proof)
        config = validate_identity_capture_config(
            read_canonical_json(args.config, label="identity capture config")
        )
        identity = run_identity_capture(
            config["command"],
            sources=args.sources,
            proof=proof,
            workspace=args.workspace,
            adapter=config["adapter"],
            revision=config["revision"],
            timeout_seconds=config["timeout_seconds"],
        )
        _write_new_json(output, identity)
    except (
        OSError,
        ValueError,
        ProofError,
        IdentityCaptureConfigError,
        IdentityCaptureError,
    ) as exc:
        print(f"BodyRig identity capture: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
