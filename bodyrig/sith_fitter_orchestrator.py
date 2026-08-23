from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .sith_input import SithInputError, stage_sith_input
from .sith_prepare import SithPrepareError, prepare_sith_input
from .sith_reconstruct import DEFAULT_SEED, SithReconstructError, reconstruct_sith

ADAPTER = "sith-smplx-vrm"
REVISION = "1"


class SithFitterOrchestratorError(RuntimeError):
    pass


def _run(command: Sequence[str], *, timeout: int = 86_400) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def _wsl_path(path: str | Path, *, distribution: str, wsl_exe: str) -> str:
    source = str(Path(path).expanduser().resolve())
    try:
        completed = _run(
            [wsl_exe, "-d", distribution, "--", "wslpath", "-a", source],
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SithFitterOrchestratorError("WSL path translation could not complete") from exc
    if completed.returncode != 0:
        raise SithFitterOrchestratorError("WSL path translation failed")
    value = completed.stdout.strip()
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithFitterOrchestratorError("WSL path translation returned an invalid Linux path")
    return value


def _validate_linux_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithFitterOrchestratorError(f"{label} must be an absolute Linux path")
    return value.rstrip("/") or "/"


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
) -> None:
    if adapter != ADAPTER or revision != REVISION:
        raise SithFitterOrchestratorError("builtin SiTH fitter adapter/revision mismatch")
    if not isinstance(distribution, str) or not distribution.strip() or len(distribution) > 160:
        raise SithFitterOrchestratorError("WSL distribution is invalid")
    if not isinstance(wsl_exe, str) or not wsl_exe.strip():
        raise SithFitterOrchestratorError("WSL executable is required")
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

    stage_sith_input(workspace_path)
    prepare_sith_input(
        workspace=workspace_path,
        distribution=distribution.strip(),
        repo=sith_repo,
        python=sith_python,
        openpose=openpose,
        wsl_exe=wsl_exe,
    )
    reconstruct_sith(
        workspace=workspace_path,
        distribution=distribution.strip(),
        repo=sith_repo,
        python=sith_python,
        diffusion_model=diffusion_model,
        diffusion_model_sha256=diffusion_model_sha256,
        seed=seed,
        wsl_exe=wsl_exe,
    )

    bridge = Path(__file__).resolve().parent / "bridges" / "sith_smplx_vrm_fitter.py"
    if not bridge.is_file():
        raise SithFitterOrchestratorError("builtin SiTH SMPL-X VRM bridge is missing")
    linux_bridge = _wsl_path(bridge, distribution=distribution.strip(), wsl_exe=wsl_exe)
    linux_request = _wsl_path(request_path, distribution=distribution.strip(), wsl_exe=wsl_exe)
    linux_workspace = _wsl_path(workspace_path, distribution=distribution.strip(), wsl_exe=wsl_exe)
    linux_output = _wsl_path(output_path, distribution=distribution.strip(), wsl_exe=wsl_exe)

    invocation = [
        wsl_exe,
        "-d",
        distribution.strip(),
        "--",
        sith_python,
        linux_bridge,
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
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
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
        )
    except (
        OSError,
        SithInputError,
        SithPrepareError,
        SithReconstructError,
        SithFitterOrchestratorError,
    ) as exc:
        print(f"BodyRig builtin SiTH fitter: FAIL: {exc}", file=sys.stderr)
        return 1
    print("BodyRig builtin SiTH fitter: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
