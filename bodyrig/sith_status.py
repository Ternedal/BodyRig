from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from .sith_model import SithModelError, digest_model_tree
from .sith_preflight import SithPreflightError, run_preflight

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

ENVIRONMENT = {
    "distribution": "BODYRIG_SITH_DISTRIBUTION",
    "repo": "BODYRIG_SITH_REPO",
    "python": "BODYRIG_SITH_PYTHON",
    "openpose": "BODYRIG_SITH_OPENPOSE",
    "diffusion_model": "BODYRIG_SITH_DIFFUSION_MODEL",
    "diffusion_sha256": "BODYRIG_SITH_DIFFUSION_SHA256",
}


def _setting(explicit: str | None, key: str, *, default: str = "") -> str:
    if explicit is not None and explicit.strip():
        return explicit.strip()
    value = os.environ.get(ENVIRONMENT[key], "").strip()
    return value or default


def collect_status(
    *,
    distribution: str | None = None,
    repo: str | None = None,
    python: str | None = None,
    openpose: str | None = None,
    diffusion_model: str | None = None,
    diffusion_sha256: str | None = None,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    settings = {
        "distribution": _setting(distribution, "distribution", default="Ubuntu-22.04"),
        "repo": _setting(repo, "repo"),
        "python": _setting(python, "python"),
        "openpose": _setting(openpose, "openpose"),
        "diffusion_model": _setting(diffusion_model, "diffusion_model"),
        "diffusion_sha256": _setting(diffusion_sha256, "diffusion_sha256").lower(),
    }
    missing = [
        ENVIRONMENT[key]
        for key in ("repo", "python", "openpose", "diffusion_model", "diffusion_sha256")
        if not settings[key]
    ]
    result: dict[str, Any] = {
        "format": "bodyrig-sith-status",
        "version": 1,
        "ready": False,
        "distribution": settings["distribution"],
        "configured": not missing,
        "missing_settings": missing,
        "preflight": None,
        "diffusion_model": None,
        "errors": [],
    }
    if missing:
        result["errors"].append("SiTH settings are incomplete")
        return result
    if not SHA_RE.fullmatch(settings["diffusion_sha256"]):
        result["errors"].append("BODYRIG_SITH_DIFFUSION_SHA256 is not a lowercase SHA-256")
        return result
    for key in ("repo", "python", "openpose", "diffusion_model"):
        if not settings[key].startswith("/"):
            result["errors"].append(f"{ENVIRONMENT[key]} must be an absolute Linux path")
    if result["errors"]:
        return result

    try:
        preflight = run_preflight(
            distribution=settings["distribution"],
            repo=settings["repo"],
            python=settings["python"],
            openpose=settings["openpose"],
            wsl_exe=wsl_exe,
        )
    except (OSError, SithPreflightError) as exc:
        result["errors"].append(f"SiTH preflight could not complete: {exc}")
        return result
    result["preflight"] = {
        "ok": bool(preflight.get("ok")),
        "errors": list(preflight.get("errors", [])),
        "revision": preflight.get("revision"),
        "cuda_device": (preflight.get("environment") or {}).get("cuda_device"),
    }
    if not preflight.get("ok"):
        result["errors"].extend(str(item) for item in preflight.get("errors", []))
        return result

    try:
        digest = digest_model_tree(
            distribution=settings["distribution"],
            python=settings["python"],
            model_path=settings["diffusion_model"],
            wsl_exe=wsl_exe,
        )
    except (OSError, SithModelError) as exc:
        result["errors"].append(f"SiTH diffusion model digest could not complete: {exc}")
        return result
    result["diffusion_model"] = {
        "sha256": digest["sha256"],
        "file_count": digest["file_count"],
        "byte_count": digest["byte_count"],
        "expected_sha256": settings["diffusion_sha256"],
        "matches": digest["sha256"] == settings["diffusion_sha256"],
    }
    if digest["sha256"] != settings["diffusion_sha256"]:
        result["errors"].append("SiTH diffusion model tree digest mismatch")
        return result

    result["ready"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report whether the configured BodyRig SiTH high-fidelity path is physically ready.")
    parser.add_argument("--distribution")
    parser.add_argument("--repo")
    parser.add_argument("--python")
    parser.add_argument("--openpose")
    parser.add_argument("--diffusion-model")
    parser.add_argument("--diffusion-model-sha256")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    status = collect_status(
        distribution=args.distribution,
        repo=args.repo,
        python=args.python,
        openpose=args.openpose,
        diffusion_model=args.diffusion_model,
        diffusion_sha256=args.diffusion_model_sha256,
        wsl_exe=args.wsl_exe,
    )
    if args.json:
        print(json.dumps(status, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    elif status["ready"]:
        device = (status.get("preflight") or {}).get("cuda_device") or "unknown CUDA device"
        model = status.get("diffusion_model") or {}
        print(f"BodyRig SiTH status: READY | {device} | model {model.get('sha256', 'unknown')}")
    else:
        print("BodyRig SiTH status: NOT READY", file=sys.stderr)
        for setting in status["missing_settings"]:
            print(f"MISSING SETTING: {setting}", file=sys.stderr)
        for error in status["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
    return 0 if status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
