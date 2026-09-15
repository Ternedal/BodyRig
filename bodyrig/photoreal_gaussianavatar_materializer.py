from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

PLAN_FORMAT = "bodyrig-photoreal-teacher-comparison-plan"
PLAN_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-gaussianavatar-materialization-request"
RECEIPT_FORMAT = "bodyrig-photoreal-gaussianavatar-materialization-receipt"
VERSION = 1
UPSTREAM_COMMIT = "d981c62238ef64e89dcc04719d2ebbb4758b080a"


class PhotorealGaussianAvatarMaterializerError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealGaussianAvatarMaterializerError(f"{label} is invalid")
    return result


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealGaussianAvatarMaterializerError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_plan(plan: Mapping[str, Any]) -> tuple[str, str, str, str, list[dict[str, Any]]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealGaussianAvatarMaterializerError("teacher comparison plan format/version mismatch")
    declared = _sha(plan.get("comparison_plan_sha256"), label="comparison plan SHA-256")
    if _digest(plan, omit="comparison_plan_sha256") != declared:
        raise PhotorealGaussianAvatarMaterializerError("teacher comparison plan digest mismatch")
    if plan.get("all_benchmarks_share_identical_training_subset") is not True:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan does not bind identical training subset")
    if plan.get("held_out_evaluation_is_external_to_all_teacher_processes") is not True:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan held-out policy is invalid")
    if plan.get("evaluation_source_paths_serialized") is not False:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan serialized evaluation paths")
    if plan.get("photoreal_acceptance_authority") is not False or plan.get("production_activation") is not False:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan crossed downstream authority")

    benchmark_entries = [
        item for item in plan.get("benchmarks", [])
        if isinstance(item, Mapping) and item.get("benchmark") == "gaussianavatar"
    ]
    if len(benchmark_entries) != 1:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan lacks unique GaussianAvatar entry")
    benchmark = benchmark_entries[0]
    if benchmark.get("upstream_ref") != UPSTREAM_COMMIT:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar comparison commit mismatch")
    if benchmark.get("source_candidate_eligible") is not True:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan has no eligible GaussianAvatar source candidate")
    if benchmark.get("held_out_evaluation_disclosed") is not False:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar comparison entry disclosed held-out evaluation")

    source_key = _text(plan.get("selected_source_key"), label="selected source key", maximum=4096)
    source_sha = _sha(plan.get("selected_source_sha256"), label="selected source SHA-256")
    resolved = _text(plan.get("selected_source_resolved_path"), label="selected train source path")
    if plan.get("selected_source_projection") != "flat" or plan.get("selected_source_stereo_layout") != "mono":
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar comparison source must be flat mono")
    observations_raw = plan.get("selected_observations")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise PhotorealGaussianAvatarMaterializerError("comparison plan has no selected observations")
    if int(plan.get("selected_observation_count") or 0) != len(observations_raw):
        raise PhotorealGaussianAvatarMaterializerError("comparison observation count mismatch")
    observations: list[dict[str, Any]] = []
    for raw in observations_raw:
        if not isinstance(raw, Mapping) or raw.get("source_key") != source_key or raw.get("eye") != "mono":
            raise PhotorealGaussianAvatarMaterializerError("comparison observation source/eye mismatch")
        observations.append({
            "source_key": source_key,
            "frame_sha256": _sha(raw.get("frame_sha256"), label="comparison frame SHA-256"),
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": "mono",
        })
    return declared, source_key, source_sha, resolved, observations


def _build_request(plan: Mapping[str, Any], *, comparison_sha: str, source_key: str, source_sha: str, linux_source: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    if not linux_source.startswith("/"):
        raise PhotorealGaussianAvatarMaterializerError("translated train source path is not absolute Linux path")
    return {
        "format": REQUEST_FORMAT,
        "version": VERSION,
        "benchmark": "gaussianavatar",
        "upstream_commit": UPSTREAM_COMMIT,
        "comparison_plan_sha256": comparison_sha,
        "teacher_input_sha256": _sha(plan.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "performer_id": _text(plan.get("performer_id"), label="performer id", maximum=256),
        "selected_epoch_id": _text(plan.get("selected_epoch_id"), label="selected epoch id", maximum=256),
        "smpl_gender": "female",
        "smpl_type": "smpl",
        "source": {
            "source_key": source_key,
            "source_sha256": source_sha,
            "resolved_path": linux_source,
            "projection": "flat",
            "stereo_layout": "mono",
        },
        "observations": observations,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def _validate_receipt(receipt: Mapping[str, Any], *, request: Mapping[str, Any], output: Path) -> dict[str, Any]:
    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("version") != VERSION:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization receipt format/version mismatch")
    for field in ("comparison_plan_sha256", "teacher_input_sha256", "performer_id", "selected_epoch_id", "upstream_commit"):
        if receipt.get(field) != request.get(field):
            raise PhotorealGaussianAvatarMaterializerError(f"GaussianAvatar receipt provenance mismatch: {field}")
    if receipt.get("smpl_gender") != "female" or receipt.get("smpl_type") != "smpl":
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar receipt geometry-prior mismatch")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization disclosed forbidden source/eval bytes")
    if receipt.get("exact_p0_frame_hashes_reproduced") is not True:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization did not reproduce P0 frame hashes")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization crossed downstream authority")
    frames = receipt.get("frames")
    if not isinstance(frames, list) or len(frames) != len(request["observations"]):
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization frame cardinality mismatch")
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping) or frame.get("gaussianavatar_frame_index") != index:
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization frame index mismatch")
        expected = request["observations"][index]
        if frame.get("source_key") != expected["source_key"] or frame.get("source_frame_sha256") != expected["frame_sha256"]:
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization frame provenance mismatch")
        relative = f"train/images/{index:08d}.png"
        if frame.get("relative_path") != relative:
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization frame path mismatch")
        path = output / relative
        if not path.is_file() or _file_sha(path) != _sha(frame.get("staged_png_sha256"), label="staged PNG SHA-256"):
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar staged PNG bytes mismatch")
    if (output / "test").exists():
        raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization unexpectedly contains test/eval directory")
    return dict(receipt)


def materialize_gaussianavatar_benchmark(
    plan: Mapping[str, Any],
    *,
    workspace: str | Path,
    tool_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    comparison_sha, source_key, source_sha, resolved, observations = _validate_plan(plan)
    root = Path(workspace).expanduser().resolve()
    tool = Path(tool_path).expanduser().resolve()
    if root.exists():
        raise PhotorealGaussianAvatarMaterializerError(f"GaussianAvatar materialization workspace already exists: {root}")
    if not tool.is_file():
        raise PhotorealGaussianAvatarMaterializerError(f"GaussianAvatar materializer tool not found: {tool}")
    root.mkdir(parents=True)
    log_path = root / "materializer.log"
    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_source = converter(resolved)
        request = _build_request(
            plan,
            comparison_sha=comparison_sha,
            source_key=source_key,
            source_sha=source_sha,
            linux_source=linux_source,
            observations=observations,
        )
        with tempfile.TemporaryDirectory(prefix="bodyrig-gaussianavatar-materialize-") as temp:
            request_path = Path(temp) / "request.json"
            request_path.write_text(json.dumps(request, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            linux_request = converter(str(request_path))
            linux_output = converter(str(root))
            linux_tool = converter(str(tool))
            invocation = [
                wsl_exe,
                "-d",
                _text(distribution, label="WSL distribution", maximum=160),
                "--",
                _text(linux_python, label="Linux Python"),
                linux_tool,
                "--request",
                linux_request,
                "--output",
                linux_output,
            ]
            completed = subprocess.run(
                invocation,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
            )
            log_path.write_text(completed.stdout or "", encoding="utf-8")
            if completed.returncode != 0:
                raise PhotorealGaussianAvatarMaterializerError(
                    f"GaussianAvatar materializer exited with code {completed.returncode}: {(completed.stdout or '')[-6000:].strip()}"
                )
        receipt_path = root / "materialization-receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization receipt is unreadable") from exc
        if not isinstance(receipt, dict):
            raise PhotorealGaussianAvatarMaterializerError("GaussianAvatar materialization receipt is invalid")
        return _validate_receipt(receipt, request=request, output=root)
    except (OSError, WslBridgeError, PhotorealGaussianAvatarMaterializerError):
        raise
