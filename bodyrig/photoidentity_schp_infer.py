from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .photoidentity_schp_contract import (
    IMAGE_MEAN,
    IMAGE_STD,
    INPUT_NAME,
    INPUT_SIZE,
    MODEL_SHA256,
    OUTPUT_NAME,
)
from .photoidentity_schp_detail import PhotoIdentitySchpDetailError, analyze_schp_detail


class PhotoIdentitySchpInferenceError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_runtime() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        import onnxruntime as ort
        from PIL import Image
    except ImportError as exc:
        raise PhotoIdentitySchpInferenceError(
            "SCHP runtime requires numpy, onnxruntime and Pillow in the isolated parser environment"
        ) from exc
    return np, ort, Image


def _read_observation(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySchpInferenceError("private SCHP observation JSON is unreadable") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySchpInferenceError("private SCHP observation must be a JSON object")
    return value


def infer_claims(
    *,
    model_path: Path,
    image_path: Path,
    observation_path: Path,
    scene_id: str,
) -> dict[str, list[dict[str, object]]]:
    model_path = model_path.expanduser().resolve()
    image_path = image_path.expanduser().resolve()
    observation_path = observation_path.expanduser().resolve()
    if not model_path.is_file() or _sha256(model_path) != MODEL_SHA256:
        raise PhotoIdentitySchpInferenceError("SCHP model bytes do not match the pinned SHA-256")
    if not image_path.is_file():
        raise PhotoIdentitySchpInferenceError("private SCHP source frame is missing")

    np, ort, Image = _load_runtime()
    if str(getattr(ort, "__version__", "")) != "1.22.1":
        raise PhotoIdentitySchpInferenceError(
            f"SCHP runtime requires onnxruntime 1.22.1, got {getattr(ort, '__version__', 'unknown')}"
        )

    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = 8
    session_options.inter_op_num_threads = 1
    session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or inputs[0].name != INPUT_NAME:
        raise PhotoIdentitySchpInferenceError("SCHP model input contract changed")
    output_names = {item.name for item in outputs}
    if OUTPUT_NAME not in output_names:
        raise PhotoIdentitySchpInferenceError("SCHP model output contract changed")

    try:
        image = Image.open(image_path).convert("RGB")
        source_width, source_height = image.size
        image = image.resize(INPUT_SIZE, resample=Image.Resampling.BILINEAR)
        array = np.asarray(image, dtype=np.float32) / np.float32(255.0)
    except Exception as exc:
        raise PhotoIdentitySchpInferenceError("private SCHP source frame could not be decoded") from exc
    mean = np.asarray(IMAGE_MEAN, dtype=np.float32).reshape((1, 1, 3))
    std = np.asarray(IMAGE_STD, dtype=np.float32).reshape((1, 1, 3))
    array = (array - mean) / std
    pixel_values = np.transpose(array, (2, 0, 1))[None, ...].astype(np.float32, copy=False)

    try:
        logits = session.run([OUTPUT_NAME], {INPUT_NAME: pixel_values})[0]
    except Exception as exc:
        raise PhotoIdentitySchpInferenceError("SCHP ONNX inference failed") from exc
    if tuple(logits.shape) != (1, 18, 512, 512):
        raise PhotoIdentitySchpInferenceError(f"SCHP logits shape changed: {tuple(logits.shape)!r}")
    segmentation = np.argmax(logits, axis=1)[0]
    if tuple(segmentation.shape) != (512, 512):
        raise PhotoIdentitySchpInferenceError("SCHP segmentation output shape changed")

    observation = _read_observation(observation_path)
    try:
        return analyze_schp_detail(
            segmentation.tolist(),
            scene_id=scene_id,
            observation=observation,
            source_width=int(source_width),
            source_height=int(source_height),
        )
    except PhotoIdentitySchpDetailError as exc:
        raise PhotoIdentitySchpInferenceError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pinned SCHP ATR source-observability inference on one private frame.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--scene-id", required=True)
    args = parser.parse_args(argv)
    try:
        claims = infer_claims(
            model_path=Path(args.model),
            image_path=Path(args.image),
            observation_path=Path(args.observation),
            scene_id=args.scene_id,
        )
    except (OSError, PhotoIdentitySchpInferenceError) as exc:
        print(f"BodyRig SCHP source observability: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(claims, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
