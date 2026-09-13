from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_source_capture import (
    CAPTURE_ID_RE,
    FORMAT as CAPTURE_FORMAT,
    POLICY_REVISION as CAPTURE_POLICY_REVISION,
    REQUIRED_REGIONS,
    VERSION as CAPTURE_VERSION,
    HandsFeetNailsSourceCaptureError,
    _source_authority,
    capture_dir,
    read_source_capture,
)
from .photoidentity_nail_landmarks import (
    FORMAT as PROJECTION_FORMAT,
    POLICY_REVISION as PROJECTION_POLICY_REVISION,
    VERSION as PROJECTION_VERSION,
    PhotoIdentityNailLandmarkError,
    normalized_crop_to_pixels,
    project_nail_landmarks_to_crop,
)
from .photoidentity_openpose_detail import ADAPTER as OPENPOSE_ADAPTER
from .photoidentity_openpose_detail import REVISION as OPENPOSE_REVISION
from .photoidentity_openpose_runner import (
    PhotoIdentityOpenPoseRunnerError,
    _extract_frame,
    _png_size,
    _run_openpose,
)

FORMAT = "bodyrig-hands-feet-nails-landmark-evidence"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-landmark-evidence-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_REGION_TO_SEMANTIC = {
    "left_hand": "left_fingernails",
    "right_hand": "right_fingernails",
    "left_foot": "left_toenails",
    "right_foot": "right_toenails",
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "person_id",
    "body_revision",
    "capture_id",
    "source_bodyrig_revision",
    "evidence_bodyrig_revision",
    "source_capture_sha256",
    "source_manifest_sha256",
    "frame_ffmpeg_version",
    "openpose_adapter",
    "openpose_revision",
    "region_count",
    "regions",
    "all_regions_application_ready",
    "source_paths_persisted",
    "package_application_authority",
    "human_review_required",
    "production_activation",
}
REGION_FIELDS = {
    "capture_region",
    "semantic_region",
    "scene_id",
    "source_media_sha256",
    "timestamp_ms",
    "crop_norm",
    "crop_px",
    "crop_projection_method",
    "source_frame_sha256",
    "source_frame_width",
    "source_frame_height",
    "closeup_image_sha256",
    "projection",
}
PROJECTION_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "region",
    "canvas_width",
    "canvas_height",
    "source_crop_px",
    "landmarks",
    "required_landmark_count",
    "observed_landmark_count",
    "application_ready",
    "source_coordinate_authority",
    "package_application_authority",
    "human_review_required",
    "production_activation",
}


class HandsFeetNailsLandmarkEvidenceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise HandsFeetNailsLandmarkEvidenceError(f"landmark evidence input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HandsFeetNailsLandmarkEvidenceError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HandsFeetNailsLandmarkEvidenceError(f"{label} is not a canonical Git SHA")
    return text


def _ffmpeg_version(ffmpeg: str) -> str:
    try:
        completed = subprocess.run(
            [ffmpeg, "-version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandsFeetNailsLandmarkEvidenceError("ffmpeg is unavailable for HFN landmark evidence") from exc
    if completed.returncode != 0:
        raise HandsFeetNailsLandmarkEvidenceError("ffmpeg version probe failed for HFN landmark evidence")
    first = (completed.stdout or "").splitlines()
    value = first[0].strip() if first else ""
    if not value.lower().startswith("ffmpeg version ") or len(value) > 512:
        raise HandsFeetNailsLandmarkEvidenceError("ffmpeg version output is invalid")
    return value


def _strict_capture(value: Mapping[str, Any]) -> dict[str, Any]:
    version = value.get("version")
    if (
        value.get("format") != CAPTURE_FORMAT
        or isinstance(version, bool)
        or version != CAPTURE_VERSION
        or value.get("policy_revision") != CAPTURE_POLICY_REVISION
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN source capture format/version/policy is not strict v1 authority")
    return dict(value)


def _validate_projection(value: Mapping[str, Any], *, semantic_region: str, crop_px: list[int]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PROJECTION_FIELDS:
        raise HandsFeetNailsLandmarkEvidenceError("HFN nail projection fields are not canonical")
    version = value.get("version")
    if (
        value.get("format") != PROJECTION_FORMAT
        or isinstance(version, bool)
        or version != PROJECTION_VERSION
        or value.get("policy_revision") != PROJECTION_POLICY_REVISION
        or value.get("region") != semantic_region
        or value.get("source_crop_px") != crop_px
        or value.get("canvas_width") != 1024
        or value.get("canvas_height") != 1024
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN nail projection format/version/crop scope mismatch")
    if value.get("source_coordinate_authority") != "openpose-semantic-landmarks-explicit-crop":
        raise HandsFeetNailsLandmarkEvidenceError("HFN nail projection does not use explicit M2 crop coordinates")
    if (
        value.get("package_application_authority") is not False
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN nail projection crossed its evidence-only authority boundary")
    required = value.get("required_landmark_count")
    observed = value.get("observed_landmark_count")
    landmarks = value.get("landmarks")
    if (
        isinstance(required, bool)
        or not isinstance(required, int)
        or required < 1
        or isinstance(observed, bool)
        or not isinstance(observed, int)
        or observed < 0
        or observed > required
        or not isinstance(landmarks, Mapping)
        or observed != len(landmarks)
        or value.get("application_ready") is not (observed == required)
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN nail projection readiness is inconsistent")
    return dict(value)


def evidence_path(
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    evidence_bodyrig_revision: str,
) -> Path:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    revision = _revision(evidence_bodyrig_revision, label="evidence BodyRig revision")
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body) or not CAPTURE_ID_RE.fullmatch(capture):
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark evidence identity is not canonical")
    return (
        Path(root).expanduser().resolve()
        / "hands-feet-nails-landmark-evidence"
        / person
        / body
        / capture
        / f"{revision}.json"
    )


def validate_landmark_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark evidence fields are not canonical")
    version = value.get("version")
    person = str(value.get("person_id") or "").strip().lower()
    body = str(value.get("body_revision") or "").strip().lower()
    capture = str(value.get("capture_id") or "").strip().lower()
    source_revision = _revision(value.get("source_bodyrig_revision"), label="source BodyRig revision")
    evidence_revision = _revision(value.get("evidence_bodyrig_revision"), label="evidence BodyRig revision")
    if (
        value.get("format") != FORMAT
        or isinstance(version, bool)
        or version != VERSION
        or value.get("policy_revision") != POLICY_REVISION
        or not PERSON_RE.fullmatch(person)
        or not BODY_RE.fullmatch(body)
        or not CAPTURE_ID_RE.fullmatch(capture)
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark evidence format/version/identity mismatch")
    _sha(value.get("source_capture_sha256"), label="source capture SHA-256")
    _sha(value.get("source_manifest_sha256"), label="source manifest SHA-256")
    ffmpeg_version = str(value.get("frame_ffmpeg_version") or "")
    if not ffmpeg_version.lower().startswith("ffmpeg version ") or len(ffmpeg_version) > 512:
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark frame ffmpeg version is invalid")
    if value.get("openpose_adapter") != OPENPOSE_ADAPTER or value.get("openpose_revision") != OPENPOSE_REVISION:
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark OpenPose authority mismatch")

    regions = value.get("regions")
    count = value.get("region_count")
    if (
        not isinstance(regions, Mapping)
        or set(regions) != set(REQUIRED_REGIONS)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(REQUIRED_REGIONS)
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark region set is not canonical")

    normalized_regions: dict[str, dict[str, Any]] = {}
    for capture_region in REQUIRED_REGIONS:
        raw = regions.get(capture_region)
        if not isinstance(raw, Mapping) or set(raw) != REGION_FIELDS:
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN landmark fields are invalid")
        semantic = CAPTURE_REGION_TO_SEMANTIC[capture_region]
        if raw.get("capture_region") != capture_region or raw.get("semantic_region") != semantic:
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN landmark scope mismatch")
        scene = str(raw.get("scene_id") or "").strip()
        timestamp = raw.get("timestamp_ms")
        crop_norm = raw.get("crop_norm")
        crop_px = raw.get("crop_px")
        if not scene or isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN landmark source identity is invalid")
        if not isinstance(crop_norm, list) or len(crop_norm) != 4:
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN normalized crop is invalid")
        if (
            not isinstance(crop_px, list)
            or len(crop_px) != 4
            or any(isinstance(item, bool) or not isinstance(item, int) for item in crop_px)
        ):
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN pixel crop is invalid")
        width = raw.get("source_frame_width")
        height = raw.get("source_frame_height")
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width < 1
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height < 1
        ):
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} source frame dimensions are invalid")
        expected_crop = list(normalized_crop_to_pixels(crop_norm, frame_width=width, frame_height=height))
        if crop_px != expected_crop or raw.get("crop_projection_method") != "normalized-source-crop-round-v1":
            raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} HFN crop projection is inconsistent")
        normalized_regions[capture_region] = {
            **dict(raw),
            "source_media_sha256": _sha(raw.get("source_media_sha256"), label=f"{capture_region} source media SHA-256"),
            "source_frame_sha256": _sha(raw.get("source_frame_sha256"), label=f"{capture_region} source frame SHA-256"),
            "closeup_image_sha256": _sha(raw.get("closeup_image_sha256"), label=f"{capture_region} closeup image SHA-256"),
            "projection": _validate_projection(raw.get("projection"), semantic_region=semantic, crop_px=crop_px),
        }

    expected_ready = all(item["projection"]["application_ready"] is True for item in normalized_regions.values())
    if value.get("all_regions_application_ready") is not expected_ready:
        raise HandsFeetNailsLandmarkEvidenceError("HFN aggregate landmark readiness is inconsistent")
    if (
        value.get("source_paths_persisted") is not False
        or value.get("package_application_authority") is not False
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark evidence crossed its evidence-only authority boundary")
    return {
        **dict(value),
        "person_id": person,
        "body_revision": body,
        "capture_id": capture,
        "source_bodyrig_revision": source_revision,
        "evidence_bodyrig_revision": evidence_revision,
        "regions": normalized_regions,
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise HandsFeetNailsLandmarkEvidenceError(f"HFN landmark evidence already exists: {path}")
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


def build_landmark_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    evidence_bodyrig_revision: str,
    ffmpeg: str,
    distribution: str,
    openpose: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture_name = str(capture_id or "").strip().lower()
    evidence_revision = _revision(evidence_bodyrig_revision, label="evidence BodyRig revision")
    try:
        capture = _strict_capture(
            read_source_capture(
                root_path,
                person,
                body_revision=body,
                capture_id=capture_name,
            )
        )
        source = _source_authority(root_path, person, body)
    except HandsFeetNailsSourceCaptureError as exc:
        raise HandsFeetNailsLandmarkEvidenceError(str(exc)) from exc

    capture_root = capture_dir(root_path, person, body, capture_name)
    capture_manifest = capture_root / "source-capture.json"
    capture_sha = _sha256_file(capture_manifest)
    source_revision = _revision(capture.get("bodyrig_revision"), label="source BodyRig revision")
    source_manifest_sha = _sha(capture.get("source_manifest_sha256"), label="source manifest SHA-256")
    if source.get("manifest_sha256") != source_manifest_sha:
        raise HandsFeetNailsLandmarkEvidenceError("HFN landmark source manifest changed after capture")
    frame_ffmpeg_version = _ffmpeg_version(ffmpeg)

    frame_cache: dict[tuple[str, int], tuple[Path, dict[str, Any], int, int, str]] = {}
    region_evidence: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="bodyrig-hfn-landmarks-") as temp_name:
        temp_root = Path(temp_name)
        for capture_region in REQUIRED_REGIONS:
            item = capture["regions"][capture_region]
            scene_id = str(item["scene_id"])
            timestamp_ms = int(item["timestamp_ms"])
            media = source["by_scene"].get(scene_id)
            if not isinstance(media, Mapping):
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} source scene disappeared from body authority")
            expected_media_sha = _sha(item.get("source_media_sha256"), label=f"{capture_region} source media SHA-256")
            if media.get("sha256") != expected_media_sha:
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} source media identity changed after capture")
            source_path = Path(str(media.get("path") or "")).expanduser().resolve()
            if _sha256_file(source_path) != expected_media_sha:
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} source media bytes changed after capture")

            cache_key = (scene_id, timestamp_ms)
            cached = frame_cache.get(cache_key)
            if cached is None:
                frame = temp_root / f"frame-{len(frame_cache):04d}.png"
                _extract_frame(
                    ffmpeg=ffmpeg,
                    source=source_path,
                    timestamp=timestamp_ms / 1000.0,
                    output=frame,
                )
                width, height = _png_size(frame)
                payload = _run_openpose(
                    frame=frame,
                    distribution=distribution,
                    openpose=openpose,
                    wsl_exe=wsl_exe,
                )
                cached = (frame, payload, width, height, _sha256_file(frame))
                frame_cache[cache_key] = cached
            frame, payload, width, height, frame_sha = cached

            closeup_name = str(item["image"])
            closeup = (capture_root / closeup_name).resolve()
            try:
                closeup.relative_to(capture_root.resolve())
            except ValueError as exc:
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} closeup escaped capture root") from exc
            closeup_sha = _sha256_file(closeup)
            if closeup_sha != _sha(item.get("image_sha256"), label=f"{capture_region} closeup SHA-256"):
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} closeup bytes changed after capture validation")

            crop_norm = list(item["crop_norm"])
            crop_px = list(normalized_crop_to_pixels(crop_norm, frame_width=width, frame_height=height))
            semantic_region = CAPTURE_REGION_TO_SEMANTIC[capture_region]
            try:
                projection = project_nail_landmarks_to_crop(
                    payload,
                    region=semantic_region,
                    frame_width=width,
                    frame_height=height,
                    crop_px=crop_px,
                    upscale_to_canvas=True,
                )
            except PhotoIdentityNailLandmarkError as exc:
                raise HandsFeetNailsLandmarkEvidenceError(f"{capture_region} landmark projection failed: {exc}") from exc

            region_evidence[capture_region] = {
                "capture_region": capture_region,
                "semantic_region": semantic_region,
                "scene_id": scene_id,
                "source_media_sha256": expected_media_sha,
                "timestamp_ms": timestamp_ms,
                "crop_norm": crop_norm,
                "crop_px": crop_px,
                "crop_projection_method": "normalized-source-crop-round-v1",
                "source_frame_sha256": frame_sha,
                "source_frame_width": width,
                "source_frame_height": height,
                "closeup_image_sha256": closeup_sha,
                "projection": _validate_projection(projection, semantic_region=semantic_region, crop_px=crop_px),
            }

    value = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "person_id": person,
        "body_revision": body,
        "capture_id": capture_name,
        "source_bodyrig_revision": source_revision,
        "evidence_bodyrig_revision": evidence_revision,
        "source_capture_sha256": capture_sha,
        "source_manifest_sha256": source_manifest_sha,
        "frame_ffmpeg_version": frame_ffmpeg_version,
        "openpose_adapter": OPENPOSE_ADAPTER,
        "openpose_revision": OPENPOSE_REVISION,
        "region_count": len(region_evidence),
        "regions": region_evidence,
        "all_regions_application_ready": all(
            item["projection"]["application_ready"] is True for item in region_evidence.values()
        ),
        "source_paths_persisted": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }
    validated = validate_landmark_evidence(value)
    output = evidence_path(root_path, person, body, capture_name, evidence_revision)
    _write_create_only(output, validated)
    return {**validated, "manifest": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Person/body-bound HFN OpenPose landmark evidence from an exact M2 source capture."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = build_landmark_evidence(
            args.root,
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            evidence_bodyrig_revision=args.bodyrig_revision,
            ffmpeg=args.ffmpeg,
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (
        OSError,
        HandsFeetNailsLandmarkEvidenceError,
        PhotoIdentityOpenPoseRunnerError,
    ) as exc:
        print(f"BodyRig HFN landmark evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "BodyRig HFN landmark evidence: PASS | "
        f"person={result['person_id']} | body={result['body_revision']} | "
        f"capture={result['capture_id']} | application-ready={str(result['all_regions_application_ready']).lower()} | "
        "package-authority=false"
    )
    print(f"HFN landmark evidence: {result['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
