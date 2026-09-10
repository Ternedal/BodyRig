from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_stash_inventory import (
    PhotoIdentityStashInventoryError,
    fetch_exhaustive_performer_scenes,
)
from .stash_cli import _remap_scene_paths
from .stash_source import (
    StashClient,
    StashConfig,
    VIDEO_SUFFIXES,
    _number,
    _projection_safe_source,
)

FORMAT = "bodyrig-photoidentity-source-universe"
VERSION = 1


class PhotoIdentitySourceUniverseError(RuntimeError):
    pass


def _file_token(path: str) -> str:
    # Private/local paths must not leak into public evidence. The token is only
    # for duplicate counting inside one receipt and is not a portable identity.
    return hashlib.sha256(os.path.normcase(path).encode("utf-8", errors="surrogatepass")).hexdigest()


def audit_source_universe(
    *,
    performer_id: str,
    stash_url: str,
    stash_api_key: str,
    maximum_scenes: int = 10_000,
    page_size: int = 250,
) -> dict[str, Any]:
    client = StashClient(StashConfig(url=stash_url, api_key=stash_api_key, timeout_seconds=20))
    performer = client.performer(performer_id)
    if str(performer.get("id") or "") != str(performer_id):
        raise PhotoIdentitySourceUniverseError("live Stash performer identity changed during source-universe audit")

    inventory = fetch_exhaustive_performer_scenes(
        client,
        performer_id,
        page_size=page_size,
        maximum_scenes=maximum_scenes,
    )
    scenes = _remap_scene_paths(list(inventory.scenes), stash_url=client.config.url)

    single_scene_count = 0
    multi_scene_count = 0
    single_safe_local_files: set[str] = set()
    single_missing_local_files: set[str] = set()
    single_projection_unsafe_files: set[str] = set()
    multi_local_video_files: set[str] = set()

    for scene in scenes:
        performers = scene.get("performers") or []
        performer_ids = {
            str(item.get("id"))
            for item in performers
            if isinstance(item, Mapping) and item.get("id") is not None
        }
        if str(performer_id) not in performer_ids:
            raise PhotoIdentitySourceUniverseError("exhaustive inventory scene lost target performer binding")
        single = len(performer_ids) == 1
        if single:
            single_scene_count += 1
        else:
            multi_scene_count += 1

        tags = [
            str(item.get("name") or "")
            for item in (scene.get("tags") or [])
            if isinstance(item, Mapping)
        ]
        for raw_file in scene.get("files") or []:
            if not isinstance(raw_file, Mapping):
                continue
            raw_path = str(raw_file.get("path") or "").strip()
            if not raw_path or Path(raw_path).suffix.lower() not in VIDEO_SUFFIXES:
                continue
            token = _file_token(raw_path)
            is_local = Path(raw_path).expanduser().is_file()
            width = int(_number(raw_file.get("width")))
            height = int(_number(raw_file.get("height")))
            projection_safe = _projection_safe_source(width=width, height=height, tags=tags)

            if not single:
                if is_local and projection_safe:
                    multi_local_video_files.add(token)
                continue
            if not projection_safe:
                single_projection_unsafe_files.add(token)
            elif not is_local:
                single_missing_local_files.add(token)
            else:
                single_safe_local_files.add(token)

    unresolved_multi = multi_scene_count > 0
    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": str(performer_id),
        "stash_scene_count": inventory.total_count,
        "inventory_page_count": inventory.page_count,
        "inventory_page_size": inventory.page_size,
        "inventory_schema": inventory.schema,
        "stash_inventory_exhausted": True,
        "single_performer_scene_count": single_scene_count,
        "multi_performer_scene_count": multi_scene_count,
        "single_performer_projection_safe_local_video_count": len(single_safe_local_files),
        "single_performer_missing_local_video_count": len(single_missing_local_files),
        "single_performer_projection_unsafe_video_count": len(single_projection_unsafe_files),
        "multi_performer_projection_safe_local_video_count": len(multi_local_video_files),
        "single_performer_source_universe_observable": len(single_safe_local_files) > 0,
        "multi_performer_identity_resolution_required": unresolved_multi,
        "performer_media_fully_identity_resolved": not unresolved_multi,
        "source_paths_persisted": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the complete Stash scene universe for one performer without granting reconstruction authority."
    )
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--stash-url", required=True)
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--maximum-scenes", type=int, default=10_000)
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    try:
        api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        result = audit_source_universe(
            performer_id=args.performer_id,
            stash_url=args.stash_url,
            stash_api_key=api_key,
            maximum_scenes=args.maximum_scenes,
            page_size=args.page_size,
        )
        text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out:
            output = Path(args.out).expanduser().resolve()
            if output.exists():
                raise PhotoIdentitySourceUniverseError(f"source-universe receipt already exists: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8", newline="\n")
            print(output)
        else:
            print(text, end="")
        return 0
    except (OSError, ValueError, PhotoIdentityStashInventoryError, PhotoIdentitySourceUniverseError) as exc:
        print(f"BodyRig photoidentity source universe: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
