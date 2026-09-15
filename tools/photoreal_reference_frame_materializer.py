from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ADAPTER = "bodyrig-reference-frame-materializer-v1"
REQUEST_FORMAT = "bodyrig-photoreal-reference-frame-materialization-request"
RESULT_FORMAT = "bodyrig-photoreal-reference-frame-materialization-receipt"
VERSION = 1


class ReferenceFrameMaterializerError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReferenceFrameMaterializerError(f"request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ReferenceFrameMaterializerError("request must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise ReferenceFrameMaterializerError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ReferenceFrameMaterializerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ReferenceFrameMaterializerError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ReferenceFrameMaterializerError(f"{label} is invalid")
    return result


def _v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value != 1:
        raise ReferenceFrameMaterializerError("request version must be numeric v1")


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _self_revision() -> str:
    return _file_sha(Path(__file__).resolve())


def _frame_sha(image: Any) -> str:
    contiguous = image if getattr(image, "flags", None) is not None and image.flags.c_contiguous else image.copy(order="C")
    digest = hashlib.sha256()
    digest.update(("x".join(str(int(value)) for value in contiguous.shape) + "\n").encode("ascii"))
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def _decode(cv2: Any, np: Any, source: Mapping[str, Any], sample: Mapping[str, Any]) -> Any:
    path = Path(_text(source.get("resolved_path"), label="resolved source path"))
    kind = _text(source.get("kind"), label="source kind", maximum=16)
    if kind == "image":
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ReferenceFrameMaterializerError(f"could not decode image: {path}")
    elif kind == "video":
        timestamp = sample.get("timestamp_seconds")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
            raise ReferenceFrameMaterializerError("video sample timestamp is invalid")
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ReferenceFrameMaterializerError(f"could not open video: {path}")
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000.0)
            ok, image = capture.read()
            if not ok or image is None:
                raise ReferenceFrameMaterializerError(f"could not decode video frame at {timestamp}s: {path}")
        finally:
            capture.release()
    else:
        raise ReferenceFrameMaterializerError(f"unsupported source kind: {kind}")

    if source.get("projection") != "flat":
        raise ReferenceFrameMaterializerError("only flat projection is reproducibly materializable in v1")
    eye = _text(sample.get("eye"), label="sample eye", maximum=16)
    layout = _text(source.get("stereo_layout"), label="stereo layout", maximum=128)
    height, width = image.shape[:2]
    if layout == "side-by-side":
        midpoint = width // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise ReferenceFrameMaterializerError("invalid side-by-side sample")
        image = image[:, :midpoint] if eye == "left" else image[:, midpoint:]
    elif layout == "over-under":
        midpoint = height // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise ReferenceFrameMaterializerError("invalid over-under sample")
        image = image[:midpoint, :] if eye == "left" else image[midpoint:, :]
    elif layout == "mono":
        if eye != "mono":
            raise ReferenceFrameMaterializerError("mono source requested non-mono eye")
    else:
        raise ReferenceFrameMaterializerError(f"unsupported stereo layout: {layout}")
    if image.size == 0:
        raise ReferenceFrameMaterializerError("decoded reference frame is empty")
    return np.ascontiguousarray(image)


