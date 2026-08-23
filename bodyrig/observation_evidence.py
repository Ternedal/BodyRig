from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class ObservationEvidenceError(ValueError):
    pass


def _load(path: str | Path, *, label: str) -> tuple[Path, bytes, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ObservationEvidenceError(f"{label} not found: {resolved}")
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ObservationEvidenceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ObservationEvidenceError(f"{label} must be an object")
    return resolved, raw, value


def build_observation_evidence(
    *,
    source_manifest_path: str | Path,
    selection_path: str | Path,
    segments_path: str | Path,
) -> dict[str, Any]:
    _, source_raw, source = _load(source_manifest_path, label="Stash source manifest")
    _, selection_raw, selection = _load(selection_path, label="observation selection")
    _, segments_raw, segments = _load(segments_path, label="observation segment manifest")

    source_sha = hashlib.sha256(source_raw).hexdigest()
    selection_sha = hashlib.sha256(selection_raw).hexdigest()
    segments_sha = hashlib.sha256(segments_raw).hexdigest()

    if source.get("format") != "bodyrig-stash-source-manifest" or source.get("version") != 1:
        raise ObservationEvidenceError("unsupported Stash source manifest")
    if selection.get("format") != "bodyrig-observation-selection" or selection.get("version") != 1:
        raise ObservationEvidenceError("unsupported observation selection")
    if segments.get("format") != "bodyrig-observation-segments" or segments.get("version") != 1:
        raise ObservationEvidenceError("unsupported observation segment manifest")
    if selection.get("source_manifest_sha256") != source_sha:
        raise ObservationEvidenceError("observation selection is not bound to this source manifest")

    selected = selection.get("selected")
    segment_rows = segments.get("segments")
    if not isinstance(selected, list) or not isinstance(segment_rows, list) or len(selected) != len(segment_rows):
        raise ObservationEvidenceError("selection/segment cardinality mismatch")
    if not 1 <= len(segment_rows) <= 10:
        raise ObservationEvidenceError("observation evidence requires 1..10 segments")

    selected_by_key = {}
    for item in selected:
        if not isinstance(item, dict):
            raise ObservationEvidenceError("selection row is invalid")
        key = (str(item.get("source_id") or ""), str(item.get("scene_id") or ""), float(item.get("start_seconds") or 0), float(item.get("duration_seconds") or 0))
        if not key[0] or not key[1] or key in selected_by_key:
            raise ObservationEvidenceError("selection row identity is invalid or duplicated")
        selected_by_key[key] = item

    redacted_segments: list[dict[str, Any]] = []
    for item in segment_rows:
        if not isinstance(item, dict):
            raise ObservationEvidenceError("segment row is invalid")
        try:
            key = (
                str(item["source_id"]),
                str(item["scene_id"]),
                float(item["start_seconds"]),
                float(item["duration_seconds"]),
            )
            digest = str(item["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationEvidenceError("segment row fields are invalid") from exc
        if key not in selected_by_key:
            raise ObservationEvidenceError("segment row is not represented by the observation selection")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ObservationEvidenceError("segment SHA-256 is invalid")
        path_value = str(item.get("path") or "")
        if not path_value:
            raise ObservationEvidenceError("segment path is missing")
        path = Path(path_value).expanduser().resolve()
        if not path.is_file():
            raise ObservationEvidenceError(f"segment file not found: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ObservationEvidenceError("segment byte hash does not match segment manifest")
        redacted_segments.append(
            {
                "source_id": key[0],
                "scene_id": key[1],
                "start_seconds": key[2],
                "duration_seconds": key[3],
                "sha256": digest,
            }
        )

    return {
        "format": "bodyrig-observation-evidence",
        "version": 1,
        "source_manifest_sha256": source_sha,
        "selection_sha256": selection_sha,
        "segments_manifest_sha256": segments_sha,
        "adapter": str(selection.get("adapter") or ""),
        "revision": str(selection.get("revision") or ""),
        "segments": redacted_segments,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create path-free BodyRig observation evidence from a private segment build.")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    output = Path(args.out).expanduser().resolve()
    if output.exists():
        print(f"BodyRig observation evidence: FAIL: output already exists: {output}", file=sys.stderr)
        return 1
    try:
        evidence = build_observation_evidence(
            source_manifest_path=args.source_manifest,
            selection_path=args.selection,
            segments_path=args.segments,
        )
    except (OSError, ObservationEvidenceError) as exc:
        print(f"BodyRig observation evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"BodyRig observation evidence: PASS | {len(evidence['segments'])} path-free segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
