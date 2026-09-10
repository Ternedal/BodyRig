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

from .bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from .photoidentity_multiperformer_track_attestation import FORMAT as TRACK_ATTESTATION_FORMAT
from .photoidentity_multiperformer_track_attestation import VERSION as TRACK_ATTESTATION_VERSION
from .photoidentity_multiperformer_track_runner import validate_track_review_batch
from .photoidentity_openpose_runner import PhotoIdentityOpenPoseRunnerError, _extract_frame
from .recover_cli import _run_wsl_file_protocol
from .wsl_adapter_bridge import make_wsl_path_converter

FORMAT = "bodyrig-photoidentity-target-isolation-candidate"
VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoidentity-private-target-isolation-index"
PRIVATE_VERSION = 1
BRIDGE_FORMAT = "bodyrig-phalp-target-isolation-result"
BRIDGE_VERSION = 1
MASK_METHOD = "black-outside-human-attested-phalp-tlwh-v1"
BBOX_PADDING_RATIO = 0.12
MAX_SAMPLES = 48


class PhotoIdentityTargetIsolationError(RuntimeError):
    pass


def _bridge_path() -> Path:
    return Path(__file__).resolve().parent / "bridges" / "hmr2_target_isolation_bridge.py"


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityTargetIsolationError(f"required target-isolation file is missing: {path}")
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
        raise PhotoIdentityTargetIsolationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityTargetIsolationError(f"{label} must be a JSON object")
    return value


