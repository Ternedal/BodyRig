from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

REQUEST_FORMAT = "bodyrig-photoreal-gaussianavatar-materialization-request"
RECEIPT_FORMAT = "bodyrig-photoreal-gaussianavatar-materialization-receipt"
VERSION = 1
GAUSSIANAVATAR_COMMIT = "d981c62238ef64e89dcc04719d2ebbb4758b080a"


class GaussianAvatarMaterializeError(RuntimeError):
    pass


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise GaussianAvatarMaterializeError(f"{label} is invalid")
    return result


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise GaussianAvatarMaterializeError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_sha(image: Any) -> str:
    shape = "x".join(str(int(value)) for value in image.shape)
    digest = hashlib.sha256()
    digest.update((shape + "\n").encode("ascii"))
    digest.update(memoryview(image).cast("B"))
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GaussianAvatarMaterializeError(f"request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise GaussianAvatarMaterializeError("request must be a JSON object")
    return value


def _validate(value: Mapping[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if value.get("format") != REQUEST_FORMAT or value.get("version") != VERSION:
        raise GaussianAvatarMaterializeError("request format/version mismatch")
    if value.get("benchmark") != "gaussianavatar" or value.get("upstream_commit") != GAUSSIANAVATAR_COMMIT:
        raise GaussianAvatarMaterializeError("request targets wrong benchmark/upstream")
    if value.get("smpl_gender") != "female" or value.get("smpl_type") != "smpl":
        raise GaussianAvatarMaterializeError("GaussianAvatar benchmark v1 requires explicit female SMPL prior")
    if value.get("held_out_evaluation_disclosed") is not False:
        raise GaussianAvatarMaterializeError("request disclosed held-out evaluation")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise GaussianAvatarMaterializeError("request crossed downstream authority")
    if value.get("build_only") is not True:
        raise GaussianAvatarMaterializeError("request must remain build-only")
    _sha(value.get("comparison_plan_sha256"), label="comparison plan SHA-256")
    _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256")

    raw_source = value.get("source")
    if not isinstance(raw_source, Mapping):
        raise GaussianAvatarMaterializeError("request source is invalid")
    if raw_source.get("projection") != "flat" or raw_source.get("stereo_layout") != "mono":
        raise GaussianAvatarMaterializeError("GaussianAvatar materialization supports only flat mono source")
    source = {
        "source_key": _text(raw_source.get("source_key"), label="source key", maximum=4096),
        "source_sha256": _sha(raw_source.get("source_sha256"), label="source SHA-256"),
        "resolved_path": _text(raw_source.get("resolved_path"), label="resolved source path"),
    }
    if not source["resolved_path"].startswith("/"):
        raise GaussianAvatarMaterializeError("resolved source path must be absolute Linux path")

    raw_observations = value.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise GaussianAvatarMaterializeError("request contains no authorized observations")
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping) or raw.get("source_key") != source["source_key"] or raw.get("eye") != "mono":
            raise GaussianAvatarMaterializeError("authorized observation source/eye is invalid")
        timestamp_raw = raw.get("timestamp_seconds")
        if isinstance(timestamp_raw, bool):
            raise GaussianAvatarMaterializeError("authorized observation timestamp is invalid")
        try:
            timestamp = round(float(timestamp_raw), 6)
        except (TypeError, ValueError) as exc:
            raise GaussianAvatarMaterializeError("authorized observation timestamp is invalid") from exc
        if not math.isfinite(timestamp) or timestamp < 0:
            raise GaussianAvatarMaterializeError("authorized observation timestamp is invalid")
        frame_sha = _sha(raw.get("frame_sha256"), label="authorized source frame SHA-256")
        key = (frame_sha, timestamp)
        if key in seen:
            raise GaussianAvatarMaterializeError("request repeats authorized observation")
        seen.add(key)
        observations.append({
            "source_key": source["source_key"],
            "frame_sha256": frame_sha,
            "timestamp_seconds": timestamp,
            "eye": "mono",
        })
    observations.sort(key=lambda item: (item["timestamp_seconds"], item["frame_sha256"]))
    return source, observations


def materialize(request: Mapping[str, Any], output: Path) -> dict[str, Any]:
    source, observations = _validate(request)
    if not output.is_dir() or any(output.iterdir()):
        raise GaussianAvatarMaterializeError("output directory must exist and be empty")
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        raise GaussianAvatarMaterializeError("OpenCV is unavailable") from exc

    train = output / "train"
    images = train / "images"
    images.mkdir(parents=True)
    capture = cv2.VideoCapture(source["resolved_path"])
    if not capture.isOpened():
        raise GaussianAvatarMaterializeError(f"could not open selected train source: {source['resolved_path']}")
    frames: list[dict[str, Any]] = []
    try:
        for index, observation in enumerate(observations):
            timestamp = float(observation["timestamp_seconds"])
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, image = capture.read()
            if not ok or image is None or image.size == 0:
                raise GaussianAvatarMaterializeError(f"could not decode authorized train frame at {timestamp:.6f}s")
            observed = _frame_sha(image)
            if observed != observation["frame_sha256"]:
                raise GaussianAvatarMaterializeError(
                    "authorized frame bytes do not reproduce P0 observation "
                    f"at {timestamp:.6f}s (expected={observation['frame_sha256']}, observed={observed})"
                )
            relative = f"train/images/{index:08d}.png"
            path = output / relative
            if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise GaussianAvatarMaterializeError(f"could not write staged PNG: {relative}")
            frames.append({
                "gaussianavatar_frame_index": index,
                "source_key": source["source_key"],
                "source_frame_sha256": observation["frame_sha256"],
                "timestamp_seconds": timestamp,
                "eye": "mono",
                "relative_path": relative,
                "staged_png_sha256": _file_sha(path),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            })
    finally:
        capture.release()

    source_map = {
        "format": "bodyrig-photoreal-gaussianavatar-source-map",
        "version": 1,
        "comparison_plan_sha256": request["comparison_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "frames": frames,
        "held_out_evaluation_disclosed": False,
        "production_activation": False,
    }
    (output / "bodyrig-source-map.json").write_text(
        json.dumps(source_map, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    receipt = {
        "format": RECEIPT_FORMAT,
        "version": VERSION,
        "benchmark": "gaussianavatar",
        "upstream_commit": GAUSSIANAVATAR_COMMIT,
        "comparison_plan_sha256": request["comparison_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "smpl_gender": "female",
        "smpl_type": "smpl",
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "frame_count": len(frames),
        "frames": frames,
        "exact_p0_frame_hashes_reproduced": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "independent_preprocessing_required": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "production_activation": False,
    }
    (output / "materialization-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig-authorized train frames for GaussianAvatar.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = materialize(_read(args.request.expanduser().resolve()), args.output.expanduser().resolve())
    except GaussianAvatarMaterializeError as exc:
        print(f"BodyRig GaussianAvatar materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "PASS",
        "frame_count": receipt["frame_count"],
        "exact_p0_frame_hashes_reproduced": True,
        "held_out_evaluation_disclosed": False,
        "production_activation": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
