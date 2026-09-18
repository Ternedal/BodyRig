from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

REQUEST_FORMAT = "bodyrig-photoreal-exavatar-materialization-request"
REQUEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-exavatar-materialization-receipt"
RECEIPT_VERSION = 1
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"


class ExAvatarMaterializeError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExAvatarMaterializeError(f"materialization request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExAvatarMaterializeError("materialization request must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise ExAvatarMaterializeError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ExAvatarMaterializeError(f"{label} is invalid")
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


def _validate_request(value: Mapping[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if value.get("format") != REQUEST_FORMAT or value.get("version") != REQUEST_VERSION:
        raise ExAvatarMaterializeError("materialization request format/version mismatch")
    if value.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ExAvatarMaterializeError("materialization request targets wrong ExAvatar commit")
    if value.get("held_out_evaluation_disclosed") is not False:
        raise ExAvatarMaterializeError("materialization request disclosed held-out evaluation")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise ExAvatarMaterializeError("materialization request crossed downstream authority")
    if value.get("build_only") is not True:
        raise ExAvatarMaterializeError("materialization request must be build-only")
    _sha(value.get("benchmark_plan_sha256"), label="benchmark plan SHA-256")
    _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256")
    _text(value.get("performer_id"), label="performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="selected epoch id", maximum=256)

    source_raw = value.get("source")
    if not isinstance(source_raw, Mapping):
        raise ExAvatarMaterializeError("materialization request source is invalid")
    if source_raw.get("projection") != "flat" or source_raw.get("stereo_layout") != "mono":
        raise ExAvatarMaterializeError("ExAvatar materialization supports only flat mono source")
    source = {
        "source_key": _text(source_raw.get("source_key"), label="source key", maximum=4096),
        "source_sha256": _sha(source_raw.get("source_sha256"), label="source SHA-256"),
        "resolved_path": _text(source_raw.get("resolved_path"), label="resolved source path"),
    }
    if not source["resolved_path"].startswith("/"):
        raise ExAvatarMaterializeError("resolved source path must be absolute Linux path")

    observations_raw = value.get("observations")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise ExAvatarMaterializeError("materialization request contains no observations")
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for raw in observations_raw:
        if not isinstance(raw, Mapping):
            raise ExAvatarMaterializeError("materialization observation is invalid")
        if raw.get("source_key") != source["source_key"]:
            raise ExAvatarMaterializeError("materialization observation references different source")
        if raw.get("eye") != "mono":
            raise ExAvatarMaterializeError("materialization observation is not mono")
        timestamp_raw = raw.get("timestamp_seconds")
        if isinstance(timestamp_raw, bool):
            raise ExAvatarMaterializeError("materialization timestamp is invalid")
        try:
            timestamp = float(timestamp_raw)
        except (TypeError, ValueError) as exc:
            raise ExAvatarMaterializeError("materialization timestamp is invalid") from exc
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ExAvatarMaterializeError("materialization timestamp is invalid")
        timestamp = round(timestamp, 6)
        frame_sha = _sha(raw.get("frame_sha256"), label="source frame SHA-256")
        key = (frame_sha, timestamp)
        if key in seen:
            raise ExAvatarMaterializeError("materialization request repeats observation")
        seen.add(key)
        observations.append(
            {
                "source_key": source["source_key"],
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": "mono",
            }
        )
    observations.sort(key=lambda item: (item["timestamp_seconds"], item["frame_sha256"]))
    return source, observations


def _load_cv2() -> Any:
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        raise ExAvatarMaterializeError("OpenCV is unavailable in ExAvatar materializer environment") from exc
    return cv2


def _decode_exact_frames(cv2: Any, source: Mapping[str, str], observations: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    source_path = source["resolved_path"]
    capture = cv2.VideoCapture(source_path)
    if not capture.isOpened():
        raise ExAvatarMaterializeError(f"could not open selected benchmark source: {source_path}")
    frames_dir = output / "frames"
    frames_dir.mkdir()
    result: list[dict[str, Any]] = []
    try:
        for index, observation in enumerate(observations):
            timestamp = float(observation["timestamp_seconds"])
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, image = capture.read()
            if not ok or image is None or image.size == 0:
                raise ExAvatarMaterializeError(f"could not decode authorized benchmark frame at {timestamp:.6f}s")
            observed_frame_sha = _frame_sha(image)
            expected_frame_sha = observation["frame_sha256"]
            if observed_frame_sha != expected_frame_sha:
                raise ExAvatarMaterializeError(
                    "authorized benchmark frame bytes do not reproduce P0 observation "
                    f"at {timestamp:.6f}s (expected={expected_frame_sha}, observed={observed_frame_sha})"
                )
            frame_path = frames_dir / f"{index}.png"
            if not cv2.imwrite(str(frame_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise ExAvatarMaterializeError(f"could not write lossless staged PNG: {frame_path}")
            if not frame_path.is_file() or frame_path.stat().st_size < 1:
                raise ExAvatarMaterializeError(f"staged PNG is missing/empty: {frame_path}")
            result.append(
                {
                    "exavatar_frame_index": index,
                    "source_key": source["source_key"],
                    "source_frame_sha256": expected_frame_sha,
                    "timestamp_seconds": timestamp,
                    "eye": "mono",
                    "relative_path": f"frames/{index}.png",
                    "staged_png_sha256": _file_sha(frame_path),
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                }
            )
    finally:
        capture.release()
    return result


def materialize(request: Mapping[str, Any], output: Path) -> dict[str, Any]:
    source, observations = _validate_request(request)
    if not output.is_dir():
        raise ExAvatarMaterializeError(f"materialization output directory does not exist: {output}")
    if any(output.iterdir()):
        raise ExAvatarMaterializeError("materialization output directory must be empty")

    cv2 = _load_cv2()
    frames = _decode_exact_frames(cv2, source, observations, output)
    indices = "".join(f"{index}\n" for index in range(len(frames)))
    (output / "frame_list_all.txt").write_text(indices, encoding="utf-8")
    (output / "frame_list_train.txt").write_text(indices, encoding="utf-8")
    # BodyRig held-out evaluation is deliberately external to ExAvatar.
    (output / "frame_list_test.txt").write_text("", encoding="utf-8")

    source_map = {
        "format": "bodyrig-photoreal-exavatar-source-map",
        "version": 1,
        "benchmark_plan_sha256": request["benchmark_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "frames": frames,
        "held_out_evaluation_disclosed": False,
        "build_only": True,
        "production_activation": False,
    }
    (output / "bodyrig-source-map.json").write_text(
        json.dumps(source_map, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "benchmark_plan_sha256": request["benchmark_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "upstream_commit": request["upstream_commit"],
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "frame_count": len(frames),
        "frames": frames,
        "frame_lists_are_training_only": True,
        "bodyrig_held_out_evaluation_is_external": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "exact_p0_frame_hashes_reproduced": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    (output / "materialization-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig-authorized frames for ExAvatar benchmark preprocessing.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = _read_json(args.request.expanduser().resolve())
        receipt = materialize(request, args.output.expanduser().resolve())
    except ExAvatarMaterializeError as exc:
        print(f"BodyRig ExAvatar materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_key": receipt["source_key"],
                "frame_count": receipt["frame_count"],
                "exact_p0_frame_hashes_reproduced": receipt["exact_p0_frame_hashes_reproduced"],
                "held_out_evaluation_disclosed": receipt["held_out_evaluation_disclosed"],
                "production_activation": receipt["production_activation"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
