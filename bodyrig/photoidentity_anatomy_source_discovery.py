from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
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
CANDIDATE_RE = re.compile(r"^anatcand-[0-9a-f]{32}$")
REGIONS = ("rear_body", "torso_chest", "waist_hips")
MIN_TARGET_CONFIDENCE = 0.75
MIN_FULL_BODY_VISIBILITY = 0.72
MIN_SOURCE_SHARPNESS = 0.70
MAX_SOURCE_OCCLUSION = 0.18
MIN_POSE_CONFIDENCE = 0.20
MIN_TORSO_NATIVE_WIDTH = 260
MIN_TORSO_NATIVE_HEIGHT = 300
MIN_WAIST_NATIVE_WIDTH = 280
MIN_WAIST_NATIVE_HEIGHT = 260
MIN_REAR_NATIVE_WIDTH = 360
MIN_REAR_NATIVE_HEIGHT = 600
MAX_FRAMES_PER_SCENE = 6


class PhotoIdentityAnatomyDiscoveryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityAnatomyDiscoveryError(f"required source file is missing: {path}")
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
        raise PhotoIdentityAnatomyDiscoveryError(f"anatomy discovery output already exists: {path}")
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


def _latest_prior_bundle(sweep_root: Path) -> tuple[Path, Path, dict[str, Any]]:
    candidates = (
        sweep_root / "nail-attested-evidence",
        sweep_root / "human-parsing-evidence",
    )
    for root in candidates:
        observations = root / "photoidentity-observations.json"
        report = root / "photoidentity-evidence.json"
        if observations.is_file() and report.is_file():
            try:
                verified = validate_bundle(report, observations)
            except PhotoIdentityEvidenceError as exc:
                raise PhotoIdentityAnatomyDiscoveryError(f"prior photoidentity evidence is invalid: {exc}") from exc
            return observations, report, verified
    raise PhotoIdentityAnatomyDiscoveryError("no authoritative SCHP/nail-attested photoidentity bundle exists")


