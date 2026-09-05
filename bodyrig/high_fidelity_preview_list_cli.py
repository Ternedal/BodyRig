from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-preview-job"
VERSION = 1
ROOT_DIRNAME = ".high-fidelity-previews"


class HighFidelityPreviewListError(RuntimeError):
    pass


def list_recent_previews(*, limit: int = 10, succeeded_only: bool = False) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise HighFidelityPreviewListError("limit must be between 1 and 100")
    root = ui_jobs_dir() / ROOT_DIRNAME
    if not root.exists():
        return []
    if not root.is_dir():
        raise HighFidelityPreviewListError(f"high-fidelity preview store is not a directory: {root}")

    rows: list[dict[str, Any]] = []
    for path in root.glob("*/job.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("version") != VERSION:
            continue
        job_id = str(value.get("job_id") or "")
        if path.parent.name != job_id or not job_id.startswith("hfpreview-"):
            continue
        status = str(value.get("status") or "")
        if succeeded_only and status != "succeeded":
            continue
        rows.append(
            {
                "job_id": job_id,
                "display_name": str(value.get("display_name") or ""),
                "person_id": str(value.get("person_id") or ""),
                "body_revision": str(value.get("body_revision") or ""),
                "canonical_body_id": str(value.get("canonical_body_id") or ""),
                "target_family": str(value.get("target_family") or ""),
                "status": status,
                "stage": str(value.get("stage") or ""),
                "bodyrig_revision": str(value.get("bodyrig_revision") or ""),
                "created_utc": str(value.get("created_utc") or ""),
                "completed_utc": value.get("completed_utc"),
            }
        )
    rows.sort(key=lambda row: row["created_utc"], reverse=True)
    return rows[:limit]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List persisted BodyRig high-fidelity preview jobs without mutating them")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--succeeded-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        rows = list_recent_previews(limit=args.limit, succeeded_only=args.succeeded_only)
    except HighFidelityPreviewListError as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig high-fidelity previews: ERROR | {exc}")
        return 2

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
        return 0
    if not rows:
        print("No persisted high-fidelity preview jobs found.")
        return 0
    print("Recent high-fidelity preview jobs:")
    for row in rows:
        print(
            f"{row['job_id']} | {row['status']}/{row['stage']} | "
            f"{row['display_name'] or row['person_id']} | {row['body_revision']} | {row['target_family']} | {row['created_utc']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
