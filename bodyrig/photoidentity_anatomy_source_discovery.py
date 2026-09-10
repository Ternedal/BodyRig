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
from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD, PhotoIdentityEvidenceError, validate_bundle
from .photoidentity_openpose_detail import ADAPTER as OPENPOSE_ADAPTER
from .photoidentity_openpose_detail import REVISION as OPENPOSE_REVISION
from .photoidentity_openpose_runner import (
    PhotoIdentityOpenPoseRunnerError,
    _extract_frame,
    _png_size,
    _run_openpose,
)

FORMAT = "bodyrig-photoidentity-anatomy-source-discovery"
VERSION = 1
POLICY_REVISION = "photoidentity-anatomy-source-discovery-v1"
REGIONS = ("rear_body", "torso_chest", "waist_hips")
BODY_POINT_THRESHOLD = 0.25
MIN_SOURCE_SHARPNESS = 0.70
MAX_SOURCE_OCCLUSION = 0.18
MIN_TARGET_CONFIDENCE = 0.75
MIN_REAR_NATIVE_WIDTH = 420
MIN_REAR_NATIVE_HEIGHT = 640
MIN_TORSO_NATIVE_WIDTH = 300
MIN_TORSO_NATIVE_HEIGHT = 300
MIN_WAIST_NATIVE_WIDTH = 300
MIN_WAIST_NATIVE_HEIGHT = 260
MAX_FRAMES_PER_SCENE = 8
MAX_DISCOVERY_FRAMES = 160

# BODY_25 indices. The model is used only to locate source crops, never to
# decide whether anatomy is exposed or whether a person is actually rear-facing.
TORSO_INDICES = (1, 2, 5, 8, 9, 12)  # neck, shoulders, mid-hip, hips
WAIST_INDICES = (2, 5, 8, 9, 12, 10, 13)  # shoulders, hips, knees
REAR_REQUIRED_INDICES = (2, 5, 8, 9, 12, 10, 13, 11, 14)  # shoulders through ankles


class PhotoIdentityAnatomyDiscoveryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityAnatomyDiscoveryError(f"anatomy discovery file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityAnatomyDiscoveryError(f"anatomy discovery evidence already exists: {path}")
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
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} must be in 0..1")
    return result


def _triples(value: object, *, label: str, expected: int) -> list[tuple[float, float, float]]:
    if not isinstance(value, list) or len(value) != expected * 3:
        raise PhotoIdentityAnatomyDiscoveryError(f"OpenPose {label} must contain exactly {expected * 3} values")
    result: list[tuple[float, float, float]] = []
    for index in range(expected):
        raw = value[index * 3 : index * 3 + 3]
        try:
            x, y, confidence = (float(item) for item in raw)
        except (TypeError, ValueError) as exc:
            raise PhotoIdentityAnatomyDiscoveryError(f"OpenPose {label} contains non-numeric values") from exc
        if not all(math.isfinite(item) for item in (x, y, confidence)) or not 0.0 <= confidence <= 1.0:
            raise PhotoIdentityAnatomyDiscoveryError(f"OpenPose {label} contains invalid coordinates/confidence")
        result.append((x, y, confidence))
    return result


def _points_for_indices(
    body: Sequence[tuple[float, float, float]],
    indices: Sequence[int],
    *,
    width: int,
    height: int,
) -> list[tuple[float, float, float]]:
    result: list[tuple[float, float, float]] = []
    for index in indices:
        point = body[index]
        if point[2] < BODY_POINT_THRESHOLD or not (0.0 <= point[0] < width and 0.0 <= point[1] < height):
            return []
        result.append(point)
    return result


def _all_confident_body_points(
    body: Sequence[tuple[float, float, float]],
    *,
    width: int,
    height: int,
) -> list[tuple[float, float, float]]:
    return [
        point
        for point in body
        if point[2] >= BODY_POINT_THRESHOLD and 0.0 <= point[0] < width and 0.0 <= point[1] < height
    ]


