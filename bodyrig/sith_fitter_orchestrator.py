from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .sith_input import SithInputError, stage_sith_input
from .sith_prepare import SithPrepareError, prepare_sith_input
from .sith_reconstruct import (
    DEFAULT_SEED,
    SMPLX_GENDERS,
    SithReconstructError,
    load_prepared_input,
    reconstruct_sith,
    validate_reconstruction_outputs,
)
from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter
from .wsl_file_digest import WslFileDigestError, digest_wsl_file
from .wsl_process import run_wsl_file_capture

ADAPTER = "sith-smplx-vrm"
REVISION = "1"
SHA256_LENGTH = 64
RECON_CHECKPOINT_HASH_ENV = "BODYRIG_SITH_RECON_CHECKPOINT_SHA256"
SMPLX_CHECKPOINT_HASH_ENV = "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256"
BODY_MODEL_GENDER_ENV = "BODYRIG_SITH_BODY_MODEL_GENDER"
RECON_FORMAT = "bodyrig-sith-reconstruction"
RECON_VERSION = 1


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


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithFitterOrchestratorError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithFitterOrchestratorError(f"{label} must be an object")
    return value


def _validate_resume_reconstruction(
    workspace: Path,
    *,
    diffusion_model_sha256: str,
    seed: int,
) -> None:
    """Validate a completed same-workspace SiTH checkpoint before expensive-stage resume.

    Resume is intentionally all-or-nothing: only a complete reconstruction receipt
    whose prepared-input binding and output byte hashes still match may skip staging,
    OpenPose, SMPL-X fitting, hallucination and UV reconstruction. The downstream
    SMPL-X -> VRM bridge independently revalidates subject binding and artifact hashes.
    """

    if not isinstance(diffusion_model_sha256, str) or len(diffusion_model_sha256) != SHA256_LENGTH:
        raise SithFitterOrchestratorError("SiTH resume diffusion model SHA-256 is invalid")
    if any(ch not in "0123456789abcdef" for ch in diffusion_model_sha256):
        raise SithFitterOrchestratorError("SiTH resume diffusion model SHA-256 is invalid")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2_147_483_647:
        raise SithFitterOrchestratorError("SiTH resume seed is invalid")

    try:
        stage, prep, prep_sha256 = load_prepared_input(workspace)
    except SithReconstructError as exc:
        raise SithFitterOrchestratorError(f"SiTH resume prepared input is invalid: {exc}") from exc

    evidence_path = stage / "reconstruction.json"
    if not evidence_path.is_file():
        raise SithFitterOrchestratorError("SiTH resume reconstruction evidence is missing")
    evidence = _load_json_object(evidence_path, label="SiTH resume reconstruction evidence")
    required = {
        "format",
        "version",
        "prepared_input_sha256",
        "subject_track_id",
        "sith_revision",
        "diffusion_model_sha256",
        "diffusion_model_file_count",
        "diffusion_model_byte_count",
        "seed",
        "hallucination",
        "reconstruction",
    }
    if set(evidence) != required:
        raise SithFitterOrchestratorError("SiTH resume reconstruction evidence fields do not match v1")
    if evidence["format"] != RECON_FORMAT or evidence["version"] != RECON_VERSION:
        raise SithFitterOrchestratorError("SiTH resume reconstruction evidence format/version mismatch")
    if evidence["prepared_input_sha256"] != prep_sha256:
        raise SithFitterOrchestratorError("SiTH resume reconstruction is not bound to current prepared input")
    if evidence["subject_track_id"] != prep["subject_track_id"]:
        raise SithFitterOrchestratorError("SiTH resume reconstruction subject mismatch")
    if evidence["sith_revision"] != prep["sith_revision"]:
        raise SithFitterOrchestratorError("SiTH resume reconstruction revision mismatch")
    if evidence["diffusion_model_sha256"] != diffusion_model_sha256:
        raise SithFitterOrchestratorError("SiTH resume diffusion model SHA-256 mismatch")
    if evidence["seed"] != seed:
        raise SithFitterOrchestratorError("SiTH resume seed mismatch")
    for field in ("diffusion_model_file_count", "diffusion_model_byte_count"):
        value = evidence[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SithFitterOrchestratorError(f"SiTH resume {field} is invalid")
    if evidence["hallucination"] != {
        "num_validation_images": 1,
        "num_inference_steps": 50,
        "offline": True,
    }:
        raise SithFitterOrchestratorError("SiTH resume hallucination profile mismatch")

    try:
        outputs = validate_reconstruction_outputs(stage)
    except SithReconstructError as exc:
        raise SithFitterOrchestratorError(f"SiTH resume reconstruction artifacts are invalid: {exc}") from exc
    details = evidence["reconstruction"]
    detail_fields = {"grid_size", "save_uv", *outputs.keys()}
    if not isinstance(details, dict) or set(details) != detail_fields:
        raise SithFitterOrchestratorError("SiTH resume reconstruction detail fields do not match v1")
    if details["grid_size"] != 300 or details["save_uv"] is not True:
        raise SithFitterOrchestratorError("SiTH resume reconstruction is not the pinned UV profile")
    for field, actual in outputs.items():
        if details[field] != actual:
            raise SithFitterOrchestratorError(f"SiTH resume reconstruction {field} mismatch")


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

    reconstruction_evidence = workspace_path / "sith-input-v1" / "reconstruction.json"
    if reconstruction_evidence.is_file():
        _validate_resume_reconstruction(
            workspace_path,
            diffusion_model_sha256=diffusion_model_sha256,
            seed=seed,
        )
    else:
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
