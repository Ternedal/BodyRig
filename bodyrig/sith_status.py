from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from .sith_model import SithModelError, digest_model_tree
from .sith_preflight import SithPreflightError, run_preflight
from .wsl_file_digest import WslFileDigestError, digest_wsl_file
from .wsl_tree_digest import WslTreeDigestError, digest_wsl_tree

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

ENVIRONMENT = {
    "distribution": "BODYRIG_SITH_DISTRIBUTION",
    "repo": "BODYRIG_SITH_REPO",
    "python": "BODYRIG_SITH_PYTHON",
    "openpose_repo": "BODYRIG_SITH_OPENPOSE_REPO",
    "openpose": "BODYRIG_SITH_OPENPOSE",
    "openpose_sha256": "BODYRIG_SITH_OPENPOSE_SHA256",
    "openpose_models_sha256": "BODYRIG_SITH_OPENPOSE_MODELS_SHA256",
    "recon_checkpoint_sha256": "BODYRIG_SITH_RECON_CHECKPOINT_SHA256",
    "smplerx_checkpoint_sha256": "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256",
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
    openpose_repo: str | None = None,
    openpose: str | None = None,
    openpose_sha256: str | None = None,
    openpose_models_sha256: str | None = None,
    recon_checkpoint_sha256: str | None = None,
    smplerx_checkpoint_sha256: str | None = None,
    diffusion_model: str | None = None,
    diffusion_sha256: str | None = None,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    settings = {
        "distribution": _setting(distribution, "distribution", default="Ubuntu-22.04"),
        "repo": _setting(repo, "repo"),
        "python": _setting(python, "python"),
        "openpose_repo": _setting(openpose_repo, "openpose_repo"),
        "openpose": _setting(openpose, "openpose"),
        "openpose_sha256": _setting(openpose_sha256, "openpose_sha256").lower(),
        "openpose_models_sha256": _setting(openpose_models_sha256, "openpose_models_sha256").lower(),
        "recon_checkpoint_sha256": _setting(recon_checkpoint_sha256, "recon_checkpoint_sha256").lower(),
        "smplerx_checkpoint_sha256": _setting(smplerx_checkpoint_sha256, "smplerx_checkpoint_sha256").lower(),
        "diffusion_model": _setting(diffusion_model, "diffusion_model"),
        "diffusion_sha256": _setting(diffusion_sha256, "diffusion_sha256").lower(),
    }
    required_keys = (
        "repo",
        "python",
        "openpose_repo",
        "openpose",
        "openpose_sha256",
        "openpose_models_sha256",
        "recon_checkpoint_sha256",
        "smplerx_checkpoint_sha256",
        "diffusion_model",
        "diffusion_sha256",
    )
    missing = [ENVIRONMENT[key] for key in required_keys if not settings[key]]
    result: dict[str, Any] = {
        "format": "bodyrig-sith-status",
        "version": 3,
        "ready": False,
        "distribution": settings["distribution"],
        "configured": not missing,
        "missing_settings": missing,
        "preflight": None,
        "checkpoints": {
            "recon_model": None,
            "smplerx": None,
        },
        "openpose_binary": None,
        "openpose_models": None,
        "diffusion_model": None,
        "errors": [],
    }
    if missing:
        result["errors"].append("SiTH settings are incomplete")
        return result
    for key in (
        "openpose_sha256",
        "openpose_models_sha256",
        "recon_checkpoint_sha256",
        "smplerx_checkpoint_sha256",
        "diffusion_sha256",
    ):
        if not SHA_RE.fullmatch(settings[key]):
            result["errors"].append(f"{ENVIRONMENT[key]} is not a lowercase SHA-256")
    for key in ("repo", "python", "openpose_repo", "openpose", "diffusion_model"):
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
            openpose_repo=settings["openpose_repo"],
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

    checkpoint_specs = (
        (
            "recon_model",
            settings["repo"].rstrip("/") + "/checkpoints/recon_model.pth",
            settings["recon_checkpoint_sha256"],
        ),
        (
            "smplerx",
            settings["repo"].rstrip("/") + "/checkpoints/save_smplerx.pth",
            settings["smplerx_checkpoint_sha256"],
        ),
    )
    for label, path, expected_sha256 in checkpoint_specs:
        try:
            checkpoint = digest_wsl_file(
                distribution=settings["distribution"],
                python=settings["python"],
                path=path,
                wsl_exe=wsl_exe,
            )
        except (OSError, WslFileDigestError) as exc:
            result["errors"].append(f"SiTH {label} checkpoint digest could not complete: {exc}")
            return result
        matches = checkpoint["sha256"] == expected_sha256
        result["checkpoints"][label] = {
            "sha256": checkpoint["sha256"],
            "byte_count": checkpoint["byte_count"],
            "expected_sha256": expected_sha256,
            "matches": matches,
        }
        if not matches:
            result["errors"].append(f"SiTH {label} checkpoint digest mismatch")
            return result

    try:
        binary = digest_wsl_file(
            distribution=settings["distribution"],
            python=settings["python"],
            path=settings["openpose"],
            wsl_exe=wsl_exe,
        )
    except (OSError, WslFileDigestError) as exc:
        result["errors"].append(f"OpenPose binary digest could not complete: {exc}")
        return result
    binary_matches = binary["sha256"] == settings["openpose_sha256"]
    result["openpose_binary"] = {
        "sha256": binary["sha256"],
        "byte_count": binary["byte_count"],
        "expected_sha256": settings["openpose_sha256"],
        "matches": binary_matches,
    }
    if not binary_matches:
        result["errors"].append("OpenPose binary digest mismatch")
        return result

    try:
        models = digest_wsl_tree(
            distribution=settings["distribution"],
            python=settings["python"],
            path=settings["openpose_repo"].rstrip("/") + "/models",
            wsl_exe=wsl_exe,
        )
    except (OSError, WslTreeDigestError) as exc:
        result["errors"].append(f"OpenPose model tree digest could not complete: {exc}")
        return result
    models_match = models["sha256"] == settings["openpose_models_sha256"]
    result["openpose_models"] = {
        "sha256": models["sha256"],
        "file_count": models["file_count"],
        "byte_count": models["byte_count"],
        "expected_sha256": settings["openpose_models_sha256"],
        "matches": models_match,
    }
    if not models_match:
        result["errors"].append("OpenPose model tree digest mismatch")
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
    parser.add_argument("--openpose-repo")
    parser.add_argument("--openpose")
    parser.add_argument("--openpose-sha256")
    parser.add_argument("--openpose-models-sha256")
    parser.add_argument("--recon-checkpoint-sha256")
    parser.add_argument("--smplerx-checkpoint-sha256")
    parser.add_argument("--diffusion-model")
    parser.add_argument("--diffusion-model-sha256")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    status = collect_status(
        distribution=args.distribution,
        repo=args.repo,
        python=args.python,
        openpose_repo=args.openpose_repo,
        openpose=args.openpose,
        openpose_sha256=args.openpose_sha256,
        openpose_models_sha256=args.openpose_models_sha256,
        recon_checkpoint_sha256=args.recon_checkpoint_sha256,
        smplerx_checkpoint_sha256=args.smplerx_checkpoint_sha256,
        diffusion_model=args.diffusion_model,
        diffusion_sha256=args.diffusion_model_sha256,
        wsl_exe=args.wsl_exe,
    )
    if args.json:
        print(json.dumps(status, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    elif status["ready"]:
        device = (status.get("preflight") or {}).get("cuda_device") or "unknown CUDA device"
        model = status.get("diffusion_model") or {}
        print(f"BodyRig SiTH status: READY | {device} | checkpoints verified | model {model.get('sha256', 'unknown')}")
    else:
        print("BodyRig SiTH status: NOT READY", file=sys.stderr)
        for setting in status["missing_settings"]:
            print(f"MISSING SETTING: {setting}", file=sys.stderr)
        for error in status["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
    return 0 if status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
