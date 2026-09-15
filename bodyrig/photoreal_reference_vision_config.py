from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .photoreal_model_set import PhotorealModelSetError, build_model_set

ADAPTER_NAME = "bodyrig-reference-vision-v1"
IDENTITY_CONFIG_FORMAT = "bodyrig-photoreal-identity-extractor-config"
FRAME_CONFIG_FORMAT = "bodyrig-photoreal-frame-analyzer-config"
VERSION = 1


class PhotorealReferenceVisionConfigError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: str, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealReferenceVisionConfigError(f"{label} is invalid")
    return result


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
    if not adapter.is_file():
        raise PhotorealReferenceVisionConfigError(f"reference vision adapter not found: {adapter}")
    if not python.is_file():
        raise PhotorealReferenceVisionConfigError(f"Windows Python not found: {python}")
    if isinstance(timeout_seconds, bool) or not 1 <= int(timeout_seconds) <= 86400:
        raise PhotorealReferenceVisionConfigError("timeout_seconds must be in 1..86400")
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
        _text(distribution, label="WSL distribution", maximum=160),
        "--linux-python",
        _text(linux_python, label="Linux Python"),
        "--adapter-path",
        str(adapter),
        "--model-root",
        str(model_root_path),
        "--device",
        _text(device, label="vision device", maximum=32),
    ]
    common = {
        "version": VERSION,
        "adapter": ADAPTER_NAME,
        "revision": revision,
        "model_set_sha256": model_set["model_set_sha256"],
        "command": command,
        "timeout_seconds": int(timeout_seconds),
    }
    identity = {"format": IDENTITY_CONFIG_FORMAT, **common}
    frame = {"format": FRAME_CONFIG_FORMAT, **common}
    return identity, frame


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
                "production_activation": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
