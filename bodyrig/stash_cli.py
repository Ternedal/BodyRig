from __future__ import annotations

import argparse
import json
import os
import sys

from .stash_source import (
    StashClient,
    StashConfig,
    StashSourceError,
    build_source_manifest,
    rank_sources,
    write_source_manifest,
)


_HEALTH_PROBE_TERM = "__bodyrig_auth_capability_probe__"


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

    select = sub.add_parser("select", help="Select ranked local video sources for one performer")
    select.add_argument("--performer-id", required=True)
    select.add_argument("--scene-limit", type=int, default=200)
    select.add_argument("--max-sources", type=int, default=10)
    select.add_argument("--out", required=True, help="New build-only source manifest JSON")
    select.add_argument(
        "--paths-only",
        action="store_true",
        help="Print selected local paths one per line after writing the manifest",
    )
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

        performer = client.performer(args.performer_id)
        scenes = client.scenes_for_performer(args.performer_id, limit=args.scene_limit)
        selected = rank_sources(
            scenes,
            performer_id=args.performer_id,
            max_sources=args.max_sources,
            require_local=True,
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
