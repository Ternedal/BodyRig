from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .photoidentity_schp_contract import IMAGE_MEAN, IMAGE_STD, INPUT_NAME, INPUT_SIZE, MODEL_SHA256, OUTPUT_NAME
from .photoidentity_schp_infer import PhotoIdentitySchpInferenceError, _load_runtime
from .photoidentity_target_crop_detail import PhotoIdentityTargetCropDetailError, analyze_schp_target_crop


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_target_crop(*, model_path: Path, image_path: Path) -> list[dict[str, object]]:
    model_path = model_path.expanduser().resolve()
    image_path = image_path.expanduser().resolve()
    if not model_path.is_file() or _sha256(model_path) != MODEL_SHA256:
        raise PhotoIdentitySchpInferenceError("SCHP model bytes do not match the pinned SHA-256")
    if not image_path.is_file():
        raise PhotoIdentitySchpInferenceError("target crop is missing")

    np, ort, Image = _load_runtime()
    if str(getattr(ort, "__version__", "")) != "1.22.1":
        raise PhotoIdentitySchpInferenceError("target-crop SCHP runtime version changed")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 8
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or inputs[0].name != INPUT_NAME or OUTPUT_NAME not in {item.name for item in outputs}:
        raise PhotoIdentitySchpInferenceError("target-crop SCHP ONNX contract changed")

    try:
        source = Image.open(image_path).convert("RGB")
        width, height = source.size
        resized = source.resize(INPUT_SIZE, resample=Image.Resampling.BILINEAR)
        array = np.asarray(resized, dtype=np.float32) / np.float32(255.0)
    except Exception as exc:
        raise PhotoIdentitySchpInferenceError("target crop could not be decoded") from exc
    mean = np.asarray(IMAGE_MEAN, dtype=np.float32).reshape((1, 1, 3))
    std = np.asarray(IMAGE_STD, dtype=np.float32).reshape((1, 1, 3))
    pixels = np.transpose((array - mean) / std, (2, 0, 1))[None, ...].astype(np.float32, copy=False)
    try:
        logits = session.run([OUTPUT_NAME], {INPUT_NAME: pixels})[0]
    except Exception as exc:
        raise PhotoIdentitySchpInferenceError("target-crop SCHP ONNX inference failed") from exc
    if tuple(logits.shape) != (1, 18, 512, 512):
        raise PhotoIdentitySchpInferenceError(f"target-crop SCHP logits shape changed: {tuple(logits.shape)!r}")
    segmentation = np.argmax(logits, axis=1)[0]
    return analyze_schp_target_crop(segmentation.tolist(), source_width=int(width), source_height=int(height))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pinned SCHP directly on one human-accepted target-isolated source crop.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    try:
        result = infer_target_crop(model_path=Path(args.model), image_path=Path(args.image))
    except (OSError, PhotoIdentitySchpInferenceError, PhotoIdentityTargetCropDetailError) as exc:
        print(f"BodyRig target-crop SCHP inference: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