def _finite01(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentityAnatomyDiscoveryError(f"{label} is outside 0..1")
    return result


def _row_quality(row: Mapping[str, Any]) -> float:
    return min(
        _finite01(row.get("target_confidence"), label="target confidence"),
        _finite01(row.get("full_body_visibility"), label="full-body visibility"),
        _finite01(row.get("sharpness"), label="source sharpness"),
        1.0 - _finite01(row.get("occlusion"), label="source occlusion"),
    )


def _candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        scene = str(row.get("scene_id") or "").strip()
        ordinal = row.get("source_ordinal")
        if not scene or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise PhotoIdentityAnatomyDiscoveryError("photoidentity observation source identity is invalid")
        target = _finite01(row.get("target_confidence"), label="target confidence")
        full = _finite01(row.get("full_body_visibility"), label="full-body visibility")
        sharp = _finite01(row.get("sharpness"), label="source sharpness")
        occ = _finite01(row.get("occlusion"), label="source occlusion")
        if target < MIN_TARGET_CONFIDENCE or full < MIN_FULL_BODY_VISIBILITY or sharp < MIN_SOURCE_SHARPNESS or occ > MAX_SOURCE_OCCLUSION:
            continue
        grouped.setdefault(scene, []).append(row)
    result: list[dict[str, Any]] = []
    for scene in sorted(grouped):
        ranked = sorted(
            grouped[scene],
            key=lambda row: (-_row_quality(row), float(row.get("start_seconds", 0.0))),
        )
        result.extend(ranked[:MAX_FRAMES_PER_SCENE])
    return result


def _triples(payload: Mapping[str, Any]) -> list[tuple[float, float, float]] | None:
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        return None
    raw = people[0].get("pose_keypoints_2d")
    if not isinstance(raw, list) or len(raw) != 75:
        return None
    result: list[tuple[float, float, float]] = []
    try:
        for index in range(25):
            x, y, confidence = (float(value) for value in raw[index * 3 : index * 3 + 3])
            if not all(math.isfinite(value) for value in (x, y, confidence)) or not 0.0 <= confidence <= 1.0:
                return None
            result.append((x, y, confidence))
    except (TypeError, ValueError):
        return None
    return result


def _point(points: Sequence[tuple[float, float, float]], index: int) -> tuple[float, float] | None:
    x, y, confidence = points[index]
    if confidence < MIN_POSE_CONFIDENCE:
        return None
    return x, y


def _bounded_box(
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int] | None:
    if not all(math.isfinite(value) for value in (center_x, center_y, width, height)) or width <= 0 or height <= 0:
        return None
    x1 = max(0, int(math.floor(center_x - width / 2.0)))
    y1 = max(0, int(math.floor(center_y - height / 2.0)))
    x2 = min(frame_width, int(math.ceil(center_x + width / 2.0)))
    y2 = min(frame_height, int(math.ceil(center_y + height / 2.0)))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2 - x1, y2 - y1


def _boxes(points: Sequence[tuple[float, float, float]], width: int, height: int) -> dict[str, tuple[int, int, int, int]]:
    right_shoulder = _point(points, 2)
    left_shoulder = _point(points, 5)
    right_hip = _point(points, 9)
    left_hip = _point(points, 12)
    mid_hip = _point(points, 8)
    neck = _point(points, 1)
    right_knee = _point(points, 10)
    left_knee = _point(points, 13)
    confident = [(x, y) for x, y, confidence in points if confidence >= MIN_POSE_CONFIDENCE and 0 <= x < width and 0 <= y < height]
    result: dict[str, tuple[int, int, int, int]] = {}

    if right_shoulder and left_shoulder and right_hip and left_hip:
        sx = (right_shoulder[0] + left_shoulder[0]) / 2.0
        sy = (right_shoulder[1] + left_shoulder[1]) / 2.0
        hx = (right_hip[0] + left_hip[0]) / 2.0
        hy = (right_hip[1] + left_hip[1]) / 2.0
        shoulder_span = math.dist(right_shoulder, left_shoulder)
        hip_span = math.dist(right_hip, left_hip)
        torso_height = max(abs(hy - sy), max(shoulder_span, hip_span) * 0.8)
        torso = _bounded_box(
            center_x=(sx + hx) / 2.0,
            center_y=(sy + hy) / 2.0,
            width=max(shoulder_span, hip_span) * 1.55,
            height=torso_height * 1.45,
            frame_width=width,
            frame_height=height,
        )
        if torso:
            result["torso_chest"] = torso

    if right_hip and left_hip:
        hx = (right_hip[0] + left_hip[0]) / 2.0
        hy = (right_hip[1] + left_hip[1]) / 2.0
        hip_span = max(math.dist(right_hip, left_hip), 40.0)
        vertical = hip_span * 1.55
        if right_knee and left_knee:
            knee_y = (right_knee[1] + left_knee[1]) / 2.0
            vertical = max(vertical, abs(knee_y - hy) * 0.75)
        waist = _bounded_box(
            center_x=hx,
            center_y=hy + vertical * 0.08,
            width=hip_span * 2.05,
            height=vertical * 1.35,
            frame_width=width,
            frame_height=height,
        )
        if waist:
            result["waist_hips"] = waist

    if len(confident) >= 10:
        xs = [item[0] for item in confident]
        ys = [item[1] for item in confident]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        pose_width = max(x2 - x1, 80.0)
        pose_height = max(y2 - y1, 160.0)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        if neck and mid_hip:
            center_x = (center_x + (neck[0] + mid_hip[0]) / 2.0) / 2.0
        rear = _bounded_box(
            center_x=center_x,
            center_y=center_y,
            width=pose_width * 1.45,
            height=pose_height * 1.28,
            frame_width=width,
            frame_height=height,
        )
        if rear:
            result["rear_body"] = rear
    return result


def _crop_review_image(frame: Path, box: tuple[int, int, int, int], output: Path) -> tuple[int, int, str]:
    try:
        with Image.open(frame) as source:
            source.load()
            x, y, width, height = box
            crop = source.crop((x, y, x + width, y + height)).convert("RGB")
            crop.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1024, 1024), (0, 0, 0))
            offset = ((1024 - crop.width) // 2, (1024 - crop.height) // 2)
            canvas.paste(crop, offset)
            canvas.save(output, format="PNG", compress_level=4)
    except Exception as exc:
        raise PhotoIdentityAnatomyDiscoveryError("could not create anatomy source review crop") from exc
    return box[2], box[3], _sha256_file(output)


def _region_quality(row: Mapping[str, Any], region: str, native_width: int, native_height: int) -> float:
    base = _row_quality(row)
    if region == "torso_chest":
        resolution = min(1.0, native_width / MIN_TORSO_NATIVE_WIDTH, native_height / MIN_TORSO_NATIVE_HEIGHT)
    elif region == "waist_hips":
        resolution = min(1.0, native_width / MIN_WAIST_NATIVE_WIDTH, native_height / MIN_WAIST_NATIVE_HEIGHT)
    else:
        resolution = min(1.0, native_width / MIN_REAR_NATIVE_WIDTH, native_height / MIN_REAR_NATIVE_HEIGHT)
    return round(min(base, resolution), 4)


def discover_anatomy_sources(
    *,
    sweep_root: Path,
    ffmpeg: str,
    distribution: str,
    openpose: str,
    wsl_exe: str,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    if not sweep_root.is_dir():
        raise PhotoIdentityAnatomyDiscoveryError("photoidentity sweep root is missing")
    public_path = sweep_root / "anatomy-source-candidates.json"
    private_root = sweep_root / "private-anatomy-source-candidates"
    if public_path.exists() or private_root.exists():
        raise PhotoIdentityAnatomyDiscoveryError("anatomy source discovery is create-only per sweep")

    observations_path, report_path, report = _latest_prior_bundle(sweep_root)
    observations = _read_json(observations_path, label="Prior photoidentity observations")
    source_count = int(report["source_files_scanned"])
    try:
        sources_by_ordinal, private_manifest_set_sha256 = _private_source_bindings(sweep_root, expected_count=source_count)
    except Exception as exc:
        raise PhotoIdentityAnatomyDiscoveryError(f"private source authority changed before anatomy discovery: {exc}") from exc

    rows = _candidate_rows(list(observations.get("rows") or []))
    private_root.mkdir(parents=True, exist_ok=False)
    public_candidates: list[dict[str, Any]] = []
    private_candidates: list[dict[str, Any]] = []
    try:
        for number, row in enumerate(rows, start=1):
            ordinal = int(row["source_ordinal"])
            source_meta = sources_by_ordinal.get(ordinal)
            if not isinstance(source_meta, Mapping):
                raise PhotoIdentityAnatomyDiscoveryError("anatomy candidate source ordinal has no private binding")
            source = Path(str(source_meta.get("path") or "")).expanduser().resolve()
            midpoint = float(row["start_seconds"]) + float(row["duration_seconds"]) / 2.0
            candidate_seed = f"{report['performer_id']}\n{row['scene_id']}\n{ordinal}\n{midpoint:.3f}\n{number}"
            candidate_id = "anatcand-" + hashlib.sha256(candidate_seed.encode("utf-8")).hexdigest()[:32]
            if not CANDIDATE_RE.fullmatch(candidate_id):
                raise PhotoIdentityAnatomyDiscoveryError("generated anatomy candidate id is invalid")
            candidate_dir = private_root / candidate_id
            candidate_dir.mkdir()
            frame = candidate_dir / "source-frame.png"
            _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=midpoint, output=frame)
            frame_width, frame_height = _png_size(frame)
            payload = _run_openpose(
                frame=frame,
                distribution=distribution,
                openpose=openpose,
                wsl_exe=wsl_exe,
            )
            points = _triples(payload)
            if points is None:
                shutil.rmtree(candidate_dir, ignore_errors=True)
                continue
            boxes = _boxes(points, frame_width, frame_height)
            if not boxes:
                shutil.rmtree(candidate_dir, ignore_errors=True)
                continue

            public_regions: dict[str, dict[str, Any]] = {}
            private_regions: dict[str, str] = {}
            for region in REGIONS:
                box = boxes.get(region)
                if box is None:
                    continue
                output = candidate_dir / f"{region}.png"
                native_width, native_height, image_sha = _crop_review_image(frame, box, output)
                quality = _region_quality(row, region, native_width, native_height)
                public_regions[region] = {
                    "image_sha256": image_sha,
                    "native_crop_width": native_width,
                    "native_crop_height": native_height,
                    "source_quality": quality,
                    "review_eligible": quality >= DETAIL_QUALITY_THRESHOLD,
                }
                private_regions[region] = str(output)
            if not public_regions:
                shutil.rmtree(candidate_dir, ignore_errors=True)
                continue

            source_sha = _sha256_file(source)
            frame_sha = _sha256_file(frame)
            public_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "scene_id": str(row["scene_id"]),
                    "source_ordinal": ordinal,
                    "timestamp_ms": int(round(midpoint * 1000.0)),
                    "source_media_sha256": source_sha,
                    "decoded_frame_sha256": frame_sha,
                    "observation_quality": _row_quality(row),
                    "regions": public_regions,
                }
            )
            private_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "scene_id": str(row["scene_id"]),
                    "source_media_sha256": source_sha,
                    "source_path": str(source),
                    "decoded_frame": str(frame),
                    "region_images": private_regions,
                }
            )

        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "performer_id": str(report["performer_id"]),
            "bodyrig_revision": str(report["bodyrig_revision"]),
            "input_observation_evidence_sha256": _sha256_file(observations_path),
            "input_sufficiency_report_sha256": _sha256_file(report_path),
            "private_source_manifest_set_sha256": private_manifest_set_sha256,
            "localizer": {"adapter": OPENPOSE_ADAPTER, "revision": OPENPOSE_REVISION},
            "candidate_count": len(public_candidates),
            "candidates": public_candidates,
            "source_paths_persisted": False,
            "machine_anatomy_identity_authority": False,
            "machine_rear_orientation_authority": False,
            "generic_guessing_permitted": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        _write_create_only(public_path, manifest)
        private_index = {
            "format": "bodyrig-photoidentity-private-anatomy-source-index",
            "version": 1,
            "public_manifest_sha256": _sha256_file(public_path),
            "candidates": private_candidates,
        }
        _write_create_only(private_root / "private-candidate-index.json", private_index)
        return {**manifest, "manifest": str(public_path), "private_root": str(private_root)}
    except Exception:
        if not public_path.exists():
            shutil.rmtree(private_root, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare source-only rear/torso/waist review candidates without granting anatomy identity authority."
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
        print(f"BodyRig anatomy source discovery: FAIL: {exc}", file=sys.stderr)
        return 1
    eligible = {region: 0 for region in REGIONS}
    for candidate in result["candidates"]:
        for region, entry in candidate["regions"].items():
            if entry.get("review_eligible") is True:
                eligible[region] += 1
    print(
        "BodyRig anatomy source discovery: PASS | "
        f"candidates={result['candidate_count']} | "
        f"rear={eligible['rear_body']} | torso={eligible['torso_chest']} | waist={eligible['waist_hips']}"
    )
    print(f"Manifest: {result['manifest']}")
    print("Machine discovery has no rear-orientation or anatomy identity authority; source review is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