def _validate_request(value: Mapping[str, Any], args: argparse.Namespace) -> None:
    required = {
        "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "review_mapping_sha256", "held_out_reference_catalog_sha256", "adapter", "revision",
        "sources", "source_count", "sample_count", "decode_semantics", "frame_hash_semantics",
        "teacher_process_disclosure", "build_only", "runtime_dependency", "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != required:
        raise ReferenceFrameMaterializerError("request fields must match v1 exactly")
    if value.get("format") != REQUEST_FORMAT:
        raise ReferenceFrameMaterializerError("request format mismatch")
    _v1(value.get("version"))
    if args.bodyrig_adapter != ADAPTER or value.get("adapter") != ADAPTER:
        raise ReferenceFrameMaterializerError("adapter identity mismatch")
    revision = _self_revision()
    if args.bodyrig_revision != revision or value.get("revision") != revision:
        raise ReferenceFrameMaterializerError("materializer revision does not match exact adapter bytes")
    for key in ("teacher_input_sha256", "review_mapping_sha256", "held_out_reference_catalog_sha256"):
        _sha(value.get(key), label=key)
    if value.get("decode_semantics") != "opencv-bgr-array-v1":
        raise ReferenceFrameMaterializerError("decode semantics mismatch")
    if value.get("frame_hash_semantics") != "sha256(shape-ascii-newline+contiguous-bgr-bytes)":
        raise ReferenceFrameMaterializerError("frame hash semantics mismatch")
    if value.get("teacher_process_disclosure") is not False:
        raise ReferenceFrameMaterializerError("request crossed teacher disclosure boundary")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise ReferenceFrameMaterializerError("request build/runtime boundary is invalid")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise ReferenceFrameMaterializerError("request crossed downstream authority")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ReferenceFrameMaterializerError("request has no sources")
    if isinstance(value.get("source_count"), bool) or value.get("source_count") != len(sources):
        raise ReferenceFrameMaterializerError("request source count mismatch")
    sample_count = sum(len(source.get("samples") or []) for source in sources if isinstance(source, Mapping))
    if isinstance(value.get("sample_count"), bool) or value.get("sample_count") != sample_count or sample_count < 1:
        raise ReferenceFrameMaterializerError("request sample count mismatch")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig held-out review frames with P0 decode/hash semantics")
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # noqa: BLE001
            raise ReferenceFrameMaterializerError("OpenCV and NumPy are required in the pinned Photoreal runtime") from exc
        request = _read_json(args.bodyrig_request.expanduser().resolve())
        _validate_request(request, args)
        output = args.bodyrig_output.expanduser().resolve()
        if not output.is_dir() or any(output.iterdir()):
            raise ReferenceFrameMaterializerError("BodyRig output directory must exist and be empty")
        references_dir = output / "references"
        references_dir.mkdir()

        materialized: list[dict[str, Any]] = []
        seen_observations: set[str] = set()
        for source in request["sources"]:
            if not isinstance(source, Mapping):
                raise ReferenceFrameMaterializerError("request contains invalid source")
            path = Path(_text(source.get("resolved_path"), label="resolved source path"))
            if not path.is_file():
                raise ReferenceFrameMaterializerError(f"reference source not found: {path}")
            expected_source_sha = _sha(source.get("source_sha256"), label="source SHA-256")
            if _file_sha(path) != expected_source_sha:
                raise ReferenceFrameMaterializerError("reference source SHA-256 mismatch")
            source_key = _text(source.get("source_key"), label="source key")
            samples = source.get("samples")
            if not isinstance(samples, list) or not samples:
                raise ReferenceFrameMaterializerError("reference source has no selected samples")
            for sample in samples:
                if not isinstance(sample, Mapping):
                    raise ReferenceFrameMaterializerError("reference sample is invalid")
                observation_id = _sha(sample.get("observation_id"), label="observation id")
                if observation_id in seen_observations:
                    raise ReferenceFrameMaterializerError("request repeats selected observation")
                seen_observations.add(observation_id)
                image = _decode(cv2, np, source, sample)
                observed_frame_sha = _frame_sha(image)
                expected_frame_sha = _sha(sample.get("expected_frame_sha256"), label="expected frame SHA-256")
                if observed_frame_sha != expected_frame_sha:
                    raise ReferenceFrameMaterializerError(
                        f"decoded reference frame SHA-256 mismatch for observation {observation_id}"
                    )
                target = references_dir / f"{observation_id}.png"
                if not cv2.imwrite(str(target), image):
                    raise ReferenceFrameMaterializerError(f"could not write reference PNG: {target}")
                if not target.is_file() or target.stat().st_size < 1:
                    raise ReferenceFrameMaterializerError(f"reference PNG is missing after write: {target}")
                coverages = sample.get("coverages")
                if not isinstance(coverages, list) or not coverages or any(not isinstance(item, str) or not item for item in coverages):
                    raise ReferenceFrameMaterializerError("reference sample coverage list is invalid")
                materialized.append({
                    "observation_id": observation_id,
                    "source_key": source_key,
                    "expected_frame_sha256": expected_frame_sha,
                    "observed_frame_sha256": observed_frame_sha,
                    "timestamp_seconds": sample.get("timestamp_seconds"),
                    "eye": sample.get("eye"),
                    "coverages": list(coverages),
                    "source_hash_verified": True,
                    "frame_hash_verified": True,
                    "png_relative_path": f"references/{observation_id}.png",
                    "png_size_bytes": target.stat().st_size,
                    "png_sha256": _file_sha(target),
                })

        materialized.sort(key=lambda item: item["observation_id"])
        receipt = {
            "format": RESULT_FORMAT,
            "version": VERSION,
            "performer_id": request["performer_id"],
            "selected_epoch_id": request["selected_epoch_id"],
            "teacher_input_sha256": request["teacher_input_sha256"],
            "review_mapping_sha256": request["review_mapping_sha256"],
            "held_out_reference_catalog_sha256": request["held_out_reference_catalog_sha256"],
            "adapter": ADAPTER,
            "revision": request["revision"],
            "source_count": request["source_count"],
            "sample_count": request["sample_count"],
            "materialized_references": materialized,
            "all_source_hashes_verified": True,
            "all_frame_hashes_verified": True,
            "decode_semantics": request["decode_semantics"],
            "frame_hash_semantics": request["frame_hash_semantics"],
            "teacher_process_disclosure": False,
            "photoreal_acceptance_authority": False,
            "human_visual_acceptance_required": True,
            "build_only": True,
            "runtime_dependency": False,
            "production_activation": False,
        }
        (output / "materialization-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "format": RESULT_FORMAT,
            "version": VERSION,
            "source_count": request["source_count"],
            "sample_count": request["sample_count"],
            "all_source_hashes_verified": True,
            "all_frame_hashes_verified": True,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }, sort_keys=True, separators=(",", ":")))
    except ReferenceFrameMaterializerError as exc:
        print(f"BodyRig reference frame materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
