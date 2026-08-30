from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .sith_input import SithInputError, stage_sith_input
from .sith_prepare import SithPrepareError, prepare_sith_input
from .sith_reconstruct import DEFAULT_SEED, SMPLX_GENDERS, SithReconstructError, reconstruct_sith
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter
from .wsl_file_digest import WslFileDigestError, digest_wsl_file
from .wsl_process import run_wsl_file_capture

ADAPTER = "sith-smplx-vrm"
REVISION = "1"
SHA256_LENGTH = 64
RECON_CHECKPOINT_HASH_ENV = "BODYRIG_SITH_RECON_CHECKPOINT_SHA256"
SMPLX_CHECKPOINT_HASH_ENV = "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256"
BODY_MODEL_GENDER_ENV = "BODYRIG_SITH_BODY_MODEL_GENDER"


class SithFitterOrchestratorError(RuntimeError):
    pass


def _run(command: Sequence[str], *, timeout: int = 86_400) -> subprocess.CompletedProcess[str]:
    return run_wsl_file_capture(command, timeout=timeout)


def _wsl_path(path: str | Path, *, distribution: str, wsl_exe: str) -> str:
    source = str(Path(path).expanduser().resolve())
    try:
        value = make_wsl_path_converter(wsl_exe, distribution)(source)
    except (OSError, WslBridgeError) as exc:
        raise SithFitterOrchestratorError(f"WSL path translation failed: {exc}") from exc
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithFitterOrchestratorError("WSL path translation returned an invalid Linux path")
    return value


def _validate_linux_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithFitterOrchestratorError(f"{label} must be an absolute Linux path")
    return value.rstrip("/") or "/"


def _required_sha256_from_environment(name: str) -> str:
    value = os.environ.get(name, "").strip().lower()
    if len(value) != SHA256_LENGTH or any(ch not in "0123456789abcdef" for ch in value):
        raise SithFitterOrchestratorError(f"{name} must contain the setup-bound lowercase SHA-256")
    return value


def _default_body_model_gender() -> str:
    value = os.environ.get(BODY_MODEL_GENDER_ENV, "neutral").strip().lower()
    if value not in SMPLX_GENDERS:
        raise SithFitterOrchestratorError(
            f"{BODY_MODEL_GENDER_ENV} must be one of: {', '.join(SMPLX_GENDERS)}"
        )
    return value


def _verify_checkpoint_authority(
    *,
    distribution: str,
    sith_repo: str,
    sith_python: str,
    wsl_exe: str,
) -> None:
    expected = (
        (
            "recon_model",
            f"{sith_repo}/checkpoints/recon_model.pth",
            _required_sha256_from_environment(RECON_CHECKPOINT_HASH_ENV),
        ),
        (
            "save_smplerx",
            f"{sith_repo}/checkpoints/save_smplerx.pth",
            _required_sha256_from_environment(SMPLX_CHECKPOINT_HASH_ENV),
        ),
    )
    for label, path, expected_sha256 in expected:
        try:
            digest = digest_wsl_file(
                distribution=distribution,
                python=sith_python,
                path=path,
                wsl_exe=wsl_exe,
            )
        except WslFileDigestError as exc:
            raise SithFitterOrchestratorError(f"SiTH {label} checkpoint authority check failed") from exc
        if digest["sha256"] != expected_sha256:
            raise SithFitterOrchestratorError(
                f"SiTH {label} checkpoint SHA-256 mismatch at fitter point-of-use"
            )


