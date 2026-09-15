from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

from .photoreal_model_set import PhotorealModelSetError, build_model_set
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter


class PhotorealReferenceVisionPreflightError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealReferenceVisionPreflightError(f"{label} must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealReferenceVisionPreflightError(f"{label} must be numeric v1")


def run_reference_vision_preflight(
    *,
    adapter_path: str | Path,
    probe_path: str | Path,
    model_root: str | Path,
    distribution: str,
    linux_python: str,
    device: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    adapter = Path(adapter_path).expanduser().resolve()
    probe = Path(probe_path).expanduser().resolve()
    root = Path(model_root).expanduser().resolve()
    if not adapter.is_file():
        raise PhotorealReferenceVisionPreflightError(f"reference vision adapter not found: {adapter}")
    if not probe.is_file():
        raise PhotorealReferenceVisionPreflightError(f"reference vision probe not found: {probe}")
    if not root.is_dir():
        raise PhotorealReferenceVisionPreflightError(f"reference vision model root not found: {root}")
    if not str(linux_python or "").startswith("/"):
        raise PhotorealReferenceVisionPreflightError("Linux Python must be an absolute Linux path")
    if device not in {"cpu", "cuda", "cuda:0"}:
        raise PhotorealReferenceVisionPreflightError("vision device must be cpu, cuda or cuda:0")
    try:
        model_set = build_model_set(root)
    except PhotorealModelSetError as exc:
        raise PhotorealReferenceVisionPreflightError(str(exc)) from exc
    adapter_revision = _sha256(adapter)

    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_adapter = converter(str(adapter))
        linux_probe = converter(str(probe))
        linux_model_root = converter(str(root))
    except WslBridgeError as exc:
        raise PhotorealReferenceVisionPreflightError(f"could not translate reference vision paths into WSL: {exc}") from exc

    invocation = [
        wsl_exe,
        "-d",
        distribution,
        "--",
        linux_python,
        linux_probe,
        "--adapter-path",
        linux_adapter,
        "--adapter-revision",
        adapter_revision,
        "--model-root",
        linux_model_root,
        "--model-set-sha256",
        model_set["model_set_sha256"],
        "--device",
        device,
    ]
    try:
        completed = subprocess.run(
            invocation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotorealReferenceVisionPreflightError(f"reference vision WSL probe could not complete: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-6000:]
        raise PhotorealReferenceVisionPreflightError(
            f"reference vision WSL probe failed with exit code {completed.returncode}: {detail}"
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe returned no output")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe must return a JSON object")
    if result.get("format") != "bodyrig-photoreal-reference-vision-probe":
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe format mismatch")
    _numeric_v1(result.get("version"), label="reference vision WSL probe version")
    if result.get("adapter_revision") != adapter_revision or result.get("model_set_sha256") != model_set["model_set_sha256"]:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe provenance mismatch")
    if result.get("face_inference_executed") is not True or result.get("pose_inference_executed") is not True:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe did not execute both inference stacks")
    if result.get("source_media_accessed") is not False or result.get("identity_authority") is not False:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe crossed source/identity authority")
    if result.get("photoreal_acceptance_authority") is not False or result.get("production_activation") is not False:
        raise PhotorealReferenceVisionPreflightError("reference vision WSL probe crossed downstream authority")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight the pinned BodyRig Photoreal reference vision stack through WSL.")
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--probe-path", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--linux-python", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_reference_vision_preflight(
            adapter_path=args.adapter_path,
            probe_path=args.probe_path,
            model_root=args.model_root,
            distribution=args.distribution,
            linux_python=args.linux_python,
            device=args.device,
            wsl_exe=args.wsl_exe,
        )
    except PhotorealReferenceVisionPreflightError as exc:
        print(f"BodyRig Photoreal reference vision preflight: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", **result}, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