def _crop_box(
    points: Sequence[tuple[float, float, float]],
    *,
    width: int,
    height: int,
    pad_x: float,
    pad_y: float,
) -> tuple[int, int, int, int]:
    if len(points) < 2:
        raise PhotoIdentityAnatomyDiscoveryError("cannot create anatomy crop without source keypoints")
    xs = [item[0] for item in points]
    ys = [item[1] for item in points]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= 1.0 or span_y <= 1.0:
        raise PhotoIdentityAnatomyDiscoveryError("anatomy source keypoints have implausible extent")
    left = max(0, int(math.floor(min(xs) - span_x * pad_x)))
    right = min(width, int(math.ceil(max(xs) + span_x * pad_x)))
    top = max(0, int(math.floor(min(ys) - span_y * pad_y)))
    bottom = min(height, int(math.ceil(max(ys) + span_y * pad_y)))
    if right <= left or bottom <= top:
        raise PhotoIdentityAnatomyDiscoveryError("computed anatomy source crop is empty")
    return left, top, right, bottom


def _save_closeup(frame: Path, crop: tuple[int, int, int, int], output: Path) -> tuple[int, int, str]:
    try:
        with Image.open(frame) as opened:
            source = opened.convert("RGB")
            native = source.crop(crop)
            native_width, native_height = native.size
            if native_width <= 0 or native_height <= 0:
                raise PhotoIdentityAnatomyDiscoveryError("anatomy source crop is empty")
            # thumbnail() never upscales. The 1024 canvas is presentation only;
            # native dimensions stay authoritative for review eligibility.
            native.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1024, 1024), (0, 0, 0))
            offset = ((1024 - native.width) // 2, (1024 - native.height) // 2)
            canvas.paste(native, offset)
            output.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(output, format="PNG", compress_level=4)
    except PhotoIdentityAnatomyDiscoveryError:
        raise
    except Exception as exc:
        raise PhotoIdentityAnatomyDiscoveryError("could not materialize source-grounded anatomy closeup") from exc
    if _png_size(output) != (1024, 1024):
        raise PhotoIdentityAnatomyDiscoveryError("anatomy closeup is not canonical 1024x1024 PNG")
    return native_width, native_height, _sha256_file(output)


def _mean_confidence(points: Sequence[tuple[float, float, float]]) -> float:
    return sum(point[2] for point in points) / len(points) if points else 0.0


def _source_quality(
    *,
    point_confidence: float,
    native_width: int,
    native_height: int,
    required_width: int,
    required_height: int,
    observation: Mapping[str, Any],
    require_full_body: bool,
) -> float:
    target = _finite(observation.get("target_confidence"), label="target confidence")
    sharpness = _finite(observation.get("sharpness"), label="source sharpness")
    occlusion = _finite(observation.get("occlusion"), label="source occlusion")
    legs = [
        point_confidence,
        min(1.0, native_width / float(required_width)),
        min(1.0, native_height / float(required_height)),
        target,
        sharpness,
        1.0 - occlusion,
    ]
    if require_full_body:
        legs.append(_finite(observation.get("full_body_visibility"), label="full-body visibility"))
    return round(min(legs), 4)


def _region_entry(
    *,
    region: str,
    frame: Path,
    crop: tuple[int, int, int, int],
    points: Sequence[tuple[float, float, float]],
    observation: Mapping[str, Any],
    required_width: int,
    required_height: int,
    require_full_body: bool,
    output: Path,
) -> dict[str, Any]:
    native_width, native_height, image_sha = _save_closeup(frame, crop, output)
    quality = _source_quality(
        point_confidence=_mean_confidence(points),
        native_width=native_width,
        native_height=native_height,
        required_width=required_width,
        required_height=required_height,
        observation=observation,
        require_full_body=require_full_body,
    )
    sharpness = _finite(observation.get("sharpness"), label="source sharpness")
    occlusion = _finite(observation.get("occlusion"), label="source occlusion")
    target = _finite(observation.get("target_confidence"), label="target confidence")
    review_eligible = (
        native_width >= required_width
        and native_height >= required_height
        and sharpness >= MIN_SOURCE_SHARPNESS
        and occlusion <= MAX_SOURCE_OCCLUSION
        and target >= MIN_TARGET_CONFIDENCE
        and quality >= DETAIL_QUALITY_THRESHOLD
    )
    return {
        "region": region,
        "image_sha256": image_sha,
        "width": 1024,
        "height": 1024,
        "native_crop_width": native_width,
        "native_crop_height": native_height,
        "keypoint_confidence": round(_mean_confidence(points), 4),
        "source_quality": quality,
        "review_eligible": review_eligible,
        "machine_asserts_anatomy_visible": False,
        "machine_asserts_rear_orientation": False,
    }


def _regions_for_frame(
    payload: Mapping[str, Any],
    *,
    frame: Path,
    observation: Mapping[str, Any],
    output_root: Path,
) -> dict[str, dict[str, Any]]:
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        return {}
    width, height = _png_size(frame)
    body = _triples(people[0].get("pose_keypoints_2d"), label="BODY_25", expected=25)
    result: dict[str, dict[str, Any]] = {}

    torso = _points_for_indices(body, TORSO_INDICES, width=width, height=height)
    if torso:
        result["torso_chest"] = _region_entry(
            region="torso_chest",
            frame=frame,
            crop=_crop_box(torso, width=width, height=height, pad_x=0.22, pad_y=0.18),
            points=torso,
            observation=observation,
            required_width=MIN_TORSO_NATIVE_WIDTH,
            required_height=MIN_TORSO_NATIVE_HEIGHT,
            require_full_body=False,
            output=output_root / "torso-chest.png",
        )

    waist = _points_for_indices(body, WAIST_INDICES, width=width, height=height)
    if waist:
        result["waist_hips"] = _region_entry(
            region="waist_hips",
            frame=frame,
            crop=_crop_box(waist, width=width, height=height, pad_x=0.20, pad_y=0.10),
            points=waist,
            observation=observation,
            required_width=MIN_WAIST_NATIVE_WIDTH,
            required_height=MIN_WAIST_NATIVE_HEIGHT,
            require_full_body=False,
            output=output_root / "waist-hips.png",
        )

    rear_required = _points_for_indices(body, REAR_REQUIRED_INDICES, width=width, height=height)
    all_body = _all_confident_body_points(body, width=width, height=height)
    if rear_required and len(all_body) >= 12:
        result["rear_body"] = _region_entry(
            region="rear_body",
            frame=frame,
            crop=_crop_box(all_body, width=width, height=height, pad_x=0.18, pad_y=0.08),
            points=rear_required,
            observation=observation,
            required_width=MIN_REAR_NATIVE_WIDTH,
            required_height=MIN_REAR_NATIVE_HEIGHT,
            require_full_body=True,
            output=output_root / "rear-body-candidate.png",
        )
    return result


def _row_score(row: Mapping[str, Any]) -> float:
    values = (
        _finite(row.get("target_confidence"), label="target confidence"),
        _finite(row.get("target_screen_fraction"), label="target screen fraction"),
        _finite(row.get("sharpness"), label="source sharpness"),
        1.0 - _finite(row.get("occlusion"), label="source occlusion"),
    )
    score = math.prod(values)
    # Unknown/no-face observations are useful rear-review candidates, but this
    # is ranking only. It never becomes rear orientation authority.
    face_visibility = _finite(row.get("face_visibility"), label="face visibility")
    view = str(row.get("view") or "")
    if view == "unknown" and face_visibility <= 0.25:
        score *= 1.08
    return score


def select_anatomy_frame_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        scene = str(row.get("scene_id") or "").strip()
        ordinal = row.get("source_ordinal")
        if not scene or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise PhotoIdentityAnatomyDiscoveryError("anatomy discovery observation source identity is invalid")
        grouped.setdefault(scene, []).append(row)
    ranked_scenes = sorted(grouped, key=lambda scene: (-max(_row_score(item) for item in grouped[scene]), scene))
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


def discover_anatomy_sources(
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
        raise PhotoIdentityAnatomyDiscoveryError(f"final hair/skin-enriched evidence is invalid: {exc}") from exc
    observations = _read_json(observations_path, label="Final photoidentity observations")
    source_count = int(report["source_files_scanned"])
    sources_by_ordinal, manifest_set_sha = _private_source_bindings(sweep_root, expected_count=source_count)

    private_root = sweep_root / "private-anatomy-source-candidates"
    if private_root.exists():
        raise PhotoIdentityAnatomyDiscoveryError("private anatomy source candidate workspace already exists")
    private_root.mkdir(parents=True, exist_ok=False)

    public_candidates: list[dict[str, Any]] = []
    private_candidates: list[dict[str, Any]] = []
    media_hash_cache: dict[str, str] = {}
    candidate_index = 0
    for row in select_anatomy_frame_candidates(list(observations["rows"])):
        ordinal = int(row["source_ordinal"])
        source_meta = sources_by_ordinal.get(ordinal)
        if not isinstance(source_meta, Mapping):
            raise PhotoIdentityAnatomyDiscoveryError("anatomy discovery row has no exact private source binding")
        scene_id = str(row["scene_id"])
        if str(source_meta.get("scene_id") or "") != scene_id:
            raise PhotoIdentityAnatomyDiscoveryError("anatomy discovery scene/source binding changed")
        source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
        midpoint = float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0
        candidate_index += 1
        candidate_root = private_root / f"candidate-{candidate_index:04d}"
        candidate_root.mkdir()
        frame = candidate_root / "source-frame.png"
        _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=midpoint, output=frame)
        payload = _run_openpose(frame=frame, distribution=distribution, openpose=openpose, wsl_exe=wsl_exe)
        regions = _regions_for_frame(payload, frame=frame, observation=row, output_root=candidate_root)
        if not regions:
            continue
        source_key = os.path.normcase(str(source))
        media_sha = media_hash_cache.get(source_key)
        if media_sha is None:
            media_sha = _sha256_file(source)
            media_hash_cache[source_key] = media_sha
        timestamp_ms = int(round(midpoint * 1000.0))
        candidate_seed = f"{scene_id}\n{ordinal}\n{timestamp_ms}\n{media_sha}".encode("utf-8")
        candidate_id = "anatomycand-" + hashlib.sha256(candidate_seed).hexdigest()[:32]
        public = {
            "candidate_id": candidate_id,
            "scene_id": scene_id,
            "source_ordinal": ordinal,
            "timestamp_ms": timestamp_ms,
            "source_media_sha256": media_sha,
            "source_frame_sha256": _sha256_file(frame),
            "observation_view_hint": str(row.get("view") or "unknown"),
            "observation_face_visibility": _finite(row.get("face_visibility"), label="face visibility"),
            "regions": {name: dict(value) for name, value in sorted(regions.items())},
        }
        private = {
            **public,
            "source_path": str(source),
            "candidate_directory": str(candidate_root),
            "region_images": {
                name: str(candidate_root / ("rear-body-candidate.png" if name == "rear_body" else name.replace("_", "-") + ".png"))
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
        "machine_anatomy_identity_authority": False,
        "machine_rear_orientation_authority": False,
        "human_source_review_required": True,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "human_review_render_permitted": False,
        "production_activation": False,
    }
    public_path = sweep_root / "anatomy-source-candidates.json"
    private_path = private_root / "private-candidate-index.json"
    _write_create_only(public_path, public_manifest)
    _write_create_only(
        private_path,
        {
            "format": "bodyrig-photoidentity-private-anatomy-source-index",
            "version": 1,
            "public_manifest_sha256": _sha256_file(public_path),
            "candidates": private_candidates,
        },
    )
    return {**public_manifest, "manifest": str(public_path), "private_index": str(private_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover source-grounded rear/torso/waist review crops without granting anatomy authority."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = discover_anatomy_sources(
            sweep_root=Path(args.sweep_root),
            ffmpeg=args.ffmpeg,
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, PhotoIdentityAnatomyDiscoveryError, PhotoIdentityOpenPoseRunnerError) as exc:
        print(f"BodyRig photoidentity anatomy source discovery: FAIL: {exc}", file=sys.stderr)
        return 1
    scenes = result["review_eligible_distinct_scenes"]
    print(
        "BodyRig photoidentity anatomy source discovery: PASS | "
        f"candidates={result['candidate_count']} | "
        f"rear-scenes={scenes['rear_body']} | torso-scenes={scenes['torso_chest']} | waist-scenes={scenes['waist_hips']}"
    )
    print(f"Candidate manifest: {result['manifest']}")
    print(f"Private source closeups: {result['private_index']}")
    print("Anatomy/rear authority: FALSE until explicit source-only human attestation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
