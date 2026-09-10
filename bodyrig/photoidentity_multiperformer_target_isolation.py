from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .photoidentity_multiperformer_review_prepare import (
    FORMAT as REVIEW_FORMAT,
    PRIVATE_FORMAT as REVIEW_PRIVATE_FORMAT,
    PRIVATE_VERSION as REVIEW_PRIVATE_VERSION,
    VERSION as REVIEW_VERSION,
)
from .photoidentity_multiperformer_track_attestation import (
    FORMAT as ATTESTATION_FORMAT,
    POLICY as ATTESTATION_POLICY,
    VERSION as ATTESTATION_VERSION,
)
from .photoidentity_multiperformer_track_runner import (
    PhotoIdentityMultiTrackRunnerError,
    validate_track_review_batch,
)

FORMAT = "bodyrig-photoidentity-multiperformer-target-isolated-source"
VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoidentity-private-multiperformer-target-source-index"
PRIVATE_VERSION = 1


class PhotoIdentityMultiTargetIsolationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityMultiTargetIsolationError(f"required target-isolation input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotoIdentityMultiTargetIsolationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityMultiTargetIsolationError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityMultiTargetIsolationError("target isolation requires exact BodyRig Git revision")
    return revision


def _canonical_sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise PhotoIdentityMultiTargetIsolationError(f"{label} is not canonical SHA-256")
    return digest


def _track_map(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise PhotoIdentityMultiTargetIsolationError(f"{label} track list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiTargetIsolationError(f"{label} track row is invalid")
        candidate_id = str(raw.get("track_candidate_id") or "")
        if not candidate_id.startswith("trackcand-") or len(candidate_id) != 42 or candidate_id in result:
            raise PhotoIdentityMultiTargetIsolationError(f"{label} track candidate id is invalid/duplicate")
        result[candidate_id] = dict(raw)
    return result


def _load_bound_review(root: Path, revision: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    public_path = root / "multiperformer-track-review-candidates.json"
    private_path = root / "private-track-review" / "private-review-index.json"
    machine_path = root / "machine-track-review.json"
    receipt_path = root / "photoidentity-multiperformer-track-attestation.json"

    public = _read_json(public_path, label="Public multi-performer track review")
    private = _read_json(private_path, label="Private multi-performer track review")
    receipt = _read_json(receipt_path, label="Human multi-performer track attestation")
    machine_raw = _read_json(machine_path, label="Machine PHALP track review")
    try:
        machine = validate_track_review_batch(machine_raw, expected_source_count=1)
    except PhotoIdentityMultiTrackRunnerError as exc:
        raise PhotoIdentityMultiTargetIsolationError(f"machine PHALP track review is invalid: {exc}") from exc

    if public.get("format") != REVIEW_FORMAT or public.get("version") != REVIEW_VERSION:
        raise PhotoIdentityMultiTargetIsolationError("public track review format/version is invalid")
    if private.get("format") != REVIEW_PRIVATE_FORMAT or private.get("version") != REVIEW_PRIVATE_VERSION:
        raise PhotoIdentityMultiTargetIsolationError("private track review format/version is invalid")
    if receipt.get("format") != ATTESTATION_FORMAT or receipt.get("version") != ATTESTATION_VERSION or receipt.get("policy") != ATTESTATION_POLICY:
        raise PhotoIdentityMultiTargetIsolationError("human track attestation format/version/policy is invalid")

    for evidence in (public, private, receipt):
        if str(evidence.get("bodyrig_revision") or "") != revision:
            raise PhotoIdentityMultiTargetIsolationError("multi-performer review chain belongs to a different BodyRig revision")

    if private.get("public_review_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityMultiTargetIsolationError("private review index is not bound to public review bytes")
    if receipt.get("public_review_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityMultiTargetIsolationError("human attestation is not bound to public review bytes")
    if receipt.get("private_review_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityMultiTargetIsolationError("human attestation is not bound to private review bytes")
    if public.get("machine_track_review_sha256") != _sha256_file(machine_path) or receipt.get("machine_track_review_sha256") != _sha256_file(machine_path):
        raise PhotoIdentityMultiTargetIsolationError("review chain is not bound to exact machine-track bytes")

    for field in ("performer_id", "scene_id", "source_candidate_id", "source_media_sha256"):
        if private.get(field) != public.get(field) or receipt.get(field) != public.get(field):
            raise PhotoIdentityMultiTargetIsolationError(f"multi-performer review chain differs on {field}")

    if receipt.get("human_identity_attested") is not True:
        raise PhotoIdentityMultiTargetIsolationError("target track lacks explicit human identity attestation")
    for field in (
        "source_paths_persisted",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        if receipt.get(field) is not False:
            raise PhotoIdentityMultiTargetIsolationError(f"human track receipt crossed pre-isolation authority boundary: {field}")

    source_path = Path(str(private.get("source_path") or "")).expanduser().resolve()
    if not source_path.is_file():
        raise PhotoIdentityMultiTargetIsolationError("human-attested source media is no longer locally readable")
    source_sha = _sha256_file(source_path)
    if source_sha != _canonical_sha(public.get("source_media_sha256"), label="source-media SHA-256"):
        raise PhotoIdentityMultiTargetIsolationError("human-attested source media bytes changed")
    if machine["sources"][0]["source_media_sha256"] != source_sha:
        raise PhotoIdentityMultiTargetIsolationError("PHALP machine review belongs to different source-media bytes")

    return public, private, receipt, machine, receipt_path


def _selected_tracks(public: Mapping[str, Any], private: Mapping[str, Any], receipt: Mapping[str, Any], machine: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    public_map = _track_map(public.get("tracks"), label="public")
    private_map = _track_map(private.get("tracks"), label="private")
    if set(public_map) != set(private_map):
        raise PhotoIdentityMultiTargetIsolationError("public/private review track sets differ")

    candidate_id = str(receipt.get("track_candidate_id") or "")
    public_track = public_map.get(candidate_id)
    private_track = private_map.get(candidate_id)
    if public_track is None or private_track is None:
        raise PhotoIdentityMultiTargetIsolationError("human-attested track candidate disappeared from review")
    track_id = str(receipt.get("selected_track_id") or "")
    if public_track.get("track_id") != track_id or private_track.get("track_id") != track_id:
        raise PhotoIdentityMultiTargetIsolationError("human-attested PHALP track id no longer matches review")

    expected_sheet = Path(str(private_track.get("review_sheet") or "")).expanduser().resolve()
    if _sha256_file(expected_sheet) != _canonical_sha(public_track.get("review_sheet_sha256"), label="review-sheet SHA-256"):
        raise PhotoIdentityMultiTargetIsolationError("human-reviewed track sheet bytes changed")
    if receipt.get("review_sheet_sha256") != public_track.get("review_sheet_sha256"):
        raise PhotoIdentityMultiTargetIsolationError("human receipt is not bound to selected review-sheet bytes")

    machine_tracks = machine["sources"][0]["review"]["tracks"]
    matches = [dict(item) for item in machine_tracks if isinstance(item, Mapping) and str(item.get("track_id") or "") == track_id]
    if len(matches) != 1:
        raise PhotoIdentityMultiTargetIsolationError("human-attested PHALP track is not unique in machine review")
    return public_track, private_track, matches[0]


def _crop_box(bbox: object, *, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise PhotoIdentityMultiTargetIsolationError("PHALP target bbox is invalid")
    try:
        x, y, box_width, box_height = (float(item) for item in bbox)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotoIdentityMultiTargetIsolationError("PHALP target bbox is non-numeric") from exc
    if not all(math.isfinite(item) for item in (x, y, box_width, box_height)) or box_width <= 0.0 or box_height <= 0.0:
        raise PhotoIdentityMultiTargetIsolationError("PHALP target bbox is non-finite/empty")
    left = max(0, min(width - 1, math.floor(x)))
    top = max(0, min(height - 1, math.floor(y)))
    right = max(left + 1, min(width, math.ceil(x + box_width)))
    bottom = max(top + 1, min(height, math.ceil(y + box_height)))
    if right - left < 16 or bottom - top < 16:
        raise PhotoIdentityMultiTargetIsolationError("PHALP target bbox exposes too little native source area")
    return left, top, right, bottom


def isolate_human_attested_track_source(
    *,
    review_root: Path,
    output_dir: Path,
    current_revision: str,
) -> dict[str, Any]:
    revision = _canonical_revision(current_revision)
    root = review_root.expanduser().resolve()
    out = output_dir.expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentityMultiTargetIsolationError("multi-performer track review root is missing")
    if out.exists():
        raise PhotoIdentityMultiTargetIsolationError(f"target-isolation output already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)

    public, private, receipt, machine, receipt_path = _load_bound_review(root, revision)
    public_track, _, machine_track = _selected_tracks(public, private, receipt, machine)
    public_samples = public_track.get("samples")
    machine_samples = machine_track.get("samples")
    if not isinstance(public_samples, list) or not isinstance(machine_samples, list) or not public_samples:
        raise PhotoIdentityMultiTargetIsolationError("selected human-reviewed track has no source samples")
    if len(public_samples) != len(machine_samples) or int(public_track.get("review_sample_count") or -1) != len(public_samples):
        raise PhotoIdentityMultiTargetIsolationError("reviewed source-sample count no longer matches PHALP machine review")

    track_candidate_id = str(receipt["track_candidate_id"])
    selected_track_id = str(receipt["selected_track_id"])
    source_media_sha = str(receipt["source_media_sha256"])

    # Exclusive top-level mkdir makes publication no-clobber even under races.
    out.mkdir(exist_ok=False)
    private_root = out / "private-target-source"
    private_root.mkdir()
    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    try:
        for index, (public_sample, machine_sample) in enumerate(zip(public_samples, machine_samples, strict=True), start=1):
            if not isinstance(public_sample, Mapping) or not isinstance(machine_sample, Mapping):
                raise PhotoIdentityMultiTargetIsolationError("selected track sample is invalid")
            timestamp = public_sample.get("timestamp_ms")
            if timestamp != machine_sample.get("timestamp_ms") or isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                raise PhotoIdentityMultiTargetIsolationError("human-reviewed sample timestamp differs from PHALP machine authority")
            confidence = machine_sample.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
                raise PhotoIdentityMultiTargetIsolationError("PHALP sample confidence is invalid")

            reviewed_frame = root / "private-track-review" / track_candidate_id / "samples" / f"sample-{index:02d}-source-frame.png"
            expected_frame_sha = _canonical_sha(public_sample.get("source_frame_sha256"), label="reviewed source-frame SHA-256")
            if _sha256_file(reviewed_frame) != expected_frame_sha:
                raise PhotoIdentityMultiTargetIsolationError("human-reviewed source-frame bytes changed")
            try:
                with Image.open(reviewed_frame) as opened:
                    opened.load()
                    frame = opened.convert("RGB")
            except Exception as exc:
                raise PhotoIdentityMultiTargetIsolationError("human-reviewed source frame is unreadable") from exc
            width, height = frame.size
            if not 64 <= width <= 16384 or not 64 <= height <= 16384:
                raise PhotoIdentityMultiTargetIsolationError("human-reviewed source frame dimensions are invalid")
            left, top, right, bottom = _crop_box(machine_sample.get("bbox_tlwh"), width=width, height=height)

            sample_id = f"targetsample-{index:04d}"
            sample_root = private_root / sample_id
            sample_root.mkdir()
            frame_copy = sample_root / "reviewed-source-frame.png"
            shutil.copyfile(reviewed_frame, frame_copy)
            if _sha256_file(frame_copy) != expected_frame_sha:
                raise PhotoIdentityMultiTargetIsolationError("copy of human-reviewed source-frame bytes changed")

            crop = frame.crop((left, top, right, bottom))
            crop_path = sample_root / "target-track-crop.png"
            crop.save(crop_path, format="PNG", optimize=False)
            crop_sha = _sha256_file(crop_path)
            bbox = [round(float(item), 6) for item in machine_sample["bbox_tlwh"]]
            row = {
                "sample_id": sample_id,
                "timestamp_ms": timestamp,
                "confidence": round(float(confidence), 6),
                "bbox_tlwh": bbox,
                "crop_ltrb": [left, top, right, bottom],
                "native_frame_width": width,
                "native_frame_height": height,
                "native_crop_width": right - left,
                "native_crop_height": bottom - top,
                "source_frame_sha256": expected_frame_sha,
                "target_crop_sha256": crop_sha,
            }
            public_rows.append(row)
            private_rows.append(
                {
                    "sample_id": sample_id,
                    "reviewed_source_frame": str(frame_copy),
                    "target_track_crop": str(crop_path),
                }
            )

        public_manifest = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrig_revision": revision,
            "performer_id": str(receipt["performer_id"]),
            "scene_id": str(receipt["scene_id"]),
            "source_candidate_id": str(receipt["source_candidate_id"]),
            "source_media_sha256": source_media_sha,
            "human_track_attestation_sha256": _sha256_file(receipt_path),
            "public_review_manifest_sha256": str(receipt["public_review_manifest_sha256"]),
            "private_review_index_sha256": str(receipt["private_review_index_sha256"]),
            "machine_track_review_sha256": str(receipt["machine_track_review_sha256"]),
            "track_candidate_id": track_candidate_id,
            "selected_track_id": selected_track_id,
            "sample_count": len(public_rows),
            "samples": public_rows,
            "target_track_identity_attested": True,
            "source_frames_human_review_bound": True,
            "all_samples_phalp_observed": True,
            "bbox_interpolation_used": False,
            "source_pixels_resized": False,
            "occlusion_removal_used": False,
            "generative_pixels_used": False,
            "biometric_identity_inference_used": False,
            "generic_guessing_permitted": False,
            "target_isolated_source_authority": True,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        private_index = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": revision,
            "performer_id": str(receipt["performer_id"]),
            "scene_id": str(receipt["scene_id"]),
            "source_media_sha256": source_media_sha,
            "source_path": str(Path(str(private["source_path"])).expanduser().resolve()),
            "track_candidate_id": track_candidate_id,
            "selected_track_id": selected_track_id,
            "samples": private_rows,
            "source_paths_private": True,
            "production_activation": False,
        }
        private_path = private_root / "private-target-source-index.json"
        private_path.write_text(
            json.dumps(private_index, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        public_manifest["private_target_source_index_sha256"] = _sha256_file(private_path)
        public_path = out / "multiperformer-target-isolated-source.json"
        public_path.write_text(
            json.dumps(public_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            **public_manifest,
            "public_manifest": str(public_path),
            "public_manifest_sha256": _sha256_file(public_path),
            "private_index": str(private_path),
        }
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize only the exact human-reviewed PHALP track samples as native source crops."
    )
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--current-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = isolate_human_attested_track_source(
            review_root=Path(args.review_root),
            output_dir=Path(args.output_dir),
            current_revision=args.current_revision,
        )
        print(result["public_manifest"])
        print(f"Target-isolated source samples: {result['sample_count']}")
        print("Target-isolated source authority: TRUE")
        print("Photoidentity source sufficiency authority: FALSE")
        print("Reconstruction permitted: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityMultiTargetIsolationError) as exc:
        print(f"BodyRig multi-performer target isolation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
