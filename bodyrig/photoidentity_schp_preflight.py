from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .photoidentity_schp_contract import (
    INPUT_NAME,
    MODEL_FILE,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    MODEL_SHA256,
    MODEL_SIZE,
    OUTPUT_NAME,
    UPSTREAM_REPOSITORY,
    UPSTREAM_REVISION,
)

RUNTIME_FORMAT = "bodyrig-photoidentity-schp-runtime"
RUNTIME_VERSION = 1
ONNXRUNTIME_VERSION = "1.22.1"
NUMPY_VERSION = "2.2.6"
PILLOW_VERSION = "11.3.0"


class PhotoIdentitySchpPreflightError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySchpPreflightError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySchpPreflightError(f"{label} must be a JSON object")
    return value


def _runtime_python(root: Path) -> Path:
    return root / "venv" / "Scripts" / "python.exe"


def _probe_script(model_path: Path) -> str:
    return f'''\
import json
import numpy
import onnxruntime as ort
import PIL
model = {str(model_path)!r}
options = ort.SessionOptions()
options.intra_op_num_threads = 8
options.inter_op_num_threads = 1
options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
print(json.dumps({{
    "onnxruntime": ort.__version__,
    "numpy": numpy.__version__,
    "pillow": PIL.__version__,
    "providers": session.get_providers(),
    "inputs": [{{"name": item.name, "shape": item.shape, "type": item.type}} for item in session.get_inputs()],
    "outputs": [{{"name": item.name, "shape": item.shape, "type": item.type}} for item in session.get_outputs()],
}}, separators=(",", ":")))
'''


def inspect_runtime(runtime_root: str | Path) -> dict[str, Any]:
    root = Path(runtime_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotoIdentitySchpPreflightError(f"SCHP runtime root not found: {root}")
    receipt_path = root / "runtime.json"
    model_path = root / "model" / "schp-atr-18-int8-static.onnx"
    python = _runtime_python(root)
    for path, label in ((receipt_path, "runtime receipt"), (model_path, "SCHP model"), (python, "runtime Python")):
        if not path.is_file():
            raise PhotoIdentitySchpPreflightError(f"SCHP {label} is missing: {path}")
    if model_path.stat().st_size != MODEL_SIZE:
        raise PhotoIdentitySchpPreflightError(
            f"SCHP model size mismatch: expected {MODEL_SIZE}, got {model_path.stat().st_size}"
        )
    model_sha = _sha256(model_path)
    if model_sha != MODEL_SHA256:
        raise PhotoIdentitySchpPreflightError(
            f"SCHP model SHA-256 mismatch: expected {MODEL_SHA256}, got {model_sha}"
        )

    receipt = _read_json(receipt_path, label="SCHP runtime receipt")
    expected_keys = {
        "format",
        "version",
        "model_repository",
        "model_revision",
        "model_file",
        "model_sha256",
        "model_size",
        "upstream_repository",
        "upstream_revision",
        "weights_redistributed_by_bodyrig",
        "onnxruntime_version",
        "numpy_version",
        "pillow_version",
    }
    if set(receipt) != expected_keys or receipt.get("format") != RUNTIME_FORMAT or receipt.get("version") != RUNTIME_VERSION:
        raise PhotoIdentitySchpPreflightError("SCHP runtime receipt fields/format are invalid")
    expected = {
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "model_file": MODEL_FILE,
        "model_sha256": MODEL_SHA256,
        "model_size": MODEL_SIZE,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_revision": UPSTREAM_REVISION,
        "weights_redistributed_by_bodyrig": False,
        "onnxruntime_version": ONNXRUNTIME_VERSION,
        "numpy_version": NUMPY_VERSION,
        "pillow_version": PILLOW_VERSION,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise PhotoIdentitySchpPreflightError(f"SCHP runtime receipt {key} mismatch")

    try:
        completed = subprocess.run(
            [str(python), "-c", _probe_script(model_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=180,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotoIdentitySchpPreflightError("SCHP ONNX runtime probe could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise PhotoIdentitySchpPreflightError(f"SCHP ONNX runtime probe failed: {detail}")
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PhotoIdentitySchpPreflightError("SCHP ONNX runtime probe returned invalid JSON") from exc
    if not isinstance(probe, dict):
        raise PhotoIdentitySchpPreflightError("SCHP ONNX runtime probe must return an object")
    for key, expected_version in (
        ("onnxruntime", ONNXRUNTIME_VERSION),
        ("numpy", NUMPY_VERSION),
        ("pillow", PILLOW_VERSION),
    ):
        if str(probe.get(key) or "") != expected_version:
            raise PhotoIdentitySchpPreflightError(
                f"SCHP runtime {key} mismatch: expected {expected_version}, got {probe.get(key)!r}"
            )
    providers = probe.get("providers")
    if not isinstance(providers, list) or "CPUExecutionProvider" not in providers:
        raise PhotoIdentitySchpPreflightError("SCHP runtime lacks CPUExecutionProvider")
    inputs = probe.get("inputs")
    outputs = probe.get("outputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or inputs[0].get("name") != INPUT_NAME:
        raise PhotoIdentitySchpPreflightError("SCHP ONNX input contract changed")
    if not isinstance(outputs, list) or OUTPUT_NAME not in {str(item.get("name") or "") for item in outputs if isinstance(item, dict)}:
        raise PhotoIdentitySchpPreflightError("SCHP ONNX output contract changed")

    return {
        "format": "bodyrig-photoidentity-schp-preflight",
        "version": 1,
        "ok": True,
        "runtime_root": str(root),
        "runtime_python": str(python),
        "model_path": str(model_path),
        "model_sha256": model_sha,
        "model_size": model_path.stat().st_size,
        "onnxruntime_version": ONNXRUNTIME_VERSION,
        "providers": providers,
        "input_name": INPUT_NAME,
        "output_name": OUTPUT_NAME,
        "weights_redistributed_by_bodyrig": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed preflight for the isolated pinned SCHP ATR runtime.")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        result = inspect_runtime(args.runtime_root)
    except (OSError, PhotoIdentitySchpPreflightError) as exc:
        print(f"BodyRig SCHP preflight: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.out:
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            print(f"BodyRig SCHP preflight: FAIL: output already exists: {output}", file=sys.stderr)
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "BodyRig SCHP preflight: PASS | "
        f"model={result['model_sha256']} | ORT={result['onnxruntime_version']} | provider=CPUExecutionProvider"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
