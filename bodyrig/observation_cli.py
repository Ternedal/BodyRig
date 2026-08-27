from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .observation import (
    ObservationError,
    build_selection_manifest,
    load_stash_source_manifest,
    materialize_segments,
    select_observations,
)
from .observation_runner import run_external_analyzer

CONFIG_FORMAT = "bodyrig-observation-analyzer-config"
CONFIG_VERSION = 1


def _load_config(path: str | Path) -> dict:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ObservationError(f"observation analyzer config not found: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError("observation analyzer config is invalid JSON") from exc
    if not isinstance(config, dict) or set(config) != {
        "format",
        "version",
        "adapter",
        "revision",
        "command",
        "timeout_seconds",
    }:
        raise ObservationError("observation analyzer config fields must match v1 exactly")
    if config["format"] != CONFIG_FORMAT or config["version"] != CONFIG_VERSION:
        raise ObservationError("unsupported observation analyzer config format/version")
    command = config["command"]
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise ObservationError("observation analyzer config command must be a non-empty argv list")
    timeout = config["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise ObservationError("observation analyzer timeout_seconds must be in 1..86400")
    return config


def _write_json_create_only(path: str | Path, value: dict) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise ObservationError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze ranked Stash sources and materialize the best private BodyRig observation segments."
    )
    parser.add_argument("source_manifest", help="bodyrig-stash-source-manifest.json")
    parser.add_argument("--config", required=True, help="strict external observation analyzer config")
    parser.add_argument("--workspace", required=True, help="new private workspace root")
    parser.add_argument("--selection-out", required=True, help="create-only observation selection JSON")
    parser.add_argument("--segments-out", required=True, help="create-only segment manifest JSON outside private workspace")
    parser.add_argument("--max-segments", type=int, default=10)
    parser.add_argument("--max-per-source", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=0.35)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).expanduser().resolve()
    if workspace.exists():
        print(f"BodyRig observation selection: workspace already exists: {workspace}", file=sys.stderr)
        return 1

    try:
        source_manifest, sources, source_sha = load_stash_source_manifest(args.source_manifest)
        performer = source_manifest.get("performer") or {}
        performer_id = str(performer.get("id") or "").strip()
        if not performer_id:
            raise ObservationError("Stash source manifest performer id is missing")
        config = _load_config(args.config)
        workspace.mkdir(parents=True)
        observations = run_external_analyzer(
            config["command"],
            sources=sources,
            performer_id=performer_id,
            source_manifest_sha256=source_sha,
            workspace=workspace,
            adapter=config["adapter"],
            revision=config["revision"],
            timeout_seconds=config["timeout_seconds"],
        )
        selected = select_observations(
            observations,
            max_segments=args.max_segments,
            min_base_score=args.min_score,
            max_per_source=args.max_per_source,
        )
        selection = build_selection_manifest(
            source_manifest_sha256=source_sha,
            adapter=config["adapter"],
            revision=config["revision"],
            sources=sources,
            selected=selected,
        )
        _write_json_create_only(args.selection_out, selection)
        segment_workspace = workspace / "selected-segments"
        segments = materialize_segments(
            sources=sources,
            selection_manifest=selection,
            workspace=segment_workspace,
            ffmpeg=args.ffmpeg,
        )
        _write_json_create_only(args.segments_out, segments)
    except (OSError, ObservationError) as exc:
        print(f"BodyRig observation selection: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        f"BodyRig observation selection: PASS | {len(selected)} segments | "
        f"views={','.join(sorted({item.view for item in selected}))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
