from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD
from .photoidentity_openpose_runner import _extract_frame, select_detail_frame_candidates
from .photoidentity_schp_contract import ADAPTER, ADAPTER_REVISION

SUPPORTED_DOMAINS = {"hair_hairline", "skin_detail"}


class PhotoIdentitySchpRunnerError(RuntimeError):
    pass


def _merge_best(
    destination: dict[str, list[dict[str, object]]],
    incoming: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    expected_scene_id: str,
) -> None:
    expected_scene = str(expected_scene_id or "").strip()
    if not expected_scene:
        raise PhotoIdentitySchpRunnerError("SCHP expected scene id is missing")
    for domain, raw_claims in incoming.items():
        if domain not in SUPPORTED_DOMAINS:
            raise PhotoIdentitySchpRunnerError(f"SCHP inference overclaimed unsupported domain: {domain}")
        if not isinstance(raw_claims, Sequence) or isinstance(raw_claims, (str, bytes, bytearray)):
            raise PhotoIdentitySchpRunnerError(f"SCHP claims for {domain} must be an array")
        by_scene = {
            str(item.get("scene_id") or ""): dict(item)
            for item in destination.get(domain, [])
            if isinstance(item, Mapping) and item.get("scene_id")
        }
        for raw in raw_claims:
            if not isinstance(raw, Mapping):
                raise PhotoIdentitySchpRunnerError(f"SCHP claim for {domain} is not an object")
            claim = dict(raw)
            scene = str(claim.get("scene_id") or "").strip()
            if scene != expected_scene:
                raise PhotoIdentitySchpRunnerError(
                    f"SCHP claim for {domain} is bound to unexpected scene {scene or 'missing'}"
                )
            if claim.get("source_derived") is not True:
                raise PhotoIdentitySchpRunnerError(f"SCHP claim for {domain} is not source-derived")
            if claim.get("adapter") != ADAPTER or claim.get("revision") != ADAPTER_REVISION:
                raise PhotoIdentitySchpRunnerError(
                    f"SCHP claim for {domain} does not match pinned adapter authority"
                )
            quality_raw = claim.get("quality")
            if isinstance(quality_raw, bool):
                raise PhotoIdentitySchpRunnerError(f"SCHP claim for {domain} has invalid quality")
            try:
                quality = float(quality_raw)
            except (TypeError, ValueError) as exc:
                raise PhotoIdentitySchpRunnerError(f"SCHP claim for {domain} has invalid quality") from exc
            if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
                raise PhotoIdentitySchpRunnerError(f"SCHP claim for {domain} quality is outside 0..1")
            claim["quality"] = quality
            current = by_scene.get(scene)
            if current is None or quality > float(current.get("quality", 0.0)):
                by_scene[scene] = claim
        destination[domain] = sorted(
            by_scene.values(), key=lambda item: (-float(item["quality"]), str(item["scene_id"]))
        )


def _qualified_scene_count(evidence: Mapping[str, Sequence[Mapping[str, object]]], domain: str) -> int:
    return len(
        {
            str(item.get("scene_id") or "")
            for item in evidence.get(domain, [])
            if isinstance(item, Mapping) and float(item.get("quality", 0.0)) >= DETAIL_QUALITY_THRESHOLD
        }
    )


def _run_inference(
    *,
    runtime_python: Path,
    repo_root: Path,
    model_path: Path,
    frame: Path,
    observation_path: Path,
    scene_id: str,
) -> dict[str, list[dict[str, object]]]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(repo_root) + (os.pathsep + existing if existing else "")
    try:
        completed = subprocess.run(
            [
                str(runtime_python),
                "-m",
                "bodyrig.photoidentity_schp_infer",
                "--model",
                str(model_path),
                "--image",
                str(frame),
                "--observation",
                str(observation_path),
                "--scene-id",
                scene_id,
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=300,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotoIdentitySchpRunnerError("SCHP private inference could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise PhotoIdentitySchpRunnerError(f"SCHP private inference failed: {detail}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise PhotoIdentitySchpRunnerError("SCHP private inference polluted its JSON output channel")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise PhotoIdentitySchpRunnerError("SCHP private inference returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySchpRunnerError("SCHP private inference result must be an object")
    normalized: dict[str, list[dict[str, object]]] = {}
    for key, raw in value.items():
        domain = str(key)
        if domain not in SUPPORTED_DOMAINS:
            raise PhotoIdentitySchpRunnerError(f"SCHP inference overclaimed unsupported domain: {domain}")
        if not isinstance(raw, list):
            raise PhotoIdentitySchpRunnerError(f"SCHP inference claims for {domain} must be an array")
        normalized[domain] = raw
    return normalized


def collect_schp_detail_evidence(
    *,
    rows: Sequence[Mapping[str, Any]],
    sources_by_ordinal: Mapping[int, Mapping[str, Any]],
    private_root: Path,
    ffmpeg: str,
    runtime_python: Path,
    model_path: Path,
    repo_root: Path,
) -> dict[str, list[dict[str, object]]]:
    private_root = private_root.expanduser().resolve()
    runtime_python = runtime_python.expanduser().resolve()
    model_path = model_path.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    if private_root.exists():
        raise PhotoIdentitySchpRunnerError("private SCHP workspace already exists")
    if not runtime_python.is_file() or not model_path.is_file() or not repo_root.is_dir():
        raise PhotoIdentitySchpRunnerError("SCHP private runner authority paths are missing")
    private_root.mkdir(parents=True, exist_ok=False)

    evidence: dict[str, list[dict[str, object]]] = {}
    attempted: set[tuple[int, float]] = set()
    candidate_number = 0
    for row in select_detail_frame_candidates(rows):
        ordinal = int(row["source_ordinal"])
        source_meta = sources_by_ordinal.get(ordinal)
        if not isinstance(source_meta, Mapping):
            raise PhotoIdentitySchpRunnerError("SCHP row source ordinal has no private source binding")
        source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
        midpoint = float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0
        key = (ordinal, round(midpoint, 3))
        if key in attempted:
            continue
        attempted.add(key)
        candidate_number += 1

        candidate_root = private_root / f"candidate-{candidate_number:04d}"
        candidate_root.mkdir()
        frame = candidate_root / "source-frame.png"
        observation_path = candidate_root / "observation.json"
        _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=midpoint, output=frame)
        observation_path.write_text(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        scene_id = str(row["scene_id"])
        claims = _run_inference(
            runtime_python=runtime_python,
            repo_root=repo_root,
            model_path=model_path,
            frame=frame,
            observation_path=observation_path,
            scene_id=scene_id,
        )
        _merge_best(evidence, claims, expected_scene_id=scene_id)
        if all(_qualified_scene_count(evidence, domain) >= 2 for domain in SUPPORTED_DOMAINS):
            break

    return evidence
