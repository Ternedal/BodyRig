from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image

from .photoidentity_detail_enrich import _private_source_bindings
from .photoidentity_evidence import PhotoIdentityEvidenceError, validate_bundle
from .photoidentity_openpose_detail import ADAPTER as OPENPOSE_ADAPTER
from .photoidentity_openpose_detail import REVISION as OPENPOSE_REVISION
from .photoidentity_openpose_runner import (
    PhotoIdentityOpenPoseRunnerError,
    _extract_frame,
    _png_size,
    _run_openpose,
)

FORMAT = "bodyrig-photoidentity-nail-source-discovery"
VERSION = 1
POLICY_REVISION = "photoidentity-nail-source-discovery-v1"
REGIONS = ("left_fingernails", "right_fingernails", "left_toenails", "right_toenails")
HAND_TIP_INDICES = (4, 8, 12, 16, 20)
HAND_POINT_THRESHOLD = 0.20
HAND_TIP_THRESHOLD = 0.25
FOOT_POINT_THRESHOLD = 0.20
MIN_HAND_CONFIDENT_POINTS = 16
MIN_HAND_CONFIDENT_TIPS = 4
MIN_HAND_NATIVE_CROP = 240
MIN_FOOT_NATIVE_CROP = 180
MIN_SOURCE_SHARPNESS = 0.75
MAX_SOURCE_OCCLUSION = 0.15
MIN_TARGET_CONFIDENCE = 0.75
MAX_FRAMES_PER_SCENE = 8
MAX_DISCOVERY_FRAMES = 160


class PhotoIdentityNailDiscoveryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityNailDiscoveryError(f"nail discovery file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityNailDiscoveryError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityNailDiscoveryError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityNailDiscoveryError(f"nail discovery evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityNailDiscoveryError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentityNailDiscoveryError(f"{label} must be in 0..1")
    return result


def _triples(value: object, *, label: str, expected: int) -> list[tuple[float, float, float]]:
    if not isinstance(value, list) or len(value) != expected * 3:
        raise PhotoIdentityNailDiscoveryError(f"OpenPose {label} must contain exactly {expected * 3} values")
    result: list[tuple[float, float, float]] = []
    for index in range(expected):
        raw = value[index * 3 : index * 3 + 3]
        try:
            x, y, confidence = (float(item) for item in raw)
        except (TypeError, ValueError) as exc:
            raise PhotoIdentityNailDiscoveryError(f"OpenPose {label} contains non-numeric values") from exc
        if not all(math.isfinite(item) for item in (x, y, confidence)) or not 0.0 <= confidence <= 1.0:
            raise PhotoIdentityNailDiscoveryError(f"OpenPose {label} contains invalid coordinates/confidence")
        result.append((x, y, confidence))
    return result


def _in_frame(
    points: Sequence[tuple[float, float, float]],
    *,
    threshold: float,
    width: int,
    height: int,
) -> list[tuple[float, float, float]]:
    return [
        point
        for point in points
        if point[2] >= threshold and 0.0 <= point[0] < width and 0.0 <= point[1] < height
    ]


def _square_crop(
    points: Sequence[tuple[float, float, float]],
    *,
    width: int,
    height: int,
    padding: float,
    minimum_side: int,
) -> tuple[int, int, int, int]:
    if not points:
        raise PhotoIdentityNailDiscoveryError("cannot build a nail crop without confident source points")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    side = max(float(minimum_side), max(span_x, span_y) * (1.0 + 2.0 * padding))
    side = min(side, float(min(width, height)))
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    left = int(round(center_x - side / 2.0))
    top = int(round(center_y - side / 2.0))
    side_i = max(1, int(round(side)))
    left = max(0, min(left, width - side_i))
    top = max(0, min(top, height - side_i))
    right = min(width, left + side_i)
    bottom = min(height, top + side_i)
    if right <= left or bottom <= top:
        raise PhotoIdentityNailDiscoveryError("computed nail source crop is empty")
    return left, top, right, bottom


def _mean_confidence(points: Sequence[tuple[float, float, float]]) -> float:
    return sum(point[2] for point in points) / len(points) if points else 0.0


def _candidate_quality(
    *,
    point_confidence: float,
    native_side: int,
    required_native_side: int,
    observation: Mapping[str, Any],
) -> float:
    target = _finite(observation.get("target_confidence"), label="target confidence")
    sharpness = _finite(observation.get("sharpness"), label="source sharpness")
    occlusion = _finite(observation.get("occlusion"), label="source occlusion")
    resolution = min(1.0, native_side / float(required_native_side))
    return round(min(point_confidence, resolution, target, sharpness, 1.0 - occlusion), 4)


def _save_closeup(frame: Path, crop: tuple[int, int, int, int], output: Path) -> tuple[int, int, str]:
    try:
        with Image.open(frame) as source:
            source = source.convert("RGB")
            native = source.crop(crop)
            native_width, native_height = native.size
            if native_width <= 0 or native_height <= 0:
                raise PhotoIdentityNailDiscoveryError("nail source crop is empty")
            native.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1024, 1024), (0, 0, 0))
            offset = ((1024 - native.width) // 2, (1024 - native.height) // 2)
            canvas.paste(native, offset)
            output.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(output, format="PNG", compress_level=4)
    except PhotoIdentityNailDiscoveryError:
        raise
    except Exception as exc:
        raise PhotoIdentityNailDiscoveryError("could not materialize source-grounded nail closeup") from exc
    if _png_size(output) != (1024, 1024):
        raise PhotoIdentityNailDiscoveryError("nail closeup is not canonical 1024x1024 PNG")
    return native_width, native_height, _sha256_file(output)


def _region_from_points(
    *,
    region: str,
    points: Sequence[tuple[float, float, float]],
    point_confidence: float,
    frame: Path,
    frame_width: int,
    frame_height: int,
    required_native_side: int,
    observation: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    crop = _square_crop(
        points,
        width=frame_width,
        height=frame_height,
        padding=0.45,
        minimum_side=max(96, required_native_side // 2),
    )
    native_width, native_height, image_sha = _save_closeup(frame, crop, output)
    native_side = min(native_width, native_height)
    quality = _candidate_quality(
        point_confidence=point_confidence,
        native_side=native_side,
        required_native_side=required_native_side,
        observation=observation,
    )
    sharpness = _finite(observation.get("sharpness"), label="source sharpness")
    occlusion = _finite(observation.get("occlusion"), label="source occlusion")
    target = _finite(observation.get("target_confidence"), label="target confidence")
    review_eligible = (
        native_side >= required_native_side
        and sharpness >= MIN_SOURCE_SHARPNESS
        and occlusion <= MAX_SOURCE_OCCLUSION
        and target >= MIN_TARGET_CONFIDENCE
        and quality >= 0.75
    )
    return {
        "region": region,
        "image_sha256": image_sha,
        "width": 1024,
        "height": 1024,
        "native_crop_width": native_width,
        "native_crop_height": native_height,
        "keypoint_confidence": round(point_confidence, 4),
        "source_quality": quality,
        "review_eligible": review_eligible,
    }


def _claims_for_frame(
    payload: Mapping[str, Any],
    *,
    frame: Path,
    observation: Mapping[str, Any],
    output_root: Path,
) -> dict[str, dict[str, Any]]:
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        return {}
    person = people[0]
    width, height = _png_size(frame)
    body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected=25)
    left_hand = _triples(person.get("hand_left_keypoints_2d"), label="left hand", expected=21)
    right_hand = _triples(person.get("hand_right_keypoints_2d"), label="right hand", expected=21)
    result: dict[str, dict[str, Any]] = {}

    for name, hand in (("left_fingernails", left_hand), ("right_fingernails", right_hand)):
        confident = _in_frame(hand, threshold=HAND_POINT_THRESHOLD, width=width, height=height)
        tips = _in_frame(
            [hand[index] for index in HAND_TIP_INDICES],
            threshold=HAND_TIP_THRESHOLD,
            width=width,
            height=height,
        )
        if len(confident) >= MIN_HAND_CONFIDENT_POINTS and len(tips) >= MIN_HAND_CONFIDENT_TIPS:
            result[name] = _region_from_points(
                region=name,
                points=confident,
                point_confidence=min(_mean_confidence(confident), _mean_confidence(tips)),
                frame=frame,
                frame_width=width,
                frame_height=height,
                required_native_side=MIN_HAND_NATIVE_CROP,
                observation=observation,
                output=output_root / f"{name.replace('_', '-')}.png",
            )

    for name, indices in (("left_toenails", (19, 20, 21)), ("right_toenails", (22, 23, 24))):
        foot = [body[index] for index in indices]
        confident = _in_frame(foot, threshold=FOOT_POINT_THRESHOLD, width=width, height=height)
        if len(confident) == 3:
            result[name] = _region_from_points(
                region=name,
                points=confident,
                point_confidence=_mean_confidence(confident),
                frame=frame,
                frame_width=width,
                frame_height=height,
                required_native_side=MIN_FOOT_NATIVE_CROP,
                observation=observation,
                output=output_root / f"{name.replace('_', '-')}.png",
            )
    return result


def _row_score(row: Mapping[str, Any]) -> float:
    values = (
        _finite(row.get("target_confidence"), label="target confidence"),
        _finite(row.get("target_screen_fraction"), label="target screen fraction"),
        _finite(row.get("sharpness"), label="source sharpness"),
        1.0 - _finite(row.get("occlusion"), label="source occlusion"),
    )
    return math.prod(values)


def select_nail_frame_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        scene = str(row.get("scene_id") or "").strip()
        ordinal = row.get("source_ordinal")
        if not scene or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise PhotoIdentityNailDiscoveryError("nail discovery observation source identity is invalid")
        grouped.setdefault(scene, []).append(row)
    ranked_scenes = sorted(
        grouped,
        key=lambda scene: (-max(_row_score(item) for item in grouped[scene]), scene),
    )
    selected: list[dict[str, Any]] = []
    for scene in ranked_scenes:
        rows_for_scene = sorted(
            grouped[scene],
            key=lambda item: (-_row_score(item), float(item.get("start_seconds", 0.0))),
        )
        seen: set[tuple[int, int]] = set()
        for row in rows_for_scene:
            midpoint_ms = int(round((float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0) * 1000.0))
            key = (int(row["source_ordinal"]), midpoint_ms)
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
            if len(seen) >= MAX_FRAMES_PER_SCENE or len(selected) >= MAX_DISCOVERY_FRAMES:
                break
        if len(selected) >= MAX_DISCOVERY_FRAMES:
            break
    return selected


def discover_nail_sources(
    *,
    sweep_root: Path,
    ffmpeg: str,
    distribution: str,
    openpose: str,
    wsl_exe: str,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    observations_path = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    report_path = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        report = validate_bundle(report_path, observations_path)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityNailDiscoveryError(f"final hair/skin-enriched evidence is invalid: {exc}") from exc
    observations = _read_json(observations_path, label="Final photoidentity observations")
    source_count = int(report["source_files_scanned"])
    sources_by_ordinal, manifest_set_sha = _private_source_bindings(sweep_root, expected_count=source_count)

    private_root = sweep_root / "private-nail-source-candidates"
    if private_root.exists():
        raise PhotoIdentityNailDiscoveryError("private nail source candidate workspace already exists")
    private_root.mkdir(parents=True, exist_ok=False)

    public_candidates: list[dict[str, Any]] = []
    private_candidates: list[dict[str, Any]] = []
    media_hash_cache: dict[str, str] = {}
    candidate_index = 0
    for row in select_nail_frame_candidates(list(observations["rows"])):
        ordinal = int(row["source_ordinal"])
        source_meta = sources_by_ordinal.get(ordinal)
        if not isinstance(source_meta, Mapping):
            raise PhotoIdentityNailDiscoveryError("nail discovery row has no exact private source binding")
        scene_id = str(row["scene_id"])
        if str(source_meta.get("scene_id") or "") != scene_id:
            raise PhotoIdentityNailDiscoveryError("nail discovery scene/source binding changed")
        source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
        midpoint = float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0
        candidate_index += 1
        candidate_root = private_root / f"candidate-{candidate_index:04d}"
        candidate_root.mkdir()
        frame = candidate_root / "source-frame.png"
        _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=midpoint, output=frame)
        payload = _run_openpose(frame=frame, distribution=distribution, openpose=openpose, wsl_exe=wsl_exe)
        regions = _claims_for_frame(
            payload,
            frame=frame,
            observation=row,
            output_root=candidate_root,
        )
        if not regions:
            continue
        source_key = os.path.normcase(str(source))
        media_sha = media_hash_cache.get(source_key)
        if media_sha is None:
            media_sha = _sha256_file(source)
            media_hash_cache[source_key] = media_sha
        timestamp_ms = int(round(midpoint * 1000.0))
        candidate_seed = f"{scene_id}\n{ordinal}\n{timestamp_ms}\n{media_sha}".encode("utf-8")
        candidate_id = "nailcand-" + hashlib.sha256(candidate_seed).hexdigest()[:32]
        public_regions = {name: dict(value) for name, value in sorted(regions.items())}
        public = {
            "candidate_id": candidate_id,
            "scene_id": scene_id,
            "source_ordinal": ordinal,
            "timestamp_ms": timestamp_ms,
            "source_media_sha256": media_sha,
            "source_frame_sha256": _sha256_file(frame),
            "regions": public_regions,
        }
        private = {
            **public,
            "source_path": str(source),
            "candidate_directory": str(candidate_root),
            "region_images": {
                name: str(candidate_root / f"{name.replace('_', '-')}.png")
                for name in regions
            },
        }
        public_candidates.append(public)
        private_candidates.append(private)

    public_candidates.sort(key=lambda item: (str(item["scene_id"]), int(item["timestamp_ms"]), str(item["candidate_id"])))
    private_candidates.sort(key=lambda item: (str(item["scene_id"]), int(item["timestamp_ms"]), str(item["candidate_id"])))
    eligible_counts = {
        region: sum(
            1
            for candidate in public_candidates
            if isinstance(candidate.get("regions"), Mapping)
            and isinstance(candidate["regions"].get(region), Mapping)
            and candidate["regions"][region].get("review_eligible") is True
        )
        for region in REGIONS
    }
    eligible_scenes = {
        region: len(
            {
                str(candidate["scene_id"])
                for candidate in public_candidates
                if isinstance(candidate.get("regions"), Mapping)
                and isinstance(candidate["regions"].get(region), Mapping)
                and candidate["regions"][region].get("review_eligible") is True
            }
        )
        for region in REGIONS
    }
    public_manifest = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": str(report["performer_id"]),
        "bodyrig_revision": str(report["bodyrig_revision"]),
        "input_observation_evidence_sha256": _sha256_file(observations_path),
        "input_sufficiency_report_sha256": _sha256_file(report_path),
        "private_source_manifest_set_sha256": manifest_set_sha,
        "openpose_adapter": OPENPOSE_ADAPTER,
        "openpose_revision": OPENPOSE_REVISION,
        "candidate_count": len(public_candidates),
        "review_eligible_region_counts": eligible_counts,
        "review_eligible_distinct_scenes": eligible_scenes,
        "candidates": public_candidates,
        "source_paths_persisted": False,
        "machine_nail_identity_authority": False,
        "human_source_review_required": True,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }
    public_path = sweep_root / "nail-source-candidates.json"
    private_path = private_root / "private-candidate-index.json"
    _write_create_only(public_path, public_manifest)
    _write_create_only(private_path, {
        "format": "bodyrig-photoidentity-private-nail-source-index",
        "version": 1,
        "public_manifest_sha256": _sha256_file(public_path),
        "candidates": private_candidates,
    })
    return {
        **public_manifest,
        "manifest": str(public_path),
        "private_index": str(private_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover source-grounded hand/foot closeups for nail sufficiency review without granting nail authority."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = discover_nail_sources(
            sweep_root=Path(args.sweep_root),
            ffmpeg=args.ffmpeg,
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, PhotoIdentityNailDiscoveryError, PhotoIdentityOpenPoseRunnerError) as exc:
        print(f"BodyRig photoidentity nail source discovery: FAIL: {exc}", file=sys.stderr)
        return 1
    scenes = result["review_eligible_distinct_scenes"]
    print(
        "BodyRig photoidentity nail source discovery: PASS | "
        f"candidates={result['candidate_count']} | "
        f"left-fingernails-scenes={scenes['left_fingernails']} | "
        f"right-fingernails-scenes={scenes['right_fingernails']} | "
        f"left-toenails-scenes={scenes['left_toenails']} | "
        f"right-toenails-scenes={scenes['right_toenails']}"
    )
    print(f"Candidate manifest: {result['manifest']}")
    print(f"Private source closeups: {result['private_index']}")
    print("Nail authority: FALSE until explicit source-only human attestation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
