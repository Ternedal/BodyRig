from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-rig-readiness"
VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

TOP_FIELDS = {
    "format",
    "version",
    "session_id",
    "bodyrig_revision",
    "observed_utc",
    "rig_setup_report",
    "rig_setup_sha256",
    "checks",
    "environment",
    "ready",
}
CHECK_FIELDS = {
    "master_setup",
    "recovery",
    "sith_openpose",
    "openpose_binary",
    "openpose_models",
    "diffusion_model",
    "stash",
    "stash_performer_read",
}
ENV_FIELDS = {
    "stash_version",
    "openpose_sha256",
    "openpose_byte_count",
    "openpose_models_sha256",
    "openpose_models_file_count",
    "openpose_models_byte_count",
    "diffusion_model_sha256",
    "diffusion_model_file_count",
    "diffusion_model_byte_count",
}


class RigReadinessError(ValueError):
    pass


def _nonempty(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RigReadinessError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def _sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise RigReadinessError(f"{field} must be lowercase SHA-256")
    return value


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RigReadinessError(f"{field} must be a positive integer")
    return value


def _timestamp(value: Any, *, field: str) -> str:
    text = _nonempty(value, field=field, maximum=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RigReadinessError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RigReadinessError(f"{field} must include a timezone")
    return text


def validate_readiness(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise RigReadinessError("rig readiness fields must match v1 exactly")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise RigReadinessError("unsupported rig readiness format/version")

    try:
        session_id = str(uuid.UUID(_nonempty(value["session_id"], field="session_id", maximum=36)))
    except (ValueError, AttributeError) as exc:
        raise RigReadinessError("session_id must be a UUID") from exc

    revision = value["bodyrig_revision"]
    if not isinstance(revision, str) or not GIT_REVISION_RE.fullmatch(revision):
        raise RigReadinessError("bodyrig_revision must be a lowercase 40-character Git SHA")

    observed_utc = _timestamp(value["observed_utc"], field="observed_utc")
    rig_setup_report = _nonempty(value["rig_setup_report"], field="rig_setup_report", maximum=4000)
    rig_setup_sha256 = _sha(value["rig_setup_sha256"], field="rig_setup_sha256")

    checks = value["checks"]
    if not isinstance(checks, Mapping) or set(checks) != CHECK_FIELDS:
        raise RigReadinessError("readiness checks must match v1 exactly")
    normalized_checks: dict[str, bool] = {}
    for field in sorted(CHECK_FIELDS):
        if checks[field] is not True:
            raise RigReadinessError(f"checks.{field} must be true")
        normalized_checks[field] = True

    environment = value["environment"]
    if not isinstance(environment, Mapping) or set(environment) != ENV_FIELDS:
        raise RigReadinessError("readiness environment fields must match v1 exactly")
    normalized_environment = {
        "stash_version": _nonempty(environment["stash_version"], field="environment.stash_version", maximum=160),
        "openpose_sha256": _sha(environment["openpose_sha256"], field="environment.openpose_sha256"),
        "openpose_byte_count": _positive_int(environment["openpose_byte_count"], field="environment.openpose_byte_count"),
        "openpose_models_sha256": _sha(environment["openpose_models_sha256"], field="environment.openpose_models_sha256"),
        "openpose_models_file_count": _positive_int(environment["openpose_models_file_count"], field="environment.openpose_models_file_count"),
        "openpose_models_byte_count": _positive_int(environment["openpose_models_byte_count"], field="environment.openpose_models_byte_count"),
        "diffusion_model_sha256": _sha(environment["diffusion_model_sha256"], field="environment.diffusion_model_sha256"),
        "diffusion_model_file_count": _positive_int(environment["diffusion_model_file_count"], field="environment.diffusion_model_file_count"),
        "diffusion_model_byte_count": _positive_int(environment["diffusion_model_byte_count"], field="environment.diffusion_model_byte_count"),
    }

    if value["ready"] is not True:
        raise RigReadinessError("ready must be true")

    return {
        "format": FORMAT,
        "version": VERSION,
        "session_id": session_id,
        "bodyrig_revision": revision,
        "observed_utc": observed_utc,
        "rig_setup_report": rig_setup_report,
        "rig_setup_sha256": rig_setup_sha256,
        "checks": normalized_checks,
        "environment": normalized_environment,
        "ready": True,
    }


def load_readiness(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise RigReadinessError(f"rig readiness report not found: {source}")
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RigReadinessError("rig readiness report is invalid JSON") from exc
    return validate_readiness(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strictly validate BodyRig live rig readiness evidence.")
    parser.add_argument("report")
    args = parser.parse_args(argv)
    try:
        value = load_readiness(args.report)
    except RigReadinessError as exc:
        print(f"BodyRig rig readiness: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
