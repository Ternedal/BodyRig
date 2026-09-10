from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD
from .photoidentity_openpose_detail import (
    CAPABILITIES,
    PhotoIdentityOpenPoseDetailError,
    analyze_openpose_detail,
    merge_best_claims,
)
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PhotoIdentityOpenPoseRunnerError(RuntimeError):
    pass


def _checked(
    args: Sequence[str],
    *,
    label: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotoIdentityOpenPoseRunnerError(f"{label} could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise PhotoIdentityOpenPoseRunnerError(
            f"{label} failed with exit code {completed.returncode}: {detail}"
        )
    return completed


def _png_size(path: Path) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        raise PhotoIdentityOpenPoseRunnerError(f"detail frame is unreadable: {path}") from exc
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise PhotoIdentityOpenPoseRunnerError("detail frame is not a canonical PNG")
    width, height = struct.unpack(">II", header[16:24])
    if not 64 <= width <= 16384 or not 64 <= height <= 16384:
        raise PhotoIdentityOpenPoseRunnerError("detail frame dimensions are invalid")
    return width, height


def _openpose_model_root(openpose: str) -> str:
    executable = PurePosixPath(openpose)
    suffix = PurePosixPath("build/examples/openpose/openpose.bin")
    if len(executable.parts) <= len(suffix.parts) or tuple(executable.parts[-len(suffix.parts) :]) != suffix.parts:
        raise PhotoIdentityOpenPoseRunnerError(
            "detail OpenPose executable must use <root>/build/examples/openpose/openpose.bin"
        )
    root = PurePosixPath(*executable.parts[: -len(suffix.parts)])
    result = str(root / "models")
    if not result.startswith("/"):
        raise PhotoIdentityOpenPoseRunnerError("could not derive absolute OpenPose model root")
    return result


def _score(row: Mapping[str, Any], *, face: bool) -> float:
    visibility_key = "face_visibility" if face else "full_body_visibility"
    try:
        values = (
            float(row["target_confidence"]),
            float(row[visibility_key]),
            float(row["sharpness"]),
            1.0 - float(row["occlusion"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PhotoIdentityOpenPoseRunnerError("photoidentity row lacks numeric source-quality fields") from exc
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
        raise PhotoIdentityOpenPoseRunnerError("photoidentity row source-quality fields are invalid")
    return math.prod(values)


def select_detail_frame_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pick at most one face-best and one body-best observation per scene."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        scene = str(row.get("scene_id") or "").strip()
        ordinal = row.get("source_ordinal")
        start = row.get("start_seconds")
        duration = row.get("duration_seconds")
        if not scene or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise PhotoIdentityOpenPoseRunnerError("photoidentity row has invalid scene/source identity")
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)) or float(start) < 0.0:
            raise PhotoIdentityOpenPoseRunnerError("photoidentity row start is invalid")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or float(duration) <= 0.0:
            raise PhotoIdentityOpenPoseRunnerError("photoidentity row duration is invalid")
        grouped.setdefault(scene, []).append(row)

    result: list[dict[str, Any]] = []
    scene_rank: list[tuple[float, str]] = []
    chosen_by_scene: dict[str, list[dict[str, Any]]] = {}
    for scene, scene_rows in grouped.items():
        face_best = max(scene_rows, key=lambda item: (_score(item, face=True), -float(item["start_seconds"])))
        body_best = max(scene_rows, key=lambda item: (_score(item, face=False), -float(item["start_seconds"])))
        unique: list[dict[str, Any]] = []
        seen: set[tuple[int, float]] = set()
        for candidate in (face_best, body_best):
            key = (int(candidate["source_ordinal"]), float(candidate["start_seconds"]))
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        chosen_by_scene[scene] = unique
        scene_rank.append((max(_score(face_best, face=True), _score(body_best, face=False)), scene))

    for _, scene in sorted(scene_rank, key=lambda item: (-item[0], item[1])):
        result.extend(chosen_by_scene[scene])
    return result


def _extract_frame(*, ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
    if not source.is_file():
        raise PhotoIdentityOpenPoseRunnerError("private detail source file disappeared during sweep")
    output.parent.mkdir(parents=True, exist_ok=True)
    _checked(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-an",
            "-sn",
            "-dn",
            "-y",
            str(output),
        ],
        label="photoidentity detail frame extraction",
        timeout=120,
    )
    if not output.is_file():
        raise PhotoIdentityOpenPoseRunnerError("ffmpeg produced no detail frame")


def _run_openpose(
    *,
    frame: Path,
    distribution: str,
    openpose: str,
    wsl_exe: str,
) -> dict[str, Any]:
    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_dir = converter(str(frame.parent))
    except (OSError, WslBridgeError) as exc:
        raise PhotoIdentityOpenPoseRunnerError(f"WSL detail path conversion failed: {exc}") from exc
    if not linux_dir.startswith("/") or "\n" in linux_dir or "\r" in linux_dir:
        raise PhotoIdentityOpenPoseRunnerError("WSL detail path conversion returned an invalid path")

    _checked(
        [
            wsl_exe,
            "-d",
            distribution,
            "--",
            openpose,
            "--image_dir",
            linux_dir,
            "--write_json",
            linux_dir,
            "--display",
            "0",
            "--model_pose",
            "BODY_25",
            "--model_folder",
            _openpose_model_root(openpose),
            "--net_resolution",
            "-1x544",
            "--scale_number",
            "3",
            "--scale_gap",
            "0.25",
            "--hand",
            "--face",
            "--render_pose",
            "0",
            "--number_people_max",
            "1",
        ],
        label="pinned OpenPose photoidentity detail extraction",
        timeout=1200,
    )
    result = frame.with_name(f"{frame.stem}_keypoints.json")
    if not result.is_file():
        raise PhotoIdentityOpenPoseRunnerError("OpenPose produced no detail keypoint JSON")
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityOpenPoseRunnerError("OpenPose detail keypoint JSON is unreadable") from exc
    if not isinstance(payload, dict):
        raise PhotoIdentityOpenPoseRunnerError("OpenPose detail keypoint result must be an object")
    return payload


def _qualified_scene_count(evidence: Mapping[str, Sequence[Mapping[str, object]]], domain: str) -> int:
    return len(
        {
            str(item.get("scene_id") or "")
            for item in evidence.get(domain, [])
            if isinstance(item, Mapping) and float(item.get("quality", 0.0)) >= DETAIL_QUALITY_THRESHOLD
        }
    )


def collect_openpose_detail_evidence(
    *,
    rows: Sequence[Mapping[str, Any]],
    sources_by_ordinal: Mapping[int, Mapping[str, Any]],
    private_root: Path,
    ffmpeg: str,
    distribution: str,
    openpose: str,
    wsl_exe: str,
) -> dict[str, list[dict[str, object]]]:
    """Collect source-derived OpenPose detail evidence without persisting source paths."""

    if not str(distribution or "").strip() or not str(openpose or "").startswith("/"):
        raise PhotoIdentityOpenPoseRunnerError("pinned OpenPose detail runtime is incomplete")
    _openpose_model_root(openpose)
    private_root = private_root.expanduser().resolve()
    if private_root.exists():
        raise PhotoIdentityOpenPoseRunnerError("private OpenPose detail workspace already exists")
    private_root.mkdir(parents=True, exist_ok=False)

    evidence: dict[str, list[dict[str, object]]] = {}
    attempted: set[tuple[int, float]] = set()
    candidate_number = 0
    for row in select_detail_frame_candidates(rows):
        ordinal = int(row["source_ordinal"])
        source_meta = sources_by_ordinal.get(ordinal)
        if not isinstance(source_meta, Mapping):
            raise PhotoIdentityOpenPoseRunnerError("detail row source ordinal has no private source binding")
        source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
        midpoint = float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0
        key = (ordinal, round(midpoint, 3))
        if key in attempted:
            continue
        attempted.add(key)
        candidate_number += 1

        frame_root = private_root / f"candidate-{candidate_number:04d}"
        frame_root.mkdir()
        frame = frame_root / "source-frame.png"
        _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=midpoint, output=frame)
        width, height = _png_size(frame)
        payload = _run_openpose(
            frame=frame,
            distribution=distribution,
            openpose=openpose,
            wsl_exe=wsl_exe,
        )
        try:
            claims = analyze_openpose_detail(
                payload,
                scene_id=str(row["scene_id"]),
                observation=row,
                frame_width=width,
                frame_height=height,
            )
        except PhotoIdentityOpenPoseDetailError as exc:
            raise PhotoIdentityOpenPoseRunnerError(str(exc)) from exc
        merge_best_claims(evidence, claims)

        # All currently supported OpenPose detail domains require two distinct
        # qualifying scenes in the photoidentity contract. Stop once that exact
        # requirement is met instead of needlessly processing more private media.
        if all(
            _qualified_scene_count(evidence, domain) >= 2
            for domain in ("eyes_detail", "hands", "feet")
        ):
            break

    return evidence
