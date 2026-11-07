"""Read the non-authoritative stage wall-clock sidecar of a physical clone session.

The ready launcher (`clone-body-from-stash-ready.ps1`) points
``BODYRIG_STAGE_TIMING_LOG`` at ``<session>.timing.jsonl`` next to the
session report, and every ``Invoke-Checked`` stage in the clone scripts
appends one JSON line::

    {"format": "bodyrig-stage-timing", "version": 1, "script": "clone-body.ps1",
     "stage": "Video recovery", "started_utc": "...Z", "finished_utc": "...Z",
     "duration_seconds": 12345.678, "outcome": "pass"}

Nothing reads this file to decide anything: it is not evidence, no gate
validates it, and the session report keeps its exact v1 field set. It exists
so that the next performance question ("where did the seven days go?") can
be answered from a measurement instead of a guess. Malformed lines are
counted and skipped rather than failing the summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

FORMAT = "bodyrig-stage-timing"
VERSION = 1
ENVIRONMENT_VARIABLE = "BODYRIG_STAGE_TIMING_LOG"
RECORD_FIELDS = {"format", "version", "script", "stage", "started_utc", "finished_utc", "duration_seconds", "outcome"}
OUTCOMES = {"pass", "fail"}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def parse_record(line: str) -> dict[str, Any] | None:
    """Return a normalised record for one sidecar line, or None if it is unusable."""
    text = line.strip().lstrip("﻿")
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not RECORD_FIELDS.issubset(value):
        return None
    version = value["version"]
    outcome = value["outcome"]
    if value["format"] != FORMAT or isinstance(version, bool) or version != VERSION:
        return None
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        return None
    started = _parse_timestamp(value["started_utc"])
    finished = _parse_timestamp(value["finished_utc"])
    duration = value["duration_seconds"]
    if started is None or finished is None or isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    if not isinstance(value["script"], str) or not isinstance(value["stage"], str) or not value["stage"].strip():
        return None
    return {
        "script": value["script"],
        "stage": value["stage"].strip(),
        "started_utc": started,
        "finished_utc": finished,
        "duration_seconds": float(duration),
        "outcome": value["outcome"],
    }


def _wraps(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    """True when `outer` spans `inner` and `inner` lies at least partly strictly inside it."""
    if outer["started_utc"] > inner["started_utc"] or outer["finished_utc"] < inner["finished_utc"]:
        return False
    if (outer["started_utc"], outer["finished_utc"]) == (inner["started_utc"], inner["finished_utc"]):
        return False
    # `inner` must start before `outer` finishes and finish after `outer`
    # starts; a zero-length row sitting exactly on a boundary fails both.
    return inner["started_utc"] < outer["finished_utc"] and inner["finished_utc"] > outer["started_utc"]


def read_stage_timing(path: str | Path) -> dict[str, Any]:
    """Summarise a sidecar: ordered stage rows, totals and the count of skipped lines."""
    sidecar = Path(path).expanduser()
    if not sidecar.is_file():
        raise FileNotFoundError(f"stage timing sidecar not found: {sidecar}")
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in sidecar.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        record = parse_record(line)
        if record is None:
            skipped += 1
            continue
        rows.append(record)
    rows.sort(key=lambda row: (row["started_utc"], row["finished_utc"]))
    # The launcher wraps the whole clone pipeline, and the pipeline wraps its
    # own stages, so the sum of all rows double counts. The leaf total skips
    # every wrapper and adds up only the innermost stages. A wrapper is a row
    # whose span contains another row's span with at least one strictly
    # interior point: a short stage that merely touches a neighbour's start
    # or finish instant (timestamps are recorded at finite precision) does
    # not make that neighbour a wrapper.
    leaf_total = 0.0
    for row in rows:
        is_wrapper = any(_wraps(row, other) for other in rows if other is not row)
        if not is_wrapper:
            leaf_total += row["duration_seconds"]
    return {
        "path": str(sidecar),
        "stages": rows,
        "stage_count": len(rows),
        "skipped_lines": skipped,
        "failed_stages": [row["stage"] for row in rows if row["outcome"] == "fail"],
        "wall_clock_seconds": leaf_total,
        "started_utc": rows[0]["started_utc"] if rows else None,
        "finished_utc": max(row["finished_utc"] for row in rows) if rows else None,
    }


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{seconds:.1f}s"


def render_table(summary: dict[str, Any]) -> str:
    lines = [f"Stage timing: {summary['path']}"]
    if not summary["stages"]:
        lines.append("(no stage records)")
    else:
        width = max(len(row["stage"]) for row in summary["stages"])
        for row in summary["stages"]:
            lines.append(
                f"{row['started_utc'].strftime('%Y-%m-%d %H:%M:%S')}  "
                f"{row['stage']:<{width}}  {format_duration(row['duration_seconds']):>12}  "
                f"{row['outcome']:<4}  {row['script']}"
            )
        lines.append(f"Wall clock (leaf stages): {format_duration(summary['wall_clock_seconds'])}")
    if summary["failed_stages"]:
        lines.append("Failed stages: " + ", ".join(summary["failed_stages"]))
    if summary["skipped_lines"]:
        lines.append(f"Skipped unreadable lines: {summary['skipped_lines']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise a BodyRig stage timing sidecar (informational, not evidence).")
    parser.add_argument("sidecar", help="path to <session>.timing.jsonl")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON instead of a table")
    args = parser.parse_args(argv)
    try:
        summary = read_stage_timing(args.sidecar)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        serialisable = dict(summary)
        serialisable["stages"] = [
            {
                **row,
                "started_utc": row["started_utc"].isoformat().replace("+00:00", "Z"),
                "finished_utc": row["finished_utc"].isoformat().replace("+00:00", "Z"),
            }
            for row in summary["stages"]
        ]
        for key in ("started_utc", "finished_utc"):
            if serialisable[key] is not None:
                serialisable[key] = serialisable[key].isoformat().replace("+00:00", "Z")
        print(json.dumps(serialisable, indent=2, ensure_ascii=False))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