def orchestrate_sith_fitter(
    *,
    request: str | Path,
    workspace: str | Path,
    output: str | Path,
    adapter: str,
    revision: str,
    distribution: str,
    sith_repo: str,
    sith_python: str,
    openpose: str,
    diffusion_model: str,
    diffusion_model_sha256: str,
    seed: int = DEFAULT_SEED,
    wsl_exe: str = "wsl.exe",
    body_model_gender: str = "neutral",
) -> None:
    if adapter != ADAPTER or revision != REVISION:
        raise SithFitterOrchestratorError("builtin SiTH fitter adapter/revision mismatch")
    if not isinstance(distribution, str) or not distribution.strip() or len(distribution) > 160:
        raise SithFitterOrchestratorError("WSL distribution is invalid")
    if not isinstance(wsl_exe, str) or not wsl_exe.strip():
        raise SithFitterOrchestratorError("WSL executable is required")
    body_model_gender = str(body_model_gender).strip().lower()
    if body_model_gender not in SMPLX_GENDERS:
        raise SithFitterOrchestratorError(
            f"SMPL-X gender must be one of: {', '.join(SMPLX_GENDERS)}"
        )
    distribution = distribution.strip()
    sith_repo = _validate_linux_path(sith_repo, label="SiTH repo")
    sith_python = _validate_linux_path(sith_python, label="SiTH Python")
    openpose = _validate_linux_path(openpose, label="OpenPose executable")
    diffusion_model = _validate_linux_path(diffusion_model, label="SiTH diffusion model")
    smplx_model_dir = f"{sith_repo}/data/body_models/smplx"

    request_path = Path(request).expanduser().resolve()
    workspace_path = Path(workspace).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if not request_path.is_file():
        raise SithFitterOrchestratorError("BodyRig fitter request is missing")
    if not workspace_path.is_dir():
        raise SithFitterOrchestratorError("BodyRig private fitter workspace is missing")
    if not output_path.is_dir() or any(output_path.iterdir()):
        raise SithFitterOrchestratorError("BodyRig fitter output must be an existing empty directory")

    _verify_checkpoint_authority(
        distribution=distribution,
        sith_repo=sith_repo,
        sith_python=sith_python,
        wsl_exe=wsl_exe,
    )

    stage_sith_input(workspace_path)
    prepare_sith_input(
        workspace=workspace_path,
        distribution=distribution,
        repo=sith_repo,
        python=sith_python,
        openpose=openpose,
        wsl_exe=wsl_exe,
    )
    reconstruct_sith(
        workspace=workspace_path,
        distribution=distribution,
        repo=sith_repo,
        python=sith_python,
        diffusion_model=diffusion_model,
        diffusion_model_sha256=diffusion_model_sha256,
        seed=seed,
        wsl_exe=wsl_exe,
        body_model_gender=body_model_gender,
    )

    bridge = Path(__file__).resolve().parent / "bridges" / "sith_smplx_vrm_fitter_gender.py"
    if not bridge.is_file():
        raise SithFitterOrchestratorError("builtin gender-aware SiTH SMPL-X VRM bridge is missing")
    linux_bridge = _wsl_path(bridge, distribution=distribution, wsl_exe=wsl_exe)
    linux_request = _wsl_path(request_path, distribution=distribution, wsl_exe=wsl_exe)
    linux_workspace = _wsl_path(workspace_path, distribution=distribution, wsl_exe=wsl_exe)
    linux_output = _wsl_path(output_path, distribution=distribution, wsl_exe=wsl_exe)

    invocation = [
        wsl_exe,
        "-d",
        distribution,
        "--",
        sith_python,
        linux_bridge,
        "--bodyrig-smplx-gender",
        body_model_gender,
        "--smplx-model-dir",
        smplx_model_dir,
        "--bodyrig-request",
        linux_request,
        "--bodyrig-workspace",
        linux_workspace,
        "--bodyrig-output",
        linux_output,
        "--bodyrig-adapter",
        ADAPTER,
        "--bodyrig-revision",
        REVISION,
    ]
    try:
        completed = _run(invocation, timeout=86_400)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SithFitterOrchestratorError("SiTH SMPL-X VRM bridge could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-3000:]
        raise SithFitterOrchestratorError(
            f"SiTH SMPL-X VRM bridge failed with exit code {completed.returncode}: {detail}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run BodyRig's builtin pinned SiTH -> SMPL-X -> skinned VRM high-fidelity fitter."
    )
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--sith-python", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--diffusion-model", required=True)
    parser.add_argument("--diffusion-model-sha256", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--body-model-gender", choices=SMPLX_GENDERS, default=None)
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        resolved_gender = args.body_model_gender or _default_body_model_gender()
        orchestrate_sith_fitter(
            request=args.bodyrig_request,
            workspace=args.bodyrig_workspace,
            output=args.bodyrig_output,
            adapter=args.bodyrig_adapter,
            revision=args.bodyrig_revision,
            distribution=args.distribution,
            sith_repo=args.sith_repo,
            sith_python=args.sith_python,
            openpose=args.openpose,
            diffusion_model=args.diffusion_model,
            diffusion_model_sha256=args.diffusion_model_sha256,
            seed=args.seed,
            wsl_exe=args.wsl_exe,
            body_model_gender=resolved_gender,
        )
    except (
        OSError,
        SithInputError,
        SithPrepareError,
        SithReconstructError,
        WslFileDigestError,
        SithFitterOrchestratorError,
    ) as exc:
        print(f"BodyRig builtin SiTH fitter: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"BodyRig builtin SiTH fitter: PASS | gender={resolved_gender}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
