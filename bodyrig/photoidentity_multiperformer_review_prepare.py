from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageOps

from .photoidentity_multiperformer_source_discovery import (
    FORMAT as DISCOVERY_FORMAT,
    PRIVATE_FORMAT as DISCOVERY_PRIVATE_FORMAT,
    PRIVATE_VERSION as DISCOVERY_PRIVATE_VERSION,
    VERSION as DISCOVERY_VERSION,
)
from .photoidentity_multiperformer_track_runner import (
    PhotoIdentityMultiTrackRunnerError,
    run_multiperformer_track_review,
)
from .photoidentity_openpose_runner import PhotoIdentityOpenPoseRunnerError, _extract_frame

FORMAT = "bodyrig-photoidentity-multiperformer-track-review-candidates"
VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoidentity-private-multiperformer-track-review-index"
PRIVATE_VERSION = 1
TRACK_ID_PREFIX = "trackcand-"


class PhotoIdentityMultiReviewPrepareError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityMultiReviewPrepareError(f"required review file is missing: {path}")
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
        raise PhotoIdentityMultiReviewPrepareError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityMultiReviewPrepareError(f"{label} must be a JSON object")
    return value


def _load_discovery(root: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    public_path = root / "multiperformer-source-candidates.json"
    private_path = root / "private-multiperformer-source-candidates" / "private-candidate-index.json"
    public = _read_json(public_path, label="Multi-performer source discovery")
    private = _read_json(private_path, label="Private multi-performer source index")
    if public.get("format") != DISCOVERY_FORMAT or public.get("version") != DISCOVERY_VERSION:
        raise PhotoIdentityMultiReviewPrepareError("multi-performer source discovery format/version is invalid")
    if public.get("stash_inventory_exhausted") is not True:
        raise PhotoIdentityMultiReviewPrepareError("multi-performer discovery did not prove exhaustive Stash inventory")
    for field in (
        "source_paths_persisted",
        "source_media_hashed_at_discovery",
        "target_track_selected",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "reconstruction_permitted",
        "human_review_render_permitted",
        "production_activation",
    ):
        if public.get(field) is not False:
            raise PhotoIdentityMultiReviewPrepareError(f"multi-performer discovery crossed authority boundary: {field}")
    if private.get("format") != DISCOVERY_PRIVATE_FORMAT or private.get("version") != DISCOVERY_PRIVATE_VERSION:
        raise PhotoIdentityMultiReviewPrepareError("private multi-performer source index format/version is invalid")
    if private.get("public_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityMultiReviewPrepareError("private multi-performer source index is not bound to public discovery bytes")
    for field in ("bodyrig_revision", "performer_id", "candidate_count"):
        if private.get(field) != public.get(field):
            raise PhotoIdentityMultiReviewPrepareError(f"public/private multi-performer discovery differs: {field}")
    return public_path, public, private_path, private


def _candidate_maps(public: Mapping[str, Any], private: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    public_rows = public.get("candidates")
    private_rows = private.get("candidates")
    if not isinstance(public_rows, list) or not isinstance(private_rows, list):
        raise PhotoIdentityMultiReviewPrepareError("multi-performer candidate lists are invalid")
    public_map: dict[str, dict[str, Any]] = {}
    private_map: dict[str, dict[str, Any]] = {}
    for raw in public_rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiReviewPrepareError("public multi-performer candidate is invalid")
        candidate_id = str(raw.get("candidate_id") or "")
        if not candidate_id.startswith("multicand-") or len(candidate_id) != 42 or candidate_id in public_map:
            raise PhotoIdentityMultiReviewPrepareError("public multi-performer candidate id is invalid/duplicate")
        public_map[candidate_id] = dict(raw)
    for raw in private_rows:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityMultiReviewPrepareError("private multi-performer candidate is invalid")
        candidate_id = str(raw.get("candidate_id") or "")
        if candidate_id not in public_map or candidate_id in private_map:
            raise PhotoIdentityMultiReviewPrepareError("private multi-performer candidate does not match public discovery")
        if raw.get("scene_id") != public_map[candidate_id].get("scene_id"):
            raise PhotoIdentityMultiReviewPrepareError("public/private multi-performer scene binding changed")
        private_map[candidate_id] = dict(raw)
    if set(public_map) != set(private_map):
        raise PhotoIdentityMultiReviewPrepareError("public/private multi-performer candidate sets differ")
    return public_map, private_map


def _track_candidate_id(*, source_candidate_id: str, track_id: str, source_sha256: str) -> str:
    authority = f"{source_candidate_id}\0{track_id}\0{source_sha256}".encode("utf-8")
    return TRACK_ID_PREFIX + hashlib.sha256(authority).hexdigest()[:32]


def _clamped_box(bbox: list[Any], *, width: int, height: int, padding_ratio: float = 0.18) -> tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise PhotoIdentityMultiReviewPrepareError("track review bbox is invalid")
    try:
        x, y, box_width, box_height = (float(item) for item in bbox)
    except (TypeError, ValueError) as exc:
        raise PhotoIdentityMultiReviewPrepareError("track review bbox is non-numeric") from exc
    if not all(math.isfinite(item) for item in (x, y, box_width, box_height)) or box_width <= 0 or box_height <= 0:
        raise PhotoIdentityMultiReviewPrepareError("track review bbox is non-finite or empty")
    pad_x = box_width * padding_ratio
    pad_y = box_height * padding_ratio
    left = max(0, min(width - 1, math.floor(x - pad_x)))
    top = max(0, min(height - 1, math.floor(y - pad_y)))
    right = max(left + 1, min(width, math.ceil(x + box_width + pad_x)))
    bottom = max(top + 1, min(height, math.ceil(y + box_height + pad_y)))
    if right - left < 16 or bottom - top < 16:
        raise PhotoIdentityMultiReviewPrepareError("track review bbox has too little visible source area")
    return left, top, right, bottom


def _annotated_context(frame: Image.Image, bbox: list[Any]) -> Image.Image:
    result = frame.convert("RGB").copy()
    width, height = result.size
    left, top, right, bottom = _clamped_box(bbox, width=width, height=height, padding_ratio=0.0)
    draw = ImageDraw.Draw(result)
    line_width = max(3, min(width, height) // 180)
    draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 255, 0), width=line_width)
    return result


def _tile(frame: Image.Image, bbox: list[Any], *, label: str) -> Image.Image:
    frame = frame.convert("RGB")
    width, height = frame.size
    crop_box = _clamped_box(bbox, width=width, height=height)
    context = _annotated_context(frame, bbox)
    crop = frame.crop(crop_box)
    tile = Image.new("RGB", (640, 640), "black")
    context_fit = ImageOps.contain(context, (640, 360))
    crop_fit = ImageOps.contain(crop, (640, 230))
    tile.paste(context_fit, ((640 - context_fit.width) // 2, (360 - context_fit.height) // 2))
    tile.paste(crop_fit, ((640 - crop_fit.width) // 2, 370 + (230 - crop_fit.height) // 2))
    draw = ImageDraw.Draw(tile)
    draw.text((12, 612), label[:100], fill="white")
    return tile


def _build_review_sheet(
    *,
    ffmpeg: str,
    source: Path,
    track_id: str,
    samples: list[Mapping[str, Any]],
    output: Path,
    private_sample_root: Path,
) -> tuple[str, list[dict[str, Any]]]:
    if not samples:
        raise PhotoIdentityMultiReviewPrepareError("track review candidate has no samples")
    tiles: list[Image.Image] = []
    sample_receipts: list[dict[str, Any]] = []
    private_sample_root.mkdir(parents=True, exist_ok=False)
    for index, sample in enumerate(samples, start=1):
        timestamp_ms = sample.get("timestamp_ms")
        bbox = sample.get("bbox_tlwh")
        confidence = sample.get("confidence")
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise PhotoIdentityMultiReviewPrepareError("track sample timestamp is invalid")
        if not isinstance(bbox, list):
            raise PhotoIdentityMultiReviewPrepareError("track sample bbox is invalid")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError) as exc:
            raise PhotoIdentityMultiReviewPrepareError("track sample confidence is invalid") from exc
        if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
            raise PhotoIdentityMultiReviewPrepareError("track sample confidence is invalid")
        frame_path = private_sample_root / f"sample-{index:02d}-source-frame.png"
        _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=timestamp_ms / 1000.0, output=frame_path)
        try:
            with Image.open(frame_path) as opened:
                opened.load()
                frame = opened.convert("RGB")
        except Exception as exc:
            raise PhotoIdentityMultiReviewPrepareError("extracted track review source frame is unreadable") from exc
        label = f"{track_id} | {timestamp_ms / 1000.0:.3f}s | conf={confidence_value:.3f}"
        tile = _tile(frame, bbox, label=label)
        tile_path = private_sample_root / f"sample-{index:02d}-review-tile.png"
        tile.save(tile_path, format="PNG", optimize=False)
        tiles.append(tile)
        sample_receipts.append(
            {
                "timestamp_ms": timestamp_ms,
                "source_frame_sha256": _sha256_file(frame_path),
                "review_tile_sha256": _sha256_file(tile_path),
            }
        )

    columns = 2
    rows = math.ceil(len(tiles) / columns)
    sheet = Image.new("RGB", (columns * 640, rows * 640), "black")
    for index, tile in enumerate(tiles):
        x = (index % columns) * 640
        y = (index // columns) * 640
        sheet.paste(tile, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=False)
    return _sha256_file(output), sample_receipts


def prepare_multiperformer_track_review(
    *,
    discovery_root: Path,
    source_candidate_id: str,
    output_dir: Path,
    ffmpeg: str,
    external_python: str,
    four_d_humans_repo: str,
    phalp_repo: str,
    distribution: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    discovery_root = discovery_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not discovery_root.is_dir():
        raise PhotoIdentityMultiReviewPrepareError("multi-performer discovery root is missing")
    if output_dir.exists():
        raise PhotoIdentityMultiReviewPrepareError(f"track review output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    public_path, discovery, private_path, private = _load_discovery(discovery_root)
    public_map, private_map = _candidate_maps(discovery, private)
    source_candidate_id = str(source_candidate_id or "").strip().lower()
    public_source = public_map.get(source_candidate_id)
    private_source = private_map.get(source_candidate_id)
    if public_source is None or private_source is None:
        raise PhotoIdentityMultiReviewPrepareError(f"unknown multi-performer source candidate: {source_candidate_id}")
    source = Path(str(private_source.get("source_path") or "")).expanduser().resolve()
    if not source.is_file():
        raise PhotoIdentityMultiReviewPrepareError("selected multi-performer source file is no longer local")

    machine = run_multiperformer_track_review(
        [source],
        external_python=external_python,
        four_d_humans_repo=four_d_humans_repo,
        phalp_repo=phalp_repo,
        distribution=distribution,
        wsl_exe=wsl_exe,
    )
    if len(machine["sources"]) != 1:
        raise PhotoIdentityMultiReviewPrepareError("PHALP review did not return exactly one selected source")
    source_result = machine["sources"][0]
    source_sha = str(source_result["source_media_sha256"])
    if _sha256_file(source) != source_sha:
        raise PhotoIdentityMultiReviewPrepareError("Windows/WSL source-media hash authority disagrees")
    review = source_result["review"]
    tracks = review["tracks"]
    if not isinstance(tracks, list):
        raise PhotoIdentityMultiReviewPrepareError("PHALP track review list is invalid")

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    try:
        machine_path = stage / "machine-track-review.json"
        machine_path.write_text(
            json.dumps(machine, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        private_root = stage / "private-track-review"
        private_root.mkdir()
        public_tracks: list[dict[str, Any]] = []
        private_tracks: list[dict[str, Any]] = []
        for raw_track in tracks:
            if not isinstance(raw_track, Mapping):
                raise PhotoIdentityMultiReviewPrepareError("PHALP track candidate is invalid")
            track_id = str(raw_track.get("track_id") or "")
            track_candidate_id = _track_candidate_id(
                source_candidate_id=source_candidate_id,
                track_id=track_id,
                source_sha256=source_sha,
            )
            track_root = private_root / track_candidate_id
            sheet_path = track_root / "review-sheet.png"
            sheet_sha, samples = _build_review_sheet(
                ffmpeg=ffmpeg,
                source=source,
                track_id=track_id,
                samples=list(raw_track.get("samples") or []),
                output=sheet_path,
                private_sample_root=track_root / "samples",
            )
            public_tracks.append(
                {
                    "track_candidate_id": track_candidate_id,
                    "track_id": track_id,
                    "observation_count": int(raw_track["observation_count"]),
                    "first_timestamp_ms": int(raw_track["first_timestamp_ms"]),
                    "last_timestamp_ms": int(raw_track["last_timestamp_ms"]),
                    "review_sample_count": len(samples),
                    "review_sheet_sha256": sheet_sha,
                    "samples": samples,
                }
            )
            private_tracks.append(
                {
                    "track_candidate_id": track_candidate_id,
                    "track_id": track_id,
                    "review_sheet": str(output_dir / "private-track-review" / track_candidate_id / "review-sheet.png"),
                }
            )

        public_review = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrig_revision": str(discovery["bodyrig_revision"]),
            "performer_id": str(discovery["performer_id"]),
            "source_discovery_manifest_sha256": _sha256_file(public_path),
            "source_discovery_private_index_sha256": _sha256_file(private_path),
            "source_candidate_id": source_candidate_id,
            "scene_id": str(public_source["scene_id"]),
            "source_media_sha256": source_sha,
            "machine_track_review_sha256": _sha256_file(machine_path),
            "track_candidate_count": len(public_tracks),
            "tracks": public_tracks,
            "source_paths_persisted": False,
            "target_track_selected": False,
            "human_identity_attestation_required": len(public_tracks) > 0,
            "biometric_identity_inference_used": False,
            "generic_guessing_permitted": False,
            "target_isolated_source_authority": False,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        public_review_path = stage / "multiperformer-track-review-candidates.json"
        public_review_path.write_text(
            json.dumps(public_review, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        private_review = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": str(discovery["bodyrig_revision"]),
            "performer_id": str(discovery["performer_id"]),
            "public_review_manifest_sha256": _sha256_file(public_review_path),
            "source_candidate_id": source_candidate_id,
            "scene_id": str(public_source["scene_id"]),
            "source_media_sha256": source_sha,
            "source_path": str(source),
            "tracks": private_tracks,
            "source_paths_private": True,
            "production_activation": False,
        }
        private_review_path = private_root / "private-review-index.json"
        private_review_path.write_text(
            json.dumps(private_review, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        **public_review,
        "public_review_manifest": str(output_dir / "multiperformer-track-review-candidates.json"),
        "private_review_index": str(output_dir / "private-track-review" / "private-review-index.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare source-derived review sheets for PHALP tracks without selecting target identity.")
    parser.add_argument("--discovery-root", required=True)
    parser.add_argument("--source-candidate-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--python", required=True, dest="external_python")
    parser.add_argument("--repo", required=True, dest="four_d_humans_repo")
    parser.add_argument("--phalp-repo", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = prepare_multiperformer_track_review(
            discovery_root=Path(args.discovery_root),
            source_candidate_id=args.source_candidate_id,
            output_dir=Path(args.output_dir),
            ffmpeg=args.ffmpeg,
            external_python=args.external_python,
            four_d_humans_repo=args.four_d_humans_repo,
            phalp_repo=args.phalp_repo,
            distribution=args.distribution,
            wsl_exe=args.wsl_exe,
        )
        print(result["public_review_manifest"])
        print(f"Track review candidates: {result['track_candidate_count']}")
        print("Target track selected by machine: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityMultiTrackRunnerError, PhotoIdentityOpenPoseRunnerError, PhotoIdentityMultiReviewPrepareError) as exc:
        print(f"BodyRig multi-performer track review preparation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
