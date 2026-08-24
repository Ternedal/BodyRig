from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-physical-clone-session"
VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BODY_ID_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
STAGES = {"initializing", "readiness", "clone", "complete"}
STATUSES = {"running", "pass", "fail"}
FIELDS = {
    "format",
    "version",
    "session_id",
    "started_utc",
    "completed_utc",
    "status",
    "stage",
    "performer_id",
    "body_id",
    "rig_setup_sha256",
    "readiness_sha256",
    "clone_output",
    "error",
}


class PhysicalSessionError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _nonempty(value: Any, *, field: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PhysicalSessionError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def _nullable_text(value: Any, *, field: str, maximum: int = 4000) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field=field, maximum=maximum)


def _sha(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PhysicalSessionError(f"{field} must be lowercase SHA-256")
    return value


def _timestamp(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _nonempty(value, field=field, maximum=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhysicalSessionError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PhysicalSessionError(f"{field} must include a timezone")
    return text


def validate_session(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != FIELDS:
        raise PhysicalSessionError("physical clone session fields must match v1 exactly")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise PhysicalSessionError("unsupported physical clone session format/version")

    try:
        session_id = str(uuid.UUID(_nonempty(value["session_id"], field="session_id", maximum=36)))
    except (ValueError, AttributeError) as exc:
        raise PhysicalSessionError("session_id must be a UUID") from exc

    performer_id = _nonempty(value["performer_id"], field="performer_id", maximum=160)
    body_id = _nonempty(value["body_id"], field="body_id", maximum=160)
    if not BODY_ID_RE.fullmatch(body_id):
        raise PhysicalSessionError("body_id has invalid characters")

    started = _timestamp(value["started_utc"], field="started_utc")
    completed = _timestamp(value["completed_utc"], field="completed_utc", nullable=True)
    status = _nonempty(value["status"], field="status", maximum=16)
    stage = _nonempty(value["stage"], field="stage", maximum=16)
    if status not in STATUSES:
        raise PhysicalSessionError("status is unsupported")
    if stage not in STAGES:
        raise PhysicalSessionError("stage is unsupported")

    rig_hash = _sha(value["rig_setup_sha256"], field="rig_setup_sha256")
    readiness_hash = _sha(value["readiness_sha256"], field="readiness_sha256", nullable=True)
    clone_output = _nullable_text(value["clone_output"], field="clone_output", maximum=4000)
    error = _nullable_text(value["error"], field="error", maximum=4000)

    if status == "running":
        if stage == "complete" or completed is not None or error is not None:
            raise PhysicalSessionError("running session state is inconsistent")
    elif status == "pass":
        if stage != "complete" or completed is None or readiness_hash is None or clone_output is None or error is not None:
            raise PhysicalSessionError("passed session state is incomplete")
    else:
        if stage == "complete" or completed is None or error is None:
            raise PhysicalSessionError("failed session state is incomplete")

    if stage in {"clone", "complete"} and readiness_hash is None:
        raise PhysicalSessionError("clone/complete stage requires readiness evidence")

    return {
        "format": FORMAT,
        "version": VERSION,
        "session_id": session_id,
        "started_utc": started,
        "completed_utc": completed,
        "status": status,
        "stage": stage,
        "performer_id": performer_id,
        "body_id": body_id,
        "rig_setup_sha256": rig_hash,
        "readiness_sha256": readiness_hash,
        "clone_output": clone_output,
        "error": error,
    }


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PhysicalSessionError(f"physical clone session not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhysicalSessionError("physical clone session is invalid JSON") from exc
    return validate_session(value)


def _atomic_create(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise PhysicalSessionError(f"physical clone session already exists: {path}") from exc


def _atomic_replace(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def start_session(path: str | Path, *, performer_id: str, body_id: str, rig_setup_sha256: str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    value = validate_session(
        {
            "format": FORMAT,
            "version": VERSION,
            "session_id": str(uuid.uuid4()),
            "started_utc": _utc_now(),
            "completed_utc": None,
            "status": "running",
            "stage": "initializing",
            "performer_id": performer_id,
            "body_id": body_id,
            "rig_setup_sha256": rig_setup_sha256,
            "readiness_sha256": None,
            "clone_output": None,
            "error": None,
        }
    )
    _atomic_create(report_path, value)
    return value


def mark_readiness_pass(path: str | Path, *, readiness_sha256: str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    value = _read(report_path)
    if value["status"] != "running" or value["stage"] not in {"initializing", "readiness"}:
        raise PhysicalSessionError("readiness can only pass from an active pre-clone session")
    value["readiness_sha256"] = _sha(readiness_sha256, field="readiness_sha256")
    value["stage"] = "clone"
    value = validate_session(value)
    _atomic_replace(report_path, value)
    return value


def mark_pass(path: str | Path, *, clone_output: str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    value = _read(report_path)
    if value["status"] != "running" or value["stage"] != "clone":
        raise PhysicalSessionError("session can only pass after readiness and clone execution")
    value["status"] = "pass"
    value["stage"] = "complete"
    value["completed_utc"] = _utc_now()
    value["clone_output"] = _nonempty(clone_output, field="clone_output", maximum=4000)
    value = validate_session(value)
    _atomic_replace(report_path, value)
    return value


def mark_fail(path: str | Path, *, stage: str, message: str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve()
    value = _read(report_path)
    if value["status"] != "running":
        raise PhysicalSessionError("only a running session can be marked failed")
    if stage not in {"initializing", "readiness", "clone"}:
        raise PhysicalSessionError("failure stage is unsupported")
    if stage == "clone" and value["readiness_sha256"] is None:
        raise PhysicalSessionError("clone failure requires readiness evidence")
    value["status"] = "fail"
    value["stage"] = stage
    value["completed_utc"] = _utc_now()
    value["error"] = _nonempty(message, field="error", maximum=4000)
    value = validate_session(value)
    _atomic_replace(report_path, value)
    return value


def _print(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and validate BodyRig physical clone session evidence.")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--out", required=True)
    start.add_argument("--performer-id", required=True)
    start.add_argument("--body-id", required=True)
    start.add_argument("--rig-setup-sha256", required=True)

    readiness = sub.add_parser("readiness-pass")
    readiness.add_argument("report")
    readiness.add_argument("--readiness-sha256", required=True)

    passed = sub.add_parser("pass")
    passed.add_argument("report")
    passed.add_argument("--clone-output", required=True)

    failed = sub.add_parser("fail")
    failed.add_argument("report")
    failed.add_argument("--stage", required=True, choices=("initializing", "readiness", "clone"))
    failed.add_argument("--message", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("report")

    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            value = start_session(args.out, performer_id=args.performer_id, body_id=args.body_id, rig_setup_sha256=args.rig_setup_sha256)
        elif args.command == "readiness-pass":
            value = mark_readiness_pass(args.report, readiness_sha256=args.readiness_sha256)
        elif args.command == "pass":
            value = mark_pass(args.report, clone_output=args.clone_output)
        elif args.command == "fail":
            value = mark_fail(args.report, stage=args.stage, message=args.message)
        else:
            value = _read(Path(args.report).expanduser().resolve())
    except PhysicalSessionError as exc:
        print(f"BodyRig physical clone session: FAIL: {exc}", file=sys.stderr)
        return 1
    _print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
