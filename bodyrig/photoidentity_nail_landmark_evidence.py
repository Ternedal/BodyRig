from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_nail_landmarks import (
    FORMAT as PROJECTION_FORMAT,
    POLICY_REVISION as PROJECTION_POLICY_REVISION,
    VERSION as PROJECTION_VERSION,
    HAND_LABELS,
    REGIONS,
    TOE_LABELS,
    PhotoIdentityNailLandmarkError,
    project_nail_landmarks,
)
from .photoidentity_nail_source_attestation import (
    PhotoIdentityNailAttestationError,
    _candidate_maps,
    _load_discovery,
)
from .photoidentity_openpose_detail import ADAPTER as OPENPOSE_ADAPTER
from .photoidentity_openpose_detail import REVISION as OPENPOSE_REVISION
from .photoidentity_openpose_runner import PhotoIdentityOpenPoseRunnerError, _png_size, _run_openpose

FORMAT = "bodyrig-photoidentity-nail-landmark-evidence"
VERSION = 1
POLICY_REVISION = "photoidentity-nail-landmark-evidence-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
CANDIDATE_RE = re.compile(r"^nailcand-[0-9a-f]{32}$")
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "performer_id",
    "bodyrig_revision",
    "input_discovery_sha256",
    "private_source_manifest_set_sha256",
    "openpose_adapter",
    "openpose_revision",
    "record_count",
    "records",
    "source_paths_persisted",
    "package_application_authority",
    "human_review_required",
    "production_activation",
}
RECORD_FIELDS = {
    "candidate_id",
    "region",
    "scene_id",
    "source_media_sha256",
    "source_frame_sha256",
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
LANDMARK_FIELDS = {"x_norm", "y_norm", "confidence"}


class PhotoIdentityNailLandmarkEvidenceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityNailLandmarkEvidenceError(f"landmark evidence input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise PhotoIdentityNailLandmarkEvidenceError(f"{label} is not a canonical SHA-256")
    return text


def _unit(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityNailLandmarkEvidenceError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentityNailLandmarkEvidenceError(f"{label} is outside 0..1")
    return result


def _validate_projection(value: Mapping[str, Any], *, region: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PROJECTION_FIELDS:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark projection fields are not canonical")
    version = value.get("version")
    if (
        value.get("format") != PROJECTION_FORMAT
        or isinstance(version, bool)
        or version != PROJECTION_VERSION
        or value.get("policy_revision") != PROJECTION_POLICY_REVISION
        or value.get("region") != region
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark projection format/version/scope mismatch")
    if value.get("canvas_width") != 1024 or value.get("canvas_height") != 1024:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark projection canvas is not canonical")

    crop = value.get("source_crop_px")
    if (
        not isinstance(crop, list)
        or len(crop) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in crop)
        or crop[0] < 0
        or crop[1] < 0
        or crop[2] <= crop[0]
        or crop[3] <= crop[1]
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark source crop is invalid")

    landmarks = value.get("landmarks")
    if not isinstance(landmarks, Mapping):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark map is invalid")
    allowed = set(HAND_LABELS if region.endswith("fingernails") else TOE_LABELS)
    if not set(landmarks) <= allowed:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark semantic labels are invalid")

    normalized: dict[str, dict[str, float]] = {}
    for label, raw in landmarks.items():
        if not isinstance(raw, Mapping) or set(raw) != LANDMARK_FIELDS:
            raise PhotoIdentityNailLandmarkEvidenceError(f"{label} nail landmark fields are invalid")
        normalized[str(label)] = {
            "x_norm": _unit(raw.get("x_norm"), label=f"{label} x_norm"),
            "y_norm": _unit(raw.get("y_norm"), label=f"{label} y_norm"),
            "confidence": _unit(raw.get("confidence"), label=f"{label} confidence"),
        }

    required = value.get("required_landmark_count")
    observed = value.get("observed_landmark_count")
    expected_required = len(allowed)
    if (
        isinstance(required, bool)
        or not isinstance(required, int)
        or required != expected_required
        or isinstance(observed, bool)
        or not isinstance(observed, int)
        or observed != len(normalized)
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark counts are inconsistent")
    expected_ready = observed == required
    if value.get("application_ready") is not expected_ready:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark application readiness is inconsistent")
    if (
        value.get("source_coordinate_authority") != "openpose-semantic-landmarks"
        or value.get("package_application_authority") is not False
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark projection crossed its evidence-only authority boundary")
    return {**dict(value), "landmarks": normalized}


def validate_landmark_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence fields are not canonical")
    version = value.get("version")
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if (
        value.get("format") != FORMAT
        or isinstance(version, bool)
        or version != VERSION
        or value.get("policy_revision") != POLICY_REVISION
        or not GIT_RE.fullmatch(revision)
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence format/version/revision mismatch")

    performer = str(value.get("performer_id") or "").strip()
    if not performer or len(performer) > 256:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence performer id is invalid")
    _sha(value.get("input_discovery_sha256"), label="input discovery SHA-256")
    _sha(value.get("private_source_manifest_set_sha256"), label="private source manifest set SHA-256")
    if value.get("openpose_adapter") != OPENPOSE_ADAPTER or value.get("openpose_revision") != OPENPOSE_REVISION:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence OpenPose authority mismatch")

    records = value.get("records")
    count = value.get("record_count")
    if (
        not isinstance(records, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        or count != len(records)
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence record count is invalid")

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in records:
        if not isinstance(raw, Mapping) or set(raw) != RECORD_FIELDS:
            raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence record fields are invalid")
        candidate_id = str(raw.get("candidate_id") or "").strip().lower()
        region = str(raw.get("region") or "").strip().lower()
        scene_id = str(raw.get("scene_id") or "").strip()
        if not CANDIDATE_RE.fullmatch(candidate_id) or region not in REGIONS or not scene_id:
            raise PhotoIdentityNailLandmarkEvidenceError("nail landmark record identity is invalid")
        key = (candidate_id, region)
        if key in seen:
            raise PhotoIdentityNailLandmarkEvidenceError("duplicate nail landmark record")
        seen.add(key)
        normalized.append(
            {
                **dict(raw),
                "candidate_id": candidate_id,
                "region": region,
                "source_media_sha256": _sha(raw.get("source_media_sha256"), label="source media SHA-256"),
                "source_frame_sha256": _sha(raw.get("source_frame_sha256"), label="source frame SHA-256"),
                "closeup_image_sha256": _sha(raw.get("closeup_image_sha256"), label="closeup image SHA-256"),
                "projection": _validate_projection(raw.get("projection"), region=region),
            }
        )

    if (
        value.get("source_paths_persisted") is not False
        or value.get("package_application_authority") is not False
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence crossed its evidence-only authority boundary")
    return {
        **dict(value),
        "bodyrig_revision": revision,
        "performer_id": performer,
        "records": normalized,
    }


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityNailLandmarkEvidenceError(f"nail landmark evidence already exists: {path}")
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
    *,
    sweep_root: Path,
    distribution: str,
    openpose: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    root = sweep_root.expanduser().resolve()
    try:
        public_path, public, _private_path, private = _load_discovery(root)
        public_map, private_map = _candidate_maps(public, private)
    except PhotoIdentityNailAttestationError as exc:
        raise PhotoIdentityNailLandmarkEvidenceError(str(exc)) from exc

    if public.get("openpose_adapter") != OPENPOSE_ADAPTER or public.get("openpose_revision") != OPENPOSE_REVISION:
        raise PhotoIdentityNailLandmarkEvidenceError("nail discovery was produced by a different OpenPose authority")
    revision = str(public.get("bodyrig_revision") or "").strip().lower()
    if not GIT_RE.fullmatch(revision):
        raise PhotoIdentityNailLandmarkEvidenceError("nail discovery BodyRig revision is invalid")
    manifest_set_sha = _sha(public.get("private_source_manifest_set_sha256"), label="private source manifest set SHA-256")
    private_root = (root / "private-nail-source-candidates").resolve()

    records: list[dict[str, Any]] = []
    for candidate_id in sorted(public_map):
        public_candidate = public_map[candidate_id]
        private_candidate = private_map[candidate_id]
        if (
            public_candidate.get("scene_id") != private_candidate.get("scene_id")
            or public_candidate.get("source_media_sha256") != private_candidate.get("source_media_sha256")
            or public_candidate.get("source_frame_sha256") != private_candidate.get("source_frame_sha256")
        ):
            raise PhotoIdentityNailLandmarkEvidenceError("public/private nail candidate identity changed")

        expected_media_sha = _sha(public_candidate.get("source_media_sha256"), label="source media SHA-256")
        source_path = Path(str(private_candidate.get("source_path") or "")).expanduser().resolve()
        if _sha256_file(source_path) != expected_media_sha:
            raise PhotoIdentityNailLandmarkEvidenceError("source media bytes changed after nail discovery")

        candidate_root = Path(str(private_candidate.get("candidate_directory") or "")).expanduser().resolve()
        try:
            candidate_root.relative_to(private_root)
        except ValueError as exc:
            raise PhotoIdentityNailLandmarkEvidenceError("nail candidate directory escaped private discovery root") from exc
        frame = candidate_root / "source-frame.png"
        frame_sha = _sha256_file(frame)
        expected_frame_sha = _sha(public_candidate.get("source_frame_sha256"), label="candidate source frame SHA-256")
        if frame_sha != expected_frame_sha:
            raise PhotoIdentityNailLandmarkEvidenceError("candidate source-frame bytes changed after discovery")

        width, height = _png_size(frame)
        payload = _run_openpose(frame=frame, distribution=distribution, openpose=openpose, wsl_exe=wsl_exe)
        regions = public_candidate.get("regions")
        private_images = private_candidate.get("region_images")
        if not isinstance(regions, Mapping) or not isinstance(private_images, Mapping):
            raise PhotoIdentityNailLandmarkEvidenceError("nail candidate region bindings are invalid")

        for region in sorted(regions):
            if region not in REGIONS:
                raise PhotoIdentityNailLandmarkEvidenceError("nail candidate contains unknown region")
            entry = regions.get(region)
            image_value = private_images.get(region)
            if not isinstance(entry, Mapping) or not isinstance(image_value, str):
                raise PhotoIdentityNailLandmarkEvidenceError("nail candidate region image binding is invalid")
            image = Path(image_value).expanduser().resolve()
            try:
                image.relative_to(candidate_root)
            except ValueError as exc:
                raise PhotoIdentityNailLandmarkEvidenceError("nail closeup escaped its candidate directory") from exc
            image_sha = _sha256_file(image)
            if image_sha != _sha(entry.get("image_sha256"), label=f"{region} closeup SHA-256"):
                raise PhotoIdentityNailLandmarkEvidenceError("nail closeup bytes changed after discovery")

            try:
                projection = project_nail_landmarks(
                    payload,
                    region=region,
                    frame_width=width,
                    frame_height=height,
                )
            except PhotoIdentityNailLandmarkError as exc:
                raise PhotoIdentityNailLandmarkEvidenceError(str(exc)) from exc
            records.append(
                {
                    "candidate_id": candidate_id,
                    "region": region,
                    "scene_id": str(public_candidate.get("scene_id") or ""),
                    "source_media_sha256": expected_media_sha,
                    "source_frame_sha256": frame_sha,
                    "closeup_image_sha256": image_sha,
                    "projection": _validate_projection(projection, region=region),
                }
            )

    if not records:
        raise PhotoIdentityNailLandmarkEvidenceError("nail landmark evidence contains no source-grounded records")

    evidence = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": str(public.get("performer_id") or ""),
        "bodyrig_revision": revision,
        "input_discovery_sha256": _sha256_file(public_path),
        "private_source_manifest_set_sha256": manifest_set_sha,
        "openpose_adapter": OPENPOSE_ADAPTER,
        "openpose_revision": OPENPOSE_REVISION,
        "record_count": len(records),
        "records": records,
        "source_paths_persisted": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }
    validated = validate_landmark_evidence(evidence)
    output = root / "nail-landmark-projections.json"
    _write_create_only(output, validated)
    return {**validated, "manifest": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Persist source-grounded OpenPose nail landmarks bound to exact discovery/source hashes without granting package authority."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = build_landmark_evidence(
            sweep_root=Path(args.sweep_root),
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, PhotoIdentityNailLandmarkEvidenceError, PhotoIdentityOpenPoseRunnerError) as exc:
        print(f"BodyRig nail landmark evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    ready = sum(1 for record in result["records"] if record["projection"]["application_ready"] is True)
    print(
        "BodyRig nail landmark evidence: PASS | "
        f"records={result['record_count']} | application-ready={ready} | package-authority=false"
    )
    print(f"Landmark evidence: {result['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
