from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_model_set import PhotorealModelSetError, build_model_set

ADAPTER_NAME = "bodyrig-reference-vision-v1"
IDENTITY_CONFIG_FORMAT = "bodyrig-photoreal-identity-extractor-config"
FRAME_CONFIG_FORMAT = "bodyrig-photoreal-frame-analyzer-config"
RUNTIME_FORMAT = "bodyrig-photoreal-reference-runtime-environment"
RUNTIME_VERSION = 1
EXPECTED_MMPOSE_REVISION = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"
EXPECTED_MMDET_REVISION = "fe3f809a0a514189baf889aa358c498d51ee36cd"
VERSION = 1


class PhotorealReferenceVisionConfigError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealReferenceVisionConfigError(f"{label} is invalid")
    return result


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealReferenceVisionConfigError(f"{label} must be numeric v1")
    if not math.isfinite(float(value)) or value != RUNTIME_VERSION:
        raise PhotorealReferenceVisionConfigError(f"{label} must be numeric v1")


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealReferenceVisionConfigError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealReferenceVisionConfigError(f"{label} must be a JSON object")
    return value


def _validate_runtime_receipt(
    root: Path,
    *,
    distribution: str,
    linux_python: str,
    device: str,
) -> dict[str, Any]:
    path = root / "runtime-environment.json"
    if not path.is_file():
        raise PhotorealReferenceVisionConfigError(
            "runtime-environment.json is missing; run setup-photoreal-reference-wsl.ps1 before generating runnable configs"
        )
    receipt = _read_object(path, label="reference runtime environment receipt")
    if receipt.get("format") != RUNTIME_FORMAT:
        raise PhotorealReferenceVisionConfigError("reference runtime environment format mismatch")
    _numeric_v1(receipt.get("version"), label="reference runtime environment version")
    if receipt.get("build_only") is not True or receipt.get("production_activation") is not False:
        raise PhotorealReferenceVisionConfigError("reference runtime environment crossed its authority boundary")
    if _text(receipt.get("distribution"), label="runtime distribution", maximum=160) != distribution:
        raise PhotorealReferenceVisionConfigError("requested WSL distribution differs from verified runtime receipt")
    if _text(receipt.get("linux_python"), label="runtime Linux Python") != linux_python:
        raise PhotorealReferenceVisionConfigError("requested Linux Python differs from verified runtime receipt")
    if receipt.get("mmpose_revision") != EXPECTED_MMPOSE_REVISION:
        raise PhotorealReferenceVisionConfigError("runtime receipt MMPose revision differs from pinned reference")
    if receipt.get("mmdetection_revision") != EXPECTED_MMDET_REVISION:
        raise PhotorealReferenceVisionConfigError("runtime receipt MMDetection revision differs from pinned reference")
    observed = receipt.get("observed")
    if not isinstance(observed, Mapping):
        raise PhotorealReferenceVisionConfigError("runtime receipt has no observed environment")
    if device != "cpu":
        if observed.get("torch_cuda_available") is not True:
            raise PhotorealReferenceVisionConfigError("verified runtime receipt has no PyTorch CUDA")
        providers = observed.get("onnxruntime_providers")
        if not isinstance(providers, list) or "CUDAExecutionProvider" not in providers:
            raise PhotorealReferenceVisionConfigError("verified runtime receipt has no ONNX Runtime CUDA provider")
    return receipt


def build_reference_configs(
    *,
    model_root: str | Path,
    adapter_path: str | Path,
    windows_python: str | Path,
    distribution: str,
    linux_python: str,
    device: str = "cuda:0",
    timeout_seconds: int = 86400,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model_root_path = Path(model_root).expanduser().resolve()
    adapter = Path(adapter_path).expanduser().resolve()
    python = Path(windows_python).expanduser().resolve()
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    linux_python = _text(linux_python, label="Linux Python")
    device = _text(device, label="vision device", maximum=32)
    if device not in {"cpu", "cuda", "cuda:0"}:
        raise PhotorealReferenceVisionConfigError("vision device must be cpu, cuda or cuda:0")
    if not adapter.is_file():
        raise PhotorealReferenceVisionConfigError(f"reference vision adapter not found: {adapter}")
    if not python.is_file():
        raise PhotorealReferenceVisionConfigError(f"Windows Python not found: {python}")
    if isinstance(timeout_seconds, bool) or not 1 <= int(timeout_seconds) <= 86400:
        raise PhotorealReferenceVisionConfigError("timeout_seconds must be in 1..86400")
    _validate_runtime_receipt(
        model_root_path,
        distribution=distribution,
        linux_python=linux_python,
        device=device,
    )
    try:
        model_set = build_model_set(model_root_path)
    except PhotorealModelSetError as exc:
        raise PhotorealReferenceVisionConfigError(str(exc)) from exc

    revision = _sha256(adapter)
    command = [
        str(python),
        "-m",
        "bodyrig.photoreal_wsl_request_bridge",
        "--distribution",
        distribution,
        "--linux-python",
        linux_python,
        "--adapter-path",
        str(adapter),
        "--model-root",
        str(model_root_path),
        "--device",
        device,
    ]
    common = {
        "version": VERSION,
        "adapter": ADAPTER_NAME,
        "revision": revision,
        "model_set_sha256": model_set["model_set_sha256"],
        "command": command,
        "timeout_seconds": int(timeout_seconds),
    }
    return {"format": IDENTITY_CONFIG_FORMAT, **common}, {"format": FRAME_CONFIG_FORMAT, **common}


def write_reference_configs(
    *,
    model_root: str | Path,
    adapter_path: str | Path,
    windows_python: str | Path,
    distribution: str,
    linux_python: str,
    identity_output: str | Path,
    frame_output: str | Path,
    device: str = "cuda:0",
    timeout_seconds: int = 86400,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity, frame = build_reference_configs(
        model_root=model_root,
        adapter_path=adapter_path,
        windows_python=windows_python,
        distribution=distribution,
        linux_python=linux_python,
        device=device,
        timeout_seconds=timeout_seconds,
    )
    identity_path = Path(identity_output).expanduser().resolve()
    frame_path = Path(frame_output).expanduser().resolve()
    if identity_path == frame_path:
        raise PhotorealReferenceVisionConfigError("identity/frame config outputs must differ")
    if identity_path.exists() or frame_path.exists():
        raise PhotorealReferenceVisionConfigError("reference vision config output already exists")
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    frame_path.write_text(json.dumps(frame, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return identity, frame


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate exact BodyRig Photoreal reference vision configs.")
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--windows-python", type=Path, required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--linux-python", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    parser.add_argument("--identity-out", type=Path, required=True)
    parser.add_argument("--frame-out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        identity, frame = write_reference_configs(
            model_root=args.model_root,
            adapter_path=args.adapter_path,
            windows_python=args.windows_python,
            distribution=args.distribution,
            linux_python=args.linux_python,
            identity_output=args.identity_out,
            frame_output=args.frame_out,
            device=args.device,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, PhotorealReferenceVisionConfigError) as exc:
        print(f"BodyRig Photoreal reference vision config: FAIL: {exc}")
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "adapter": identity["adapter"],
                "revision": identity["revision"],
                "model_set_sha256": identity["model_set_sha256"],
                "same_embedding_space": identity["command"] == frame["command"],
                "runtime_environment_bound": True,
                "production_activation": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
