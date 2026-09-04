from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .bridges.hmr2_checkpoint_bridge import CHECKPOINT_VERSION, RAW_META_FORMAT
from .bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from .storage import data_dir

FORMAT = "bodyrig-recovery-rescue-probe"
VERSION = 1
_WORKSPACE_STAMP = re.compile(r"-(\d{8}-\d{6})-[0-9a-f]{32}$", re.IGNORECASE)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RecoveryRescueProbeError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _tail_text(path: Path, *, maximum_bytes: int = 12000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - maximum_bytes), 0)
            raw = handle.read(maximum_bytes)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def _workspace_timestamp(path: Path) -> datetime | None:
    match = _WORKSPACE_STAMP.search(path.name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _latest_mtime(path: Path) -> datetime | None:
    try:
        stamps = [path.stat().st_mtime]
        stamps.extend(item.stat().st_mtime for item in path.iterdir())
    except OSError:
        return None
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc)


def _valid_raw_meta(meta: dict[str, Any], *, raw_path: Path) -> bool:
    source_sha = str(meta.get("source_sha256") or "").strip().lower()
    return (
        meta.get("format") == RAW_META_FORMAT
        and meta.get("version") == CHECKPOINT_VERSION
        and meta.get("adapter") == ADAPTER_NAME
        and meta.get("revision") == ADAPTER_REVISION
        and isinstance(meta.get("source_index"), int)
        and not isinstance(meta.get("source_index"), bool)
        and _HEX64.fullmatch(source_sha) is not None
        and raw_path.is_file()
        and raw_path.stat().st_size > 0
    )


def _checkpoint_workspace(path: Path) -> dict[str, Any] | None:
    checkpoint_root = path / "selected-segments" / "bodyrig-recovery-checkpoints"
    if not checkpoint_root.is_dir():
        return None

    rows: list[dict[str, Any]] = []
    for meta_path in sorted(checkpoint_root.glob("segment-*.phalp.json")):
        meta = _read_json(meta_path)
        raw_path = meta_path.with_suffix(".pkl")
        valid_raw = bool(meta is not None and _valid_raw_meta(meta, raw_path=raw_path))
        stem = meta_path.name.removesuffix(".phalp.json")
        status = _read_json(checkpoint_root / f"{stem}.status.json")
        canonical = checkpoint_root / f"{stem}.json"
        rows.append(
            {
                "segment": stem,
                "raw_checkpoint": valid_raw,
                "canonical_checkpoint": canonical.is_file() and canonical.stat().st_size > 0,
                "state": str((status or {}).get("state") or "") or None,
                "source_sha256": str((meta or {}).get("source_sha256") or "") or None,
            }
        )

    return {
        "workspace": str(path),
        "workspace_utc": _workspace_timestamp(path).isoformat().replace("+00:00", "Z") if _workspace_timestamp(path) else None,
        "reusable_raw_checkpoints": sum(1 for row in rows if row["raw_checkpoint"]),
        "segments": rows,
    }


def _staging_candidate(path: Path, *, started: datetime | None, completed: datetime | None) -> dict[str, Any] | None:
    latest = _latest_mtime(path)
    if latest is None:
        return None
    if started is not None and latest < started - timedelta(minutes=10):
        return None
    if completed is not None and latest > completed + timedelta(hours=1):
        return None

    status = _read_json(path / "status.json")
    return {
        "staging": str(path),
        "last_write_utc": latest.isoformat().replace("+00:00", "Z"),
        "status": status,
        "stderr_tail": _tail_text(path / "stderr.log"),
        "result_bytes": (path / "result.json").stat().st_size if (path / "result.json").is_file() else 0,
    }


def inspect_job(
    job_id: str,
    *,
    data_root: Path | None = None,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    clean_id = str(job_id or "").strip()
    if not re.fullmatch(r"job-[0-9a-f]{32}", clean_id):
        raise RecoveryRescueProbeError("job id must be job- followed by 32 lowercase hexadecimal characters")

    root = (data_root or data_dir()).expanduser().resolve()
    job_path = root / "ui-jobs" / clean_id / "job.json"
    job = _read_json(job_path)
    if job is None or job.get("format") != "bodyrig-ui-job" or job.get("kind") != "body-build":
        raise RecoveryRescueProbeError(f"BodyRig body-build job not found or invalid: {clean_id}")

    person_id = str(job.get("person_id") or "").strip()
    started = _parse_utc(job.get("started_utc"))
    completed = _parse_utc(job.get("completed_utc"))

    workspace_rows: list[dict[str, Any]] = []
    observation_root = root / "observation-workspaces"
    if observation_root.is_dir() and person_id:
        try:
            candidates = sorted(observation_root.glob(f"{person_id}-*"))
        except OSError:
            candidates = []
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            stamp = _workspace_timestamp(candidate)
            if started is not None and stamp is not None and stamp < started - timedelta(minutes=15):
                continue
            if completed is not None and stamp is not None and stamp > completed + timedelta(minutes=15):
                continue
            value = _checkpoint_workspace(candidate)
            if value is not None:
                workspace_rows.append(value)

    temp = (temp_root or Path(tempfile.gettempdir())).expanduser().resolve()
    staging_rows: list[dict[str, Any]] = []
    if temp.is_dir():
        try:
            staging_dirs = sorted(temp.glob("bodyrig-wsl-recovery-*"))
        except OSError:
            staging_dirs = []
        for candidate in staging_dirs:
            if not candidate.is_dir():
                continue
            value = _staging_candidate(candidate, started=started, completed=completed)
            if value is not None:
                staging_rows.append(value)

    log_path = Path(str(job.get("log_path") or "")).expanduser()
    if not log_path.is_absolute():
        log_path = job_path.parent / log_path
    log_tail = _tail_text(log_path)
    reusable = sum(int(row["reusable_raw_checkpoints"]) for row in workspace_rows)

    return {
        "format": FORMAT,
        "version": VERSION,
        "job_id": clean_id,
        "job_status": str(job.get("status") or ""),
        "bodyrig_revision": str(job.get("bodyrig_revision") or ""),
        "person_id": person_id,
        "terminal_error": str(job.get("error") or "") or None,
        "reusable_raw_checkpoints": reusable,
        "checkpoint_workspaces": workspace_rows,
        "wsl_staging_candidates": staging_rows,
        "job_log_tail": log_tail,
        "legacy_recovery_survived": bool(reusable or staging_rows),
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect retained BodyRig recovery evidence without mutating it.")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_job(args.job_id)
    except RecoveryRescueProbeError as exc:
        print(f"BodyRig recovery rescue probe: {exc}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
