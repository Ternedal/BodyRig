from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .stash_source import (
    SourceCandidate,
    StashClient,
    StashConfig,
    StashSourceError,
    build_source_manifest,
    rank_sources,
    write_source_manifest,
)


_HEALTH_PROBE_TERM = "__bodyrig_auth_capability_probe__"
_DECODE_GATE = "ffmpeg-one-frame-v1"
_PATH_MAP_ENV = "BODYRIG_STASH_PATH_MAP"


def _config(args: argparse.Namespace) -> StashConfig:
    url = (args.url or os.environ.get("STASH_URL") or "").strip()
    if not url:
        raise StashSourceError("Stash URL is required via --url or STASH_URL")
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    return StashConfig(url=url, api_key=api_key, timeout_seconds=args.timeout)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default="", help="Stash base URL; defaults to STASH_URL")
    parser.add_argument(
        "--api-key-env",
        default="STASH_API_KEY",
        help="Environment variable containing Stash API key; default STASH_API_KEY",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds (1..120)")


def _add_decode_probe(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="FFmpeg executable used for a one-frame decode probe; default ffmpeg",
    )
    parser.add_argument(
        "--decode-timeout",
        type=int,
        default=20,
        help="Per-source one-frame decode timeout seconds (1..120); default 20",
    )


def _path_map_rules() -> list[tuple[str, str]]:
    raw = os.environ.get(_PATH_MAP_ENV, "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StashSourceError(
            f"{_PATH_MAP_ENV} must be a JSON object mapping Stash path prefixes to local path prefixes"
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise StashSourceError(f"{_PATH_MAP_ENV} must be a non-empty JSON object when set")

    rules: list[tuple[str, str]] = []
    for source, target in parsed.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise StashSourceError(f"{_PATH_MAP_ENV} keys and values must be strings")
        source = source.strip().replace("/", "\\").rstrip("\\")
        target = target.strip().rstrip("\\/")
        if not source or not target:
            raise StashSourceError(f"{_PATH_MAP_ENV} may not contain empty path prefixes")
        rules.append((source, target))

    rules.sort(key=lambda pair: len(pair[0]), reverse=True)
    return rules


def _remap_source_path(raw_path: str, rules: Sequence[tuple[str, str]]) -> str:
    normalized = raw_path.replace("/", "\\")
    folded = normalized.casefold()
    for source, target in rules:
        source_folded = source.casefold()
        if folded == source_folded:
            return target
        prefix = source_folded + "\\"
        if folded.startswith(prefix):
            remainder = normalized[len(source) :].lstrip("\\")
            parts = [part for part in remainder.split("\\") if part]
            return os.path.join(target, *parts)
    return raw_path


def _remap_scene_paths(scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rules = _path_map_rules()
    if not rules:
        return [dict(scene) for scene in scenes]

    mapped_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        mapped_scene = dict(scene)
        mapped_files: list[Any] = []
        for item in scene.get("files") or []:
            if not isinstance(item, Mapping):
                mapped_files.append(item)
                continue
            mapped_file = dict(item)
            raw_path = str(item.get("path") or "")
            if raw_path:
                mapped_file["path"] = _remap_source_path(raw_path, rules)
            mapped_files.append(mapped_file)
        mapped_scene["files"] = mapped_files
        mapped_scenes.append(mapped_scene)
    return mapped_scenes


def _filter_decodable_sources(
    candidates: Sequence[SourceCandidate],
    *,
    ffmpeg: str,
    timeout_seconds: int,
) -> list[SourceCandidate]:
    if not isinstance(ffmpeg, str) or not ffmpeg.strip():
        raise StashSourceError("FFmpeg executable is required for source decode probe")
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 120:
        raise StashSourceError("decode timeout must be in 1..120 seconds")

    decodable: list[SourceCandidate] = []
    for candidate in candidates:
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            candidate.path,
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                check=False,
                timeout=timeout_seconds,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise StashSourceError("FFmpeg source decode probe could not start") from exc
        except subprocess.TimeoutExpired:
            # A hung/problematic media file is not suitable for the first physical run.
            continue
        if completed.returncode == 0:
            decodable.append(candidate)
    return decodable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Use local Stash performers/scenes as BodyRig clone sources.")
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser(
        "health",
        help="Probe Stash GraphQL plus performer-read capability without selecting or reading media",
    )
    _add_common(health)

    search = sub.add_parser("search", help="Search Stash performers")
    search.add_argument("term")
    search.add_argument("--limit", type=int, default=25)
    _add_common(search)

    probe = sub.add_parser(
        "probe",
        help="Verify one performer resolves and has locally decodable video sources without writing a source manifest",
    )
    probe.add_argument("--performer-id", required=True)
    probe.add_argument("--scene-limit", type=int, default=200)
    probe.add_argument("--max-sources", type=int, default=10)
    _add_decode_probe(probe)
    _add_common(probe)

    select = sub.add_parser("select", help="Select ranked, locally decodable video sources for one performer")
    select.add_argument("--performer-id", required=True)
    select.add_argument("--scene-limit", type=int, default=200)
    select.add_argument("--max-sources", type=int, default=10)
    select.add_argument("--out", required=True, help="New build-only source manifest JSON")
    select.add_argument(
        "--paths-only",
        action="store_true",
        help="Print selected local paths one per line after writing the manifest",
    )
    select.add_argument(
        "--skip-decode-probe",
        action="store_true",
        help="Diagnostics only: skip the one-frame FFmpeg decode gate before writing the source manifest",
    )
    _add_decode_probe(select)
    _add_common(select)

    args = parser.parse_args(argv)
    try:
        client = StashClient(_config(args))
        if args.command == "health":
            version = client.version()
            # Prove the same read capability used by the next operator step. The
            # deliberately unlikely term keeps the probe metadata-only and its
            # result is discarded; success itself is the capability evidence.
            client.search_performers(_HEALTH_PROBE_TERM, limit=1)
            print(
                json.dumps(
                    {"ok": True, "version": version, "performer_read": True},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "search":
            performers = client.search_performers(args.term, limit=args.limit)
            print(json.dumps(performers, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        if args.command == "probe":
            performer = client.performer(args.performer_id)
            scenes = _remap_scene_paths(client.scenes_for_performer(args.performer_id, limit=args.scene_limit))
            ranked = rank_sources(
                scenes,
                performer_id=args.performer_id,
                max_sources=args.max_sources,
                require_local=True,
            )
            if not ranked:
                raise StashSourceError(
                    f"performer {args.performer_id!r} has no rankable local video sources"
                )
            selected = _filter_decodable_sources(
                ranked,
                ffmpeg=args.ffmpeg,
                timeout_seconds=args.decode_timeout,
            )
            if not selected:
                raise StashSourceError(
                    f"performer {args.performer_id!r} has no locally decodable video sources"
                )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "version": client.version(),
                        "performer": {
                            "id": str(performer.get("id") or ""),
                            "name": str(performer.get("name") or ""),
                            "disambiguation": str(performer.get("disambiguation") or ""),
                        },
                        "candidate_count": len(scenes),
                        "rankable_source_count": len(ranked),
                        "usable_source_count": len(selected),
                        "decode_gate": _DECODE_GATE,
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            return 0

        performer = client.performer(args.performer_id)
        scenes = _remap_scene_paths(client.scenes_for_performer(args.performer_id, limit=args.scene_limit))
        selected = rank_sources(
            scenes,
            performer_id=args.performer_id,
            max_sources=args.max_sources,
            require_local=True,
        )
        if not selected:
            raise StashSourceError(
                f"performer {args.performer_id!r} has no rankable local video sources"
            )
        if not args.skip_decode_probe:
            selected = _filter_decodable_sources(
                selected,
                ffmpeg=args.ffmpeg,
                timeout_seconds=args.decode_timeout,
            )
            if not selected:
                raise StashSourceError(
                    f"performer {args.performer_id!r} has no locally decodable video sources"
                )
        manifest = build_source_manifest(
            performer=performer,
            candidates=selected,
            stash_version=client.version(),
            candidate_count=len(scenes),
        )
        output = write_source_manifest(args.out, manifest)
        if args.paths_only:
            for item in selected:
                print(item.path)
        else:
            print(output)
        return 0
    except StashSourceError as exc:
        print(f"BodyRig Stash source: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())