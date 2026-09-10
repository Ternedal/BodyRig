from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_stash_inventory import (
    PhotoIdentityStashInventoryError,
    fetch_exhaustive_performer_scenes,
)
from .stash_cli import _remap_scene_paths
from .stash_source import (
    SourceCandidate,
    StashClient,
    StashConfig,
    VIDEO_SUFFIXES,
    _number,
    _projection_safe_source,
    _score_candidate,
)

FORMAT = "bodyrig-photoidentity-multiperformer-source-discovery"
VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoidentity-private-multiperformer-source-index"
PRIVATE_VERSION = 1


class PhotoIdentityMultiSourceDiscoveryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_revision(value: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityMultiSourceDiscoveryError("multi-performer discovery requires exact BodyRig Git revision")
    return revision


def _candidate_id(*, scene_id: str, path: str) -> str:
    authority = f"{scene_id}\0{os.path.normcase(path)}".encode("utf-8", errors="surrogatepass")
    return "multicand-" + hashlib.sha256(authority).hexdigest()[:32]


def _rank_candidates(
    scenes: list[dict[str, Any]],
    *,
    performer_id: str,
) -> list[tuple[SourceCandidate, tuple[str, ...]]]:
    by_path: dict[str, tuple[SourceCandidate, tuple[str, ...]]] = {}
    for scene in scenes:
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            continue
        performers = scene.get("performers") or []
        performer_ids = tuple(
            sorted(
                {
                    str(item.get("id"))
                    for item in performers
                    if isinstance(item, Mapping) and item.get("id") is not None
                }
            )
        )
        if performer_id not in performer_ids:
            raise PhotoIdentityMultiSourceDiscoveryError("inventory scene lost target performer binding")
        if len(performer_ids) <= 1:
            continue
        tags = [
            str(item.get("name") or "")
            for item in (scene.get("tags") or [])
            if isinstance(item, Mapping)
        ]
        title = str(scene.get("title") or f"Scene {scene_id}")
        for raw_file in scene.get("files") or []:
            if not isinstance(raw_file, Mapping):
                continue
            raw_path = str(raw_file.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if path.suffix.lower() not in VIDEO_SUFFIXES or not path.is_file():
                continue
            try:
                normalized = str(path.resolve(strict=True))
            except OSError:
                continue
            width = int(_number(raw_file.get("width")))
            height = int(_number(raw_file.get("height")))
            if not _projection_safe_source(width=width, height=height, tags=tags):
                continue
            duration = _number(raw_file.get("duration"))
            framerate = _number(raw_file.get("frame_rate"))
            candidate = SourceCandidate(
                scene_id=scene_id,
                scene_title=title,
                path=normalized,
                width=width,
                height=height,
                duration=duration,
                framerate=framerate,
                performer_count=len(performer_ids),
                score=_score_candidate(
                    width=width,
                    height=height,
                    duration=duration,
                    framerate=framerate,
                    performer_count=len(performer_ids),
                    tags=tags,
                ),
            )
            key = os.path.normcase(normalized)
            previous = by_path.get(key)
            if previous is None or candidate.score > previous[0].score:
                by_path[key] = (candidate, performer_ids)
    return sorted(
        by_path.values(),
        key=lambda item: (-item[0].score, -item[0].height, -item[0].width, item[0].scene_id, item[0].path.lower()),
    )


def discover_multiperformer_sources(
    *,
    performer_id: str,
    stash_url: str,
    stash_api_key: str,
    bodyrig_revision: str,
    output_dir: Path,
    maximum_scenes: int = 10_000,
    page_size: int = 250,
) -> dict[str, Any]:
    revision = _canonical_revision(bodyrig_revision)
    performer_id = str(performer_id or "").strip()
    if not performer_id or len(performer_id) > 256:
        raise PhotoIdentityMultiSourceDiscoveryError("performer id is invalid")
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise PhotoIdentityMultiSourceDiscoveryError(f"multi-performer discovery output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    client = StashClient(StashConfig(url=stash_url, api_key=stash_api_key, timeout_seconds=20))
    performer = client.performer(performer_id)
    if str(performer.get("id") or "") != performer_id:
        raise PhotoIdentityMultiSourceDiscoveryError("live Stash performer identity changed during discovery")
    inventory = fetch_exhaustive_performer_scenes(
        client,
        performer_id,
        page_size=page_size,
        maximum_scenes=maximum_scenes,
    )
    scenes = _remap_scene_paths(list(inventory.scenes), stash_url=client.config.url)
    ranked = _rank_candidates(scenes, performer_id=performer_id)

    public_candidates: list[dict[str, Any]] = []
    private_candidates: list[dict[str, Any]] = []
    ids: set[str] = set()
    for candidate, performer_ids in ranked:
        candidate_id = _candidate_id(scene_id=candidate.scene_id, path=candidate.path)
        if candidate_id in ids:
            raise PhotoIdentityMultiSourceDiscoveryError("multi-performer candidate id collision")
        ids.add(candidate_id)
        public_candidates.append(
            {
                "candidate_id": candidate_id,
                "scene_id": candidate.scene_id,
                "performer_count": candidate.performer_count,
                "width": candidate.width,
                "height": candidate.height,
                "duration": round(candidate.duration, 3),
                "framerate": round(candidate.framerate, 3),
                "review_priority_score": round(candidate.score, 3),
            }
        )
        private_candidates.append(
            {
                "candidate_id": candidate_id,
                "scene_id": candidate.scene_id,
                "source_path": candidate.path,
                "performer_ids": list(performer_ids),
            }
        )

    public = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "stash_scene_count": inventory.total_count,
        "inventory_page_count": inventory.page_count,
        "inventory_page_size": inventory.page_size,
        "inventory_schema": inventory.schema,
        "stash_inventory_exhausted": True,
        "candidate_count": len(public_candidates),
        "candidates": public_candidates,
        "source_paths_persisted": False,
        "source_media_hashed_at_discovery": False,
        "target_track_selected": False,
        "human_identity_attestation_required": bool(public_candidates),
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    try:
        public_path = stage / "multiperformer-source-candidates.json"
        public_path.write_text(
            json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        private_root = stage / "private-multiperformer-source-candidates"
        private_root.mkdir()
        private = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": revision,
            "performer_id": performer_id,
            "public_manifest_sha256": _sha256_file(public_path),
            "candidate_count": len(private_candidates),
            "candidates": private_candidates,
            "source_paths_private": True,
            "target_track_selected": False,
            "production_activation": False,
        }
        private_path = private_root / "private-candidate-index.json"
        private_path.write_text(
            json.dumps(private, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        **public,
        "public_manifest": str(output_dir / "multiperformer-source-candidates.json"),
        "private_index": str(output_dir / "private-multiperformer-source-candidates" / "private-candidate-index.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover projection-safe local multi-performer Stash sources without choosing target identity.")
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--stash-url", required=True)
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--maximum-scenes", type=int, default=10_000)
    parser.add_argument("--page-size", type=int, default=250)
    args = parser.parse_args(argv)
    try:
        api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        result = discover_multiperformer_sources(
            performer_id=args.performer_id,
            stash_url=args.stash_url,
            stash_api_key=api_key,
            bodyrig_revision=args.bodyrig_revision,
            output_dir=Path(args.output_dir),
            maximum_scenes=args.maximum_scenes,
            page_size=args.page_size,
        )
        print(result["public_manifest"])
        print(f"Multi-performer review candidates: {result['candidate_count']}")
        print("Target track selected by machine: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityStashInventoryError, PhotoIdentityMultiSourceDiscoveryError) as exc:
        print(f"BodyRig multi-performer source discovery: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