def _canonical_revision(value: object, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise PhotoIdentityTargetIsolationError(f"{label} is not a canonical Git revision")
    return text


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise PhotoIdentityTargetIsolationError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhotoIdentityTargetIsolationError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise PhotoIdentityTargetIsolationError(f"{label} must be finite")
    return result


def _load_attested_chain(review_root: Path) -> dict[str, Any]:
    public_path = review_root / "multiperformer-track-review-candidates.json"
    private_path = review_root / "private-track-review" / "private-review-index.json"
    machine_path = review_root / "machine-track-review.json"
    attestation_path = review_root / "photoidentity-multiperformer-track-attestation.json"
    public = _read_json(public_path, label="Public multi-performer track review")
    private = _read_json(private_path, label="Private multi-performer track review index")
    machine = _read_json(machine_path, label="Machine multi-performer track review")
    attestation = _read_json(attestation_path, label="Human multi-performer track attestation")

    if attestation.get("format") != TRACK_ATTESTATION_FORMAT or attestation.get("version") != TRACK_ATTESTATION_VERSION:
        raise PhotoIdentityTargetIsolationError("human track attestation format/version is invalid")
    if attestation.get("human_identity_attested") is not True:
        raise PhotoIdentityTargetIsolationError("human track identity has not been attested")
    for field in (
        "source_paths_persisted",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        if attestation.get(field) is not False:
            raise PhotoIdentityTargetIsolationError(f"upstream human track attestation crossed authority boundary: {field}")

    if attestation.get("public_review_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityTargetIsolationError("human track attestation no longer binds public review bytes")
    if attestation.get("private_review_index_sha256") != _sha256_file(private_path):
        raise PhotoIdentityTargetIsolationError("human track attestation no longer binds private review bytes")
    if attestation.get("machine_track_review_sha256") != _sha256_file(machine_path):
        raise PhotoIdentityTargetIsolationError("human track attestation no longer binds machine review bytes")

    attestation_revision = _canonical_revision(attestation.get("bodyrig_revision"), label="attestation revision")
    if str(public.get("bodyrig_revision") or "").lower() != attestation_revision:
        raise PhotoIdentityTargetIsolationError("public review revision differs from human attestation")
    for field in ("performer_id", "scene_id", "source_candidate_id", "source_media_sha256"):
        if attestation.get(field) != public.get(field) or attestation.get(field) != private.get(field):
            raise PhotoIdentityTargetIsolationError(f"upstream multi-performer chain differs on {field}")

    try:
        machine_valid = validate_track_review_batch(machine, expected_source_count=1)
    except Exception as exc:
        raise PhotoIdentityTargetIsolationError(f"machine track review is invalid: {exc}") from exc
    source_row = machine_valid["sources"][0]
    expected_source_sha = str(attestation.get("source_media_sha256") or "").lower()
    if source_row["source_media_sha256"] != expected_source_sha:
        raise PhotoIdentityTargetIsolationError("machine review source hash differs from human attestation")

    selected_track_id = str(attestation.get("selected_track_id") or "")
    selected_candidate_id = str(attestation.get("track_candidate_id") or "")
    public_candidates = [
        row for row in public.get("tracks", [])
        if isinstance(row, Mapping) and row.get("track_candidate_id") == selected_candidate_id
    ]
    if len(public_candidates) != 1 or public_candidates[0].get("track_id") != selected_track_id:
        raise PhotoIdentityTargetIsolationError("human attestation no longer maps uniquely to public track candidate")
    machine_tracks = [
        row for row in source_row["review"]["tracks"]
        if isinstance(row, Mapping) and row.get("track_id") == selected_track_id
    ]
    if len(machine_tracks) != 1:
        raise PhotoIdentityTargetIsolationError("human-attested track is not unique in bound machine review")

    source = Path(str(private.get("source_path") or "")).expanduser().resolve()
    if not source.is_file():
        raise PhotoIdentityTargetIsolationError("human-attested multi-performer source is no longer local")
    if _sha256_file(source) != expected_source_sha:
        raise PhotoIdentityTargetIsolationError("human-attested source media bytes changed")

    return {
        "public_path": public_path,
        "private_path": private_path,
        "machine_path": machine_path,
        "attestation_path": attestation_path,
        "public": public,
        "private": private,
        "attestation": attestation,
        "attestation_revision": attestation_revision,
        "selected_track_id": selected_track_id,
        "expected_machine_track": dict(machine_tracks[0]),
        "source": source,
        "source_sha256": expected_source_sha,
    }


def _validate_isolation_payload(payload: object, *, expected_track_id: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation bridge returned a non-object")
    required = {
        "format", "version", "adapter", "revision", "source_media_sha256", "isolation",
        "source_paths_exported", "appearance_embeddings_exported", "machine_identity_selection",
        "biometric_identity_inference_used", "generic_guessing_permitted", "target_isolated_source_authority",
        "photoidentity_source_evidence_authority", "reconstruction_permitted", "production_activation",
    }
    if set(payload) != required or payload.get("format") != BRIDGE_FORMAT or payload.get("version") != BRIDGE_VERSION:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation bridge contract changed")
    if payload.get("adapter") != ADAPTER_NAME or payload.get("revision") != ADAPTER_REVISION:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation adapter authority changed")
    for field in (
        "source_paths_exported", "appearance_embeddings_exported", "machine_identity_selection",
        "biometric_identity_inference_used", "generic_guessing_permitted", "target_isolated_source_authority",
        "photoidentity_source_evidence_authority", "reconstruction_permitted", "production_activation",
    ):
        if payload.get(field) is not False:
            raise PhotoIdentityTargetIsolationError(f"PHALP target-isolation bridge illegally enabled {field}")

    isolation = payload.get("isolation")
    if not isinstance(isolation, Mapping):
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation evidence is invalid")
    isolation_required = {
        "format", "version", "source_index", "selected_track_id", "identity_authority", "canonical_review_track",
        "observed_state_count", "first_timestamp_ms", "last_timestamp_ms", "max_other_overlap_fraction",
        "p95_other_overlap_fraction", "high_overlap_state_count", "severe_overlap_state_count", "isolation_samples",
        "machine_identity_selection", "biometric_identity_inference_used", "generic_guessing_permitted",
        "target_isolated_source_authority", "photoidentity_source_evidence_authority", "reconstruction_permitted",
        "production_activation",
    }
    if set(isolation) != isolation_required:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation evidence fields changed")
    if isolation.get("format") != "bodyrig-phalp-target-isolation" or isolation.get("version") != 1:
        raise PhotoIdentityTargetIsolationError("unsupported PHALP target-isolation evidence format/version")
    if isolation.get("source_index") != 0 or isolation.get("selected_track_id") != expected_track_id:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation source/track binding changed")
    if isolation.get("identity_authority") != "human-track-attestation":
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation identity authority changed")
    for field in (
        "machine_identity_selection", "biometric_identity_inference_used", "generic_guessing_permitted",
        "target_isolated_source_authority", "photoidentity_source_evidence_authority",
        "reconstruction_permitted", "production_activation",
    ):
        if isolation.get(field) is not False:
            raise PhotoIdentityTargetIsolationError(f"PHALP target-isolation evidence illegally enabled {field}")

    observed = isolation.get("observed_state_count")
    first = isolation.get("first_timestamp_ms")
    last = isolation.get("last_timestamp_ms")
    high = isolation.get("high_overlap_state_count")
    severe = isolation.get("severe_overlap_state_count")
    for value, label in ((observed, "observed state count"), (first, "first timestamp"), (last, "last timestamp"), (high, "high-overlap count"), (severe, "severe-overlap count")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PhotoIdentityTargetIsolationError(f"PHALP target-isolation {label} is invalid")
    if observed < 3 or last < first or high > observed or severe > high:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation summary bounds are invalid")
    maximum = _finite(isolation.get("max_other_overlap_fraction"), label="maximum overlap")
    p95 = _finite(isolation.get("p95_other_overlap_fraction"), label="p95 overlap")
    if not 0.0 <= p95 <= maximum <= 1.0:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation overlap summary is invalid")

    samples = isolation.get("isolation_samples")
    if not isinstance(samples, list) or not 3 <= len(samples) <= MAX_SAMPLES or len(samples) > observed:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation sample set is invalid")
    previous = -1
    for sample in samples:
        if not isinstance(sample, Mapping) or set(sample) != {
            "timestamp_ms", "confidence", "bbox_tlwh", "observed_other_track_count", "max_other_overlap_fraction"
        }:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation sample fields changed")
        timestamp = sample.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= previous or timestamp < first or timestamp > last:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation sample timestamp is invalid")
        previous = timestamp
        confidence = _finite(sample.get("confidence"), label="target confidence")
        overlap = _finite(sample.get("max_other_overlap_fraction"), label="sample overlap")
        other_count = sample.get("observed_other_track_count")
        if not 0.0 <= confidence <= 1.0 or not 0.0 <= overlap <= 1.0:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation sample score is invalid")
        if isinstance(other_count, bool) or not isinstance(other_count, int) or other_count < 0:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation other-track count is invalid")
        bbox = sample.get("bbox_tlwh")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation bbox is invalid")
        values = [_finite(item, label="target bbox coordinate") for item in bbox]
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise PhotoIdentityTargetIsolationError("PHALP target-isolation bbox size is invalid")
    return dict(payload)


def _run_target_isolation(
    *,
    source: Path,
    selected_track_id: str,
    external_python: str,
    four_d_humans_repo: str,
    phalp_repo: str,
    distribution: str,
    wsl_exe: str,
) -> dict[str, Any]:
    for label, value in (("external Python", external_python), ("4D-Humans repo", four_d_humans_repo), ("PHALP repo", phalp_repo)):
        if not str(value).startswith("/"):
            raise PhotoIdentityTargetIsolationError(f"WSL {label} must be an absolute Linux path")
    if not str(distribution).strip():
        raise PhotoIdentityTargetIsolationError("WSL distribution is required")
    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        bridge = converter(str(_bridge_path()))
        translated_source = converter(str(source))
    except Exception as exc:
        raise PhotoIdentityTargetIsolationError(f"could not translate target-isolation paths into WSL: {exc}") from exc
    request = {"format": "bodyrig-recovery-request", "version": 1, "sources": [translated_source]}
    command = [
        external_python,
        bridge,
        "--repo", four_d_humans_repo.rstrip("/"),
        "--phalp-repo", phalp_repo.rstrip("/"),
        "--track-id", selected_track_id,
    ]
    try:
        returncode, stdout, stderr, staging = _run_wsl_file_protocol(
            wsl_exe=wsl_exe,
            distribution=distribution,
            external_python=external_python,
            target_command=command,
            request=request,
            converter=converter,
        )
    except Exception as exc:
        raise PhotoIdentityTargetIsolationError(f"PHALP target-isolation transport failed: {exc}") from exc
    if returncode != 0:
        detail = stderr.strip()[-2000:]
        suffix = f": {detail}" if detail else ""
        raise PhotoIdentityTargetIsolationError(
            f"PHALP target-isolation bridge exited {returncode}{suffix}; staging retained: {staging}"
        )
    try:
        payload = json.loads(stdout, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise PhotoIdentityTargetIsolationError("PHALP target-isolation bridge returned invalid JSON") from exc
    return _validate_isolation_payload(payload, expected_track_id=selected_track_id)


def _clamped_bbox(bbox: list[Any], *, width: int, height: int, padding_ratio: float = BBOX_PADDING_RATIO) -> tuple[int, int, int, int]:
    x, y, box_width, box_height = (_finite(item, label="isolation bbox coordinate") for item in bbox)
    if box_width <= 0.0 or box_height <= 0.0:
        raise PhotoIdentityTargetIsolationError("isolation bbox has non-positive size")
    pad_x = box_width * padding_ratio
    pad_y = box_height * padding_ratio
    left = max(0, min(width - 1, math.floor(x - pad_x)))
    top = max(0, min(height - 1, math.floor(y - pad_y)))
    right = max(left + 1, min(width, math.ceil(x + box_width + pad_x)))
    bottom = max(top + 1, min(height, math.ceil(y + box_height + pad_y)))
    if right - left < 16 or bottom - top < 16:
        raise PhotoIdentityTargetIsolationError("target isolation bbox has too little visible source area")
    return left, top, right, bottom


def _review_tile(frame: Image.Image, isolated: Image.Image, bbox: list[Any], *, label: str) -> Image.Image:
    original = frame.convert("RGB").copy()
    width, height = original.size
    left, top, right, bottom = _clamped_bbox(bbox, width=width, height=height, padding_ratio=0.0)
    draw = ImageDraw.Draw(original)
    line_width = max(3, min(width, height) // 180)
    draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 255, 0), width=line_width)

    tile = Image.new("RGB", (1000, 600), "black")
    left_panel = ImageOps.contain(original, (490, 540))
    right_panel = ImageOps.contain(isolated.convert("RGB"), (490, 540))
    tile.paste(left_panel, ((490 - left_panel.width) // 2, 35 + (540 - left_panel.height) // 2))
    tile.paste(right_panel, (500 + (490 - right_panel.width) // 2, 35 + (540 - right_panel.height) // 2))
    caption = ImageDraw.Draw(tile)
    caption.text((12, 8), label[:145], fill="white")
    caption.text((12, 580), "LEFT: source context + PHALP target box    RIGHT: isolated candidate (outside box masked)", fill="white")
    return tile


def _contact_sheet(tile_paths: list[Path], output: Path) -> str:
    if not tile_paths:
        raise PhotoIdentityTargetIsolationError("cannot build target-isolation contact sheet without review tiles")
    thumbs: list[Image.Image] = []
    for path in tile_paths:
        with Image.open(path) as image:
            thumb = ImageOps.contain(image.convert("RGB"), (500, 300))
            canvas = Image.new("RGB", (500, 300), "black")
            canvas.paste(thumb, ((500 - thumb.width) // 2, (300 - thumb.height) // 2))
            thumbs.append(canvas)
    columns = 2
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * 500, rows * 300), "black")
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % columns) * 500, (index // columns) * 300))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=False)
    return _sha256_file(output)


def prepare_target_isolation(
    *,
    review_root: Path,
    output_dir: Path,
    current_revision: str,
    ffmpeg: str,
    external_python: str,
    four_d_humans_repo: str,
    phalp_repo: str,
    distribution: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    review_root = review_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    isolation_revision = _canonical_revision(current_revision, label="target-isolation operator revision")
    if not review_root.is_dir():
        raise PhotoIdentityTargetIsolationError("multi-performer review root is missing")
    if output_dir.exists():
        raise PhotoIdentityTargetIsolationError(f"target-isolation output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    chain = _load_attested_chain(review_root)
    source: Path = chain["source"]
    source_sha_before = _sha256_file(source)
    if source_sha_before != chain["source_sha256"]:
        raise PhotoIdentityTargetIsolationError("source bytes changed before target-isolation run")

    machine = _run_target_isolation(
        source=source,
        selected_track_id=chain["selected_track_id"],
        external_python=external_python,
        four_d_humans_repo=four_d_humans_repo,
        phalp_repo=phalp_repo,
        distribution=distribution,
        wsl_exe=wsl_exe,
    )
    if str(machine.get("source_media_sha256") or "").lower() != source_sha_before:
        raise PhotoIdentityTargetIsolationError("Windows/WSL source-media hash authority disagrees")
    isolation = machine["isolation"]
    if isolation["canonical_review_track"] != chain["expected_machine_track"]:
        raise PhotoIdentityTargetIsolationError(
            "rerun PHALP track fingerprint differs from the machine review bound by human attestation"
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    try:
        machine_path = stage / "machine-target-isolation.json"
        machine_path.write_text(
            json.dumps(machine, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        private_root = stage / "private-target-isolation"
        private_root.mkdir()
        public_samples: list[dict[str, Any]] = []
        private_samples: list[dict[str, Any]] = []
        tile_paths: list[Path] = []

        for index, sample in enumerate(isolation["isolation_samples"], start=1):
            sample_root = private_root / f"sample-{index:03d}"
            sample_root.mkdir()
            frame_path = sample_root / "source-frame.png"
            timestamp_ms = int(sample["timestamp_ms"])
            _extract_frame(ffmpeg=ffmpeg, source=source, timestamp=timestamp_ms / 1000.0, output=frame_path)
            try:
                with Image.open(frame_path) as opened:
                    opened.load()
                    frame = opened.convert("RGB")
            except Exception as exc:
                raise PhotoIdentityTargetIsolationError("extracted target-isolation source frame is unreadable") from exc
            width, height = frame.size
            if width < 64 or height < 64 or width > 16384 or height > 16384:
                raise PhotoIdentityTargetIsolationError("target-isolation source frame geometry is invalid")
            box = _clamped_bbox(list(sample["bbox_tlwh"]), width=width, height=height)
            isolated = Image.new("RGB", (width, height), "black")
            isolated.paste(frame.crop(box), (box[0], box[1]))
            isolated_path = sample_root / "isolated-frame.png"
            isolated.save(isolated_path, format="PNG", optimize=False)
            label = (
                f"{chain['selected_track_id']} | {timestamp_ms / 1000.0:.3f}s | "
                f"conf={float(sample['confidence']):.3f} | other-overlap={float(sample['max_other_overlap_fraction']):.3f}"
            )
            tile = _review_tile(frame, isolated, list(sample["bbox_tlwh"]), label=label)
            tile_path = sample_root / "review-tile.png"
            tile.save(tile_path, format="PNG", optimize=False)
            tile_paths.append(tile_path)

            public_samples.append(
                {
                    "sample_index": index,
                    "timestamp_ms": timestamp_ms,
                    "confidence": float(sample["confidence"]),
                    "bbox_tlwh": list(sample["bbox_tlwh"]),
                    "observed_other_track_count": int(sample["observed_other_track_count"]),
                    "max_other_overlap_fraction": float(sample["max_other_overlap_fraction"]),
                    "source_frame_sha256": _sha256_file(frame_path),
                    "isolated_frame_sha256": _sha256_file(isolated_path),
                    "review_tile_sha256": _sha256_file(tile_path),
                    "width": width,
                    "height": height,
                }
            )
            final_sample_root = output_dir / "private-target-isolation" / f"sample-{index:03d}"
            private_samples.append(
                {
                    "sample_index": index,
                    "source_frame": str(final_sample_root / "source-frame.png"),
                    "isolated_frame": str(final_sample_root / "isolated-frame.png"),
                    "review_tile": str(final_sample_root / "review-tile.png"),
                }
            )

        contact_path = private_root / "target-isolation-contact-sheet.png"
        contact_sha = _contact_sheet(tile_paths, contact_path)
        if _sha256_file(source) != source_sha_before:
            raise PhotoIdentityTargetIsolationError("source media changed during target-isolation materialization")

        public_manifest = {
            "format": FORMAT,
            "version": VERSION,
            "attestation_revision": chain["attestation_revision"],
            "isolation_operator_revision": isolation_revision,
            "performer_id": str(chain["attestation"]["performer_id"]),
            "scene_id": str(chain["attestation"]["scene_id"]),
            "source_candidate_id": str(chain["attestation"]["source_candidate_id"]),
            "source_media_sha256": source_sha_before,
            "selected_track_id": chain["selected_track_id"],
            "human_track_attestation_sha256": _sha256_file(chain["attestation_path"]),
            "machine_track_review_sha256": _sha256_file(chain["machine_path"]),
            "machine_target_isolation_sha256": _sha256_file(machine_path),
            "mask_method": MASK_METHOD,
            "bbox_padding_ratio": BBOX_PADDING_RATIO,
            "observed_state_count": int(isolation["observed_state_count"]),
            "max_other_overlap_fraction": float(isolation["max_other_overlap_fraction"]),
            "p95_other_overlap_fraction": float(isolation["p95_other_overlap_fraction"]),
            "high_overlap_state_count": int(isolation["high_overlap_state_count"]),
            "severe_overlap_state_count": int(isolation["severe_overlap_state_count"]),
            "candidate_frame_count": len(public_samples),
            "samples": public_samples,
            "contact_sheet_sha256": contact_sha,
            "source_paths_persisted": False,
            "machine_identity_selection": False,
            "biometric_identity_inference_used": False,
            "generic_guessing_permitted": False,
            "human_isolation_review_required": True,
            "target_isolated_source_authority": False,
            "photoidentity_source_evidence_authority": False,
            "reconstruction_permitted": False,
            "production_activation": False,
        }
        public_path = stage / "target-isolation-candidate.json"
        public_path.write_text(
            json.dumps(public_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        final_private_root = output_dir / "private-target-isolation"
        private_manifest = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "public_manifest_sha256": _sha256_file(public_path),
            "attestation_revision": chain["attestation_revision"],
            "isolation_operator_revision": isolation_revision,
            "performer_id": str(chain["attestation"]["performer_id"]),
            "scene_id": str(chain["attestation"]["scene_id"]),
            "source_media_sha256": source_sha_before,
            "selected_track_id": chain["selected_track_id"],
            "source_path": str(source),
            "upstream_review_root": str(review_root),
            "human_track_attestation": str(chain["attestation_path"]),
            "machine_track_review": str(chain["machine_path"]),
            "machine_target_isolation": str(output_dir / "machine-target-isolation.json"),
            "contact_sheet": str(final_private_root / "target-isolation-contact-sheet.png"),
            "samples": private_samples,
            "source_paths_private": True,
            "target_isolated_source_authority": False,
            "photoidentity_source_evidence_authority": False,
            "production_activation": False,
        }
        private_path = private_root / "private-isolation-index.json"
        private_path.write_text(
            json.dumps(private_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.rename(stage, output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        **public_manifest,
        "output_dir": str(output_dir),
        "public_manifest": str(output_dir / "target-isolation-candidate.json"),
        "private_index": str(output_dir / "private-target-isolation" / "private-isolation-index.json"),
        "contact_sheet": str(output_dir / "private-target-isolation" / "target-isolation-contact-sheet.png"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare source-grounded target-isolation review evidence from a human-attested PHALP track.")
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--python", required=True, dest="external_python")
    parser.add_argument("--repo", required=True, dest="four_d_humans_repo")
    parser.add_argument("--phalp-repo", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = prepare_target_isolation(
            review_root=Path(args.review_root),
            output_dir=Path(args.output_dir),
            current_revision=args.current_revision,
            ffmpeg=args.ffmpeg,
            external_python=args.external_python,
            four_d_humans_repo=args.four_d_humans_repo,
            phalp_repo=args.phalp_repo,
            distribution=args.distribution,
            wsl_exe=args.wsl_exe,
        )
        print(result["public_manifest"])
        print(f"Review contact sheet: {result['contact_sheet']}")
        print("Human isolation review required: TRUE")
        print("Target-isolated source authority: FALSE")
        print("Photoidentity source evidence authority: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityOpenPoseRunnerError, PhotoIdentityTargetIsolationError) as exc:
        print(f"BodyRig target isolation preparation: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
