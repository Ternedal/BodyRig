from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .observation import Observation, load_stash_source_manifest
from .observation_cli import _load_config
from .observation_runner import run_external_analyzer
from .photoidentity_evidence import (
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    write_bundle,
)
from .stash_cli import _filter_decodable_sources, _remap_scene_paths
from .stash_source import (
    SourceCandidate,
    StashClient,
    StashConfig,
    StashSourceError,
    VIDEO_SUFFIXES,
    _number,
    _projection_safe_source,
    _score_candidate,
    build_source_manifest,
    write_source_manifest,
)

SWEEP_FORMAT = "bodyrig-photoidentity-stash-sweep"
SWEEP_VERSION = 1
MAX_SWEEP_SOURCES = 100
MAX_BATCH_SOURCES = 10


class PhotoIdentitySweepError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_revision(value: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentitySweepError("photoidentity sweep requires an exact BodyRig Git revision")
    return revision


def _rank_source_pool(
    scenes: Iterable[Mapping[str, Any]],
    *,
    performer_id: str,
) -> list[SourceCandidate]:
    """Rank the complete local, flat-camera, single-performer source pool.

    The existing Stash source contract intentionally caps a reconstruction
    manifest at ten files. Photoidentity evidence gathering is a *pre-build*
    sweep, so it examines a larger pool and then feeds the unchanged v1
    analyzer in batches of at most ten. Multi-performer scenes are excluded:
    the current built-in HOG/Haar analyzer cannot prove which detected person
    is the named Stash performer.
    """

    performer_id = str(performer_id or "").strip()
    if not performer_id:
        raise PhotoIdentitySweepError("photoidentity performer id is required")
    by_path: dict[str, SourceCandidate] = {}
    for scene in scenes:
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            continue
        performers = scene.get("performers") or []
        performer_ids = {
            str(item.get("id"))
            for item in performers
            if isinstance(item, Mapping) and item.get("id") is not None
        }
        if performer_id not in performer_ids or len(performer_ids) != 1:
            continue
        tags = [
            str(item.get("name") or "")
            for item in (scene.get("tags") or [])
            if isinstance(item, Mapping)
        ]
        title = str(scene.get("title") or f"Scene {scene_id}")
        for file_info in scene.get("files") or []:
            if not isinstance(file_info, Mapping):
                continue
            raw_path = str(file_info.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if path.suffix.lower() not in VIDEO_SUFFIXES or not path.is_file():
                continue
            try:
                normalized = str(path.resolve(strict=False))
            except OSError:
                continue
            width = int(_number(file_info.get("width")))
            height = int(_number(file_info.get("height")))
            if not _projection_safe_source(width=width, height=height, tags=tags):
                continue
            duration = _number(file_info.get("duration"))
            framerate = _number(file_info.get("frame_rate"))
            score = _score_candidate(
                width=width,
                height=height,
                duration=duration,
                framerate=framerate,
                performer_count=1,
                tags=tags,
            )
            candidate = SourceCandidate(
                scene_id=scene_id,
                scene_title=title,
                path=normalized,
                width=width,
                height=height,
                duration=duration,
                framerate=framerate,
                performer_count=1,
                score=score,
            )
            key = os.path.normcase(normalized)
            previous = by_path.get(key)
            if previous is None or candidate.score > previous.score:
                by_path[key] = candidate
    return sorted(
        by_path.values(),
        key=lambda item: (-item.score, -item.height, -item.width, item.path.lower()),
    )


def _command_for_manifest(command: Sequence[str], manifest: Path) -> list[str]:
    argv = list(command)
    indices = [index for index, value in enumerate(argv) if value == "--bodyrig-stash-manifest"]
    if len(indices) != 1:
        raise PhotoIdentitySweepError(
            "photoidentity sweep requires an observation analyzer command with exactly one --bodyrig-stash-manifest binding"
        )
    index = indices[0]
    if index + 1 >= len(argv):
        raise PhotoIdentitySweepError("observation analyzer Stash manifest binding is incomplete")
    argv[index + 1] = str(manifest)
    return argv


def _known_capabilities(adapter: str, revision: str) -> list[str]:
    # Do not infer capabilities from a friendly adapter name. This explicit map
    # is deliberately conservative; a future detail analyzer must land a new
    # exact adapter/revision binding before it can satisfy extra domains.
    if adapter == "opencv-hog-haar" and revision == "1":
        return ["coarse-face-view", "coarse-full-body-view"]
    return []


def _row_from_observation(
    observation: Observation,
    *,
    scene_id: str,
    source_ordinal: int,
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "source_ordinal": source_ordinal,
        "start_seconds": round(observation.start_seconds, 3),
        "duration_seconds": round(observation.duration_seconds, 3),
        "target_confidence": round(observation.target_confidence, 4),
        "target_screen_fraction": round(observation.target_screen_fraction, 4),
        "face_visibility": round(observation.face_visibility, 4),
        "full_body_visibility": round(observation.full_body_visibility, 4),
        "sharpness": round(observation.sharpness, 4),
        "occlusion": round(observation.occlusion, 4),
        "motion": round(observation.motion, 4),
        "view": observation.view,
    }


def run_sweep(
    *,
    performer_id: str,
    baseline_source_manifest: Path,
    analyzer_config_path: Path,
    stash_url: str,
    stash_api_key: str,
    bodyrig_revision: str,
    output_dir: Path,
    ffmpeg: str,
    scene_limit: int = 1000,
    max_sources: int = 50,
    batch_size: int = 10,
    decode_timeout: int = 20,
) -> dict[str, Any]:
    revision = _canonical_revision(bodyrig_revision)
    performer_id = str(performer_id or "").strip()
    if not performer_id or len(performer_id) > 256:
        raise PhotoIdentitySweepError("photoidentity performer id is invalid")
    if isinstance(scene_limit, bool) or not 1 <= scene_limit <= 1000:
        raise PhotoIdentitySweepError("photoidentity scene_limit must be in 1..1000")
    if isinstance(max_sources, bool) or not 1 <= max_sources <= MAX_SWEEP_SOURCES:
        raise PhotoIdentitySweepError(f"photoidentity max_sources must be in 1..{MAX_SWEEP_SOURCES}")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_BATCH_SOURCES:
        raise PhotoIdentitySweepError(f"photoidentity batch_size must be in 1..{MAX_BATCH_SOURCES}")
    if isinstance(decode_timeout, bool) or not 1 <= decode_timeout <= 120:
        raise PhotoIdentitySweepError("photoidentity decode_timeout must be in 1..120 seconds")

    baseline_source_manifest = baseline_source_manifest.expanduser().resolve()
    analyzer_config_path = analyzer_config_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not baseline_source_manifest.is_file() or not analyzer_config_path.is_file():
        raise PhotoIdentitySweepError("baseline source manifest/analyzer config is missing")
    if output_dir.exists():
        raise PhotoIdentitySweepError(f"photoidentity sweep output already exists: {output_dir}")

    try:
        baseline_manifest = json.loads(baseline_source_manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySweepError("baseline Stash source manifest is unreadable") from exc
    if (
        not isinstance(baseline_manifest, dict)
        or baseline_manifest.get("format") != "bodyrig-stash-source-manifest"
        or isinstance(baseline_manifest.get("version"), bool)
        or baseline_manifest.get("version") != 1
    ):
        raise PhotoIdentitySweepError("baseline Stash source manifest format/version is invalid")
    baseline_performer = baseline_manifest.get("performer") or {}
    if str(baseline_performer.get("id") or "") != performer_id:
        raise PhotoIdentitySweepError("baseline Stash source manifest belongs to a different performer")
    baseline_sha = _sha256(baseline_source_manifest)

    try:
        config = _load_config(analyzer_config_path)
    except Exception as exc:
        raise PhotoIdentitySweepError(f"observation analyzer config is invalid: {exc}") from exc
    adapter = str(config["adapter"])
    adapter_revision = str(config["revision"])
    capabilities = _known_capabilities(adapter, adapter_revision)

    client = StashClient(StashConfig(url=stash_url, api_key=stash_api_key, timeout_seconds=20))
    performer = client.performer(performer_id)
    if str(performer.get("id") or "") != performer_id:
        raise PhotoIdentitySweepError("live Stash performer identity changed during photoidentity sweep")
    scenes = _remap_scene_paths(
        client.scenes_for_performer(performer_id, limit=scene_limit),
        stash_url=client.config.url,
    )
    ranked_all = _rank_source_pool(scenes, performer_id=performer_id)
    if not ranked_all:
        raise PhotoIdentitySweepError("no projection-safe local single-performer Stash video is available for photoidentity evidence")
    selected_pool = ranked_all[:max_sources]
    decodable = _filter_decodable_sources(
        selected_pool,
        ffmpeg=ffmpeg,
        timeout_seconds=decode_timeout,
    )
    if not decodable:
        raise PhotoIdentitySweepError("no ranked Stash source passed the one-frame decode gate")

    scan_exhausted = len(ranked_all) <= max_sources
    output_dir.mkdir(parents=True, exist_ok=False)
    private_root = output_dir / "private-batches"
    private_root.mkdir()
    rows: list[dict[str, Any]] = []
    analyzed_sources = 0

    for batch_index, start in enumerate(range(0, len(decodable), batch_size), start=1):
        batch = decodable[start : start + batch_size]
        if not batch:
            continue
        batch_root = private_root / f"batch-{batch_index:03d}"
        batch_root.mkdir()
        manifest_path = batch_root / "bodyrig-stash-source-manifest.json"
        manifest = build_source_manifest(
            performer=performer,
            candidates=list(batch),
            stash_version=client.version(),
            candidate_count=len(scenes),
        )
        write_source_manifest(manifest_path, manifest)
        _, sources, source_sha = load_stash_source_manifest(manifest_path)
        workspace = batch_root / "analysis-workspace"
        workspace.mkdir()
        command = _command_for_manifest(config["command"], manifest_path)
        observations = run_external_analyzer(
            command,
            sources=sources,
            performer_id=performer_id,
            source_manifest_sha256=source_sha,
            workspace=workspace,
            adapter=adapter,
            revision=adapter_revision,
            timeout_seconds=int(config["timeout_seconds"]),
        )
        source_to_scene = {str(source["source_id"]): str(source["scene_id"]) for source in sources}
        source_to_ordinal = {
            str(source["source_id"]): start + index + 1
            for index, source in enumerate(sources)
        }
        for observation in observations:
            scene_id = source_to_scene.get(observation.source_id)
            ordinal = source_to_ordinal.get(observation.source_id)
            if scene_id is None or ordinal is None:
                raise PhotoIdentitySweepError("observation analyzer returned an unmapped source during sweep")
            rows.append(_row_from_observation(observation, scene_id=scene_id, source_ordinal=ordinal))
        analyzed_sources += len(sources)

    if not rows:
        raise PhotoIdentitySweepError("photoidentity sweep found no usable source observations")

    observation_evidence = build_observation_evidence(
        performer_id=performer_id,
        bodyrig_revision=revision,
        baseline_source_manifest_sha256=baseline_sha,
        analyzer_adapter=adapter,
        analyzer_revision=adapter_revision,
        analyzer_capabilities=capabilities,
        candidate_scenes=len(scenes),
        source_files_scanned=analyzed_sources,
        scan_exhausted=scan_exhausted,
        rows=rows,
        detail_evidence={},
    )
    observations_path, report_path, report = write_bundle(output_dir / "evidence", observation_evidence)
    receipt = {
        "format": SWEEP_FORMAT,
        "version": SWEEP_VERSION,
        "performer_id": performer_id,
        "bodyrig_revision": revision,
        "baseline_source_manifest_sha256": baseline_sha,
        "candidate_scenes": len(scenes),
        "rankable_single_performer_sources": len(ranked_all),
        "source_files_scanned": analyzed_sources,
        "scan_exhausted": scan_exhausted,
        "analyzer": {"adapter": adapter, "revision": adapter_revision, "capabilities": capabilities},
        "observation_evidence": str(observations_path),
        "observation_evidence_sha256": _sha256(observations_path),
        "sufficiency_report": str(report_path),
        "sufficiency_report_sha256": _sha256(report_path),
        "source_evidence_sufficient": bool(report["source_evidence_sufficient"]),
        "reconstruction_permitted": bool(report["reconstruction_permitted"]),
        "human_review_render_permitted": bool(report["human_review_render_permitted"]),
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    receipt_path = output_dir / "photoidentity-sweep.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {**receipt, "receipt": str(receipt_path), "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan additional local Stash media and prove whether photoidentity source evidence is sufficient."
    )
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--baseline-source-manifest", required=True)
    parser.add_argument("--analyzer-config", required=True)
    parser.add_argument("--stash-url", required=True)
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--scene-limit", type=int, default=1000)
    parser.add_argument("--max-sources", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--decode-timeout", type=int, default=20)
    args = parser.parse_args(argv)

    try:
        api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        result = run_sweep(
            performer_id=args.performer_id,
            baseline_source_manifest=Path(args.baseline_source_manifest),
            analyzer_config_path=Path(args.analyzer_config),
            stash_url=args.stash_url,
            stash_api_key=api_key,
            bodyrig_revision=args.bodyrig_revision,
            output_dir=Path(args.output_dir),
            ffmpeg=args.ffmpeg,
            scene_limit=args.scene_limit,
            max_sources=args.max_sources,
            batch_size=args.batch_size,
            decode_timeout=args.decode_timeout,
        )
    except (OSError, ValueError, StashSourceError, PhotoIdentityEvidenceError, PhotoIdentitySweepError) as exc:
        print(f"BodyRig photoidentity evidence sweep: FAIL: {exc}", file=sys.stderr)
        return 1

    report = result["report"]
    state = "PASS" if report["source_evidence_sufficient"] else "INSUFFICIENT EVIDENCE"
    print(
        f"BodyRig photoidentity evidence sweep: {state} | "
        f"scanned={result['source_files_scanned']} | rankable={result['rankable_single_performer_sources']} | "
        f"next={report['next_action']}"
    )
    print(f"Evidence: {result['sufficiency_report']}")
    if report["analyzer_blockers"]:
        print("Analyzer cannot prove: " + ", ".join(report["analyzer_blockers"]))
    if report["source_blockers"]:
        print("Source coverage missing: " + ", ".join(report["source_blockers"]))
    print("Render permitted: " + str(bool(report["human_review_render_permitted"])).upper())
    print("Generic guessing permitted: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())