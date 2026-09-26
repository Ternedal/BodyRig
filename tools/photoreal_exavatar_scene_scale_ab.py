from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class SceneScaleABError(ValueError):
    pass


RASTERIZER_CLASSIFICATIONS = {
    "physical-scale-rasterizer-backward-nonfinite",
    "broad-rasterizer-backward-nonfinite",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic one-iteration ExAvatar scene-scale baseline and conditional rasterizer A/B."
    )
    parser.add_argument("--workspace-root", required=True)
    return parser


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SceneScaleABError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise SceneScaleABError(f"{label} must be a JSON object")
    return value


def _rasterizer_implicated(report: dict[str, Any]) -> bool:
    if report.get("forward_interpretation") not in {None, "finite"}:
        return False
    source = report.get("source_interpretation")
    if isinstance(source, dict):
        for value in source.values():
            if value in RASTERIZER_CLASSIFICATIONS:
                return True
    return report.get("combined_interpretation") in RASTERIZER_CLASSIFICATIONS


def _finite_abs_max(report: dict[str, Any], key: str) -> float | str | None:
    value = report.get(key)
    if not isinstance(value, dict):
        return None
    result = value.get("finite_abs_max")
    if isinstance(result, bool):
        return None
    if isinstance(result, (int, float, str)):
        return result
    return None


def _bad_count(report: dict[str, Any], key: str) -> int | None:
    value = report.get(key)
    if not isinstance(value, dict):
        return None
    count = value.get("bad_row_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def _require_report_identity(report: dict[str, Any], *, label: str) -> None:
    if report.get("format") != "bodyrig-exavatar-scene-scale-diagnostic":
        raise SceneScaleABError(f"{label} report format is invalid")
    if report.get("version") != 1:
        raise SceneScaleABError(f"{label} report version is invalid")
    if not isinstance(report.get("subject_id"), str) or not report["subject_id"].strip():
        raise SceneScaleABError(f"{label} report subject_id is invalid")
    for field in ("seed", "cur_itr", "scene_point_count"):
        value = report.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SceneScaleABError(f"{label} report {field} is invalid")
    frames = report.get("batch_frame_idx")
    if (
        not isinstance(frames, list)
        or not frames
        or any(isinstance(value, bool) or not isinstance(value, int) for value in frames)
    ):
        raise SceneScaleABError(f"{label} report batch_frame_idx is invalid")
    if report.get("camera_mode") not in {"virtual", "colmap"}:
        raise SceneScaleABError(f"{label} report camera_mode is invalid")
    cloud = report.get("background_point_cloud")
    cloud_sha = cloud.get("sha256") if isinstance(cloud, dict) else None
    if not isinstance(cloud_sha, str) or len(cloud_sha) != 64:
        raise SceneScaleABError(
            f"{label} report background_point_cloud.sha256 is invalid"
        )
    for field in (
        "batch_input_sha256",
        "scene_mean_sha256",
        "scene_log_scale_sha256",
        "scene_rotation_sha256",
        "scene_opacity_sha256",
        "scene_feature_dc_sha256",
        "scene_feature_rest_sha256",
    ):
        value = report.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise SceneScaleABError(f"{label} report {field} is invalid")
    render_sha = report.get("scene_render_sha256")
    if (
        not isinstance(render_sha, list)
        or not render_sha
        or any(not isinstance(value, str) or len(value) != 64 for value in render_sha)
    ):
        raise SceneScaleABError(
            f"{label} report scene_render_sha256 is invalid"
        )
    forward_params = report.get("forward_scene_parameters")
    required_forward_params = {
        "mean_scene",
        "log_scale_scene",
        "physical_scale_input",
        "rotation_scene",
        "opacity_scene",
    }
    if (
        not isinstance(forward_params, dict)
        or not required_forward_params.issubset(forward_params)
    ):
        raise SceneScaleABError(
            f"{label} report forward_scene_parameters is invalid"
        )
    for field in required_forward_params:
        item = forward_params.get(field)
        if not isinstance(item, dict) or not isinstance(item.get("all_finite"), bool):
            raise SceneScaleABError(
                f"{label} report forward_scene_parameters.{field} is invalid"
            )
    forward_renders = report.get("forward_scene_render_outputs")
    if not isinstance(forward_renders, list) or not forward_renders:
        raise SceneScaleABError(
            f"{label} report forward_scene_render_outputs is invalid"
        )
    render_hashes: list[str] = []
    for index, item in enumerate(forward_renders):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("all_finite"), bool)
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
        ):
            raise SceneScaleABError(
                f"{label} report forward_scene_render_outputs[{index}] is invalid"
            )
        render_hashes.append(item["sha256"])
    if render_hashes != render_sha:
        raise SceneScaleABError(
            f"{label} report forward render SHA fields disagree"
        )

    source_provenance = report.get("source_patch_provenance")
    if not isinstance(source_provenance, dict):
        raise SceneScaleABError(
            f"{label} report source_patch_provenance is invalid"
        )
    for field in ("loss_sha256", "custom_sha256"):
        value = source_provenance.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise SceneScaleABError(
                f"{label} report source_patch_provenance.{field} is invalid"
            )
    if not isinstance(report.get("loss_values"), dict):
        raise SceneScaleABError(f"{label} report loss_values is invalid")
    if not isinstance(report.get("nonfinite_loss"), list):
        raise SceneScaleABError(f"{label} report nonfinite_loss is invalid")
    extension = report.get("rasterizer_extension_sha256")
    if not isinstance(extension, str) or len(extension) != 64:
        raise SceneScaleABError(
            f"{label} report rasterizer_extension_sha256 is invalid"
        )


def _require_comparable_reports(
    baseline: dict[str, Any],
    patched: dict[str, Any],
) -> None:
    _require_report_identity(baseline, label="baseline")
    _require_report_identity(patched, label="patched")
    scalar_fields = (
        "format",
        "version",
        "subject_id",
        "seed",
        "cur_itr",
        "batch_frame_idx",
        "camera_mode",
        "scene_point_count",
        "batch_input_sha256",
        "scene_mean_sha256",
        "scene_log_scale_sha256",
        "scene_rotation_sha256",
        "scene_opacity_sha256",
        "scene_feature_dc_sha256",
        "scene_feature_rest_sha256",
        "scene_render_sha256",
        "forward_scene_parameters",
        "forward_scene_render_outputs",
    )
    mismatched = [
        field
        for field in scalar_fields
        if baseline.get(field) != patched.get(field)
    ]
    baseline_cloud = baseline.get("background_point_cloud")
    patched_cloud = patched.get("background_point_cloud")
    baseline_cloud_sha = (
        baseline_cloud.get("sha256")
        if isinstance(baseline_cloud, dict)
        else None
    )
    patched_cloud_sha = (
        patched_cloud.get("sha256")
        if isinstance(patched_cloud, dict)
        else None
    )
    if baseline_cloud_sha != patched_cloud_sha:
        mismatched.append("background_point_cloud.sha256")
    baseline_source = baseline.get("source_patch_provenance")
    patched_source = patched.get("source_patch_provenance")
    for field in ("loss_sha256", "custom_sha256"):
        baseline_value = (
            baseline_source.get(field)
            if isinstance(baseline_source, dict)
            else None
        )
        patched_value = (
            patched_source.get(field)
            if isinstance(patched_source, dict)
            else None
        )
        if baseline_value != patched_value:
            mismatched.append(f"source_patch_provenance.{field}")
    if baseline.get("loss_values") != patched.get("loss_values"):
        mismatched.append("loss_values")
    if baseline.get("nonfinite_loss") != patched.get("nonfinite_loss"):
        mismatched.append("nonfinite_loss")
    baseline_extension = baseline.get("rasterizer_extension_sha256")
    patched_extension = patched.get("rasterizer_extension_sha256")
    if (
        not isinstance(baseline_extension, str)
        or not isinstance(patched_extension, str)
        or len(baseline_extension) != 64
        or len(patched_extension) != 64
    ):
        mismatched.append("rasterizer_extension_sha256")
    elif baseline_extension == patched_extension:
        raise SceneScaleABError(
            "baseline/patched rasterizer extension digests are identical"
        )
    if mismatched:
        raise SceneScaleABError(
            "baseline/patched reports are not comparable; mismatched fields: "
            + ",".join(mismatched)
        )


def _source_gradient_matrix(report: dict[str, Any]) -> dict[str, Any]:
    source = report.get("source_scale_gradients")
    if not isinstance(source, dict):
        return {}
    matrix: dict[str, Any] = {}
    for loss_name in ("rgb_scene", "ssim_scene"):
        loss_report = source.get(loss_name)
        if not isinstance(loss_report, dict):
            matrix[loss_name] = {"missing": True}
            continue
        if "backward_error" in loss_report:
            matrix[loss_name] = {
                "backward_error": str(loss_report["backward_error"]),
            }
            continue
        row: dict[str, Any] = {}
        for param_name in (
            "render_scene_output",
            "mean_scene",
            "scale_scene",
            "physical_scale_input",
            "rotation_scene",
            "opacity_scene",
        ):
            param_report = loss_report.get(param_name)
            if not isinstance(param_report, dict):
                row[param_name] = None
                continue
            row[param_name] = {
                "used": param_report.get("used"),
                "all_finite": param_report.get("all_finite"),
                "bad_row_count": param_report.get("bad_row_count"),
                "nonfinite_value_count": param_report.get(
                    "nonfinite_value_count"
                ),
            }
        matrix[loss_name] = row
    return matrix


def _summarize_change(
    baseline: dict[str, Any],
    patched: dict[str, Any],
) -> str:
    baseline_bad = _bad_count(
        baseline,
        "combined_physical_scale_input_gradient",
    )
    patched_bad = _bad_count(
        patched,
        "combined_physical_scale_input_gradient",
    )
    patched_implicated = _rasterizer_implicated(patched)

    if not patched_implicated and patched_bad == 0:
        return "candidate-fix-eliminated-observed-rasterizer-nonfinite"
    if (
        baseline_bad is not None
        and patched_bad is not None
        and patched_bad < baseline_bad
    ):
        return "candidate-fix-reduced-observed-rasterizer-nonfinite"
    if baseline_bad == patched_bad:
        return "candidate-fix-did-not-change-observed-rasterizer-nonfinite-count"
    return "candidate-fix-changed-observation-without-eliminating-nonfinite"


def _run(
    argv: list[str],
    *,
    env: dict[str, str],
    log_path: Path,
    label: str,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if completed.returncode != 0:
        raise SceneScaleABError(
            f"{label} failed with code {completed.returncode}; log: {log_path}"
        )


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise SceneScaleABError(f"summary path may not be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".bodyrig-tmp")
    if temp.is_symlink():
        raise SceneScaleABError(f"summary temp path may not be a symlink: {temp}")
    if temp.exists():
        if not temp.is_file():
            raise SceneScaleABError(
                f"summary temp path is not a regular file: {temp}"
            )
        temp.unlink()
    temp.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise SceneScaleABError(f"workspace root is missing or unsafe: {root}")

    repo_root = Path(__file__).resolve().parents[1]
    diagnostic = repo_root / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    builder = repo_root / "tools" / "photoreal_exavatar_prepare_rasterizer_ab.py"
    for path, label in (
        (diagnostic, "scene-scale diagnostic"),
        (builder, "rasterizer A/B builder"),
    ):
        if not path.is_file() or path.is_symlink():
            raise SceneScaleABError(f"{label} is missing or unsafe: {path}")

    result_dir = root / "diagnostics" / "scene-scale-ab"
    if result_dir.is_symlink():
        raise SceneScaleABError("scene-scale A/B result directory may not be a symlink")
    result_dir.mkdir(parents=True, exist_ok=True)
    baseline_report = result_dir / "baseline.json"
    patched_report = result_dir / "conic-offdiag-fix.json"
    summary_path = result_dir / "comparison.json"

    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYOPENGL_PLATFORM"] = "egl"
    env["PYTHONPATH"] = str(repo_root)

    original_repo = root / "repos" / "diff-gaussian-rasterization-depth"
    _run(
        [
            sys.executable,
            str(diagnostic),
            "--workspace-root",
            str(root),
            "--gaussian-repo",
            str(original_repo),
            "--report-json",
            str(baseline_report),
        ],
        env=env,
        log_path=result_dir / "baseline.log",
        label="baseline scene-scale diagnostic",
    )
    baseline = _read_json(baseline_report, label="baseline scene-scale report")

    implicated = _rasterizer_implicated(baseline)
    summary: dict[str, Any] = {
        "format": "bodyrig-exavatar-scene-scale-ab-comparison",
        "version": 1,
        "baseline_report": baseline_report.as_posix(),
        "baseline_rasterizer_implicated": implicated,
        "baseline_forward_interpretation": baseline.get("forward_interpretation"),
        "baseline_source_interpretation": baseline.get("source_interpretation"),
        "baseline_combined_interpretation": baseline.get("combined_interpretation"),
        "ab_executed": False,
        "production_activation": False,
    }
    if not implicated:
        summary["outcome"] = (
            "baseline-forward-nonfinite"
            if baseline.get("forward_interpretation") not in {None, "finite"}
            else "baseline-did-not-implicate-rasterizer"
        )
        _write_json_atomic(summary_path, summary)
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0

    _run(
        [
            sys.executable,
            str(builder),
            "--workspace-root",
            str(root),
        ],
        env=env,
        log_path=result_dir / "prepare-conic-offdiag-fix.log",
        label="isolated rasterizer A/B build",
    )

    patched_repo = root / "diagnostics" / "rasterizer-conic-offdiag-fix"
    _run(
        [
            sys.executable,
            str(diagnostic),
            "--workspace-root",
            str(root),
            "--gaussian-repo",
            str(patched_repo),
            "--report-json",
            str(patched_report),
        ],
        env=env,
        log_path=result_dir / "conic-offdiag-fix.log",
        label="patched scene-scale diagnostic",
    )
    patched = _read_json(patched_report, label="patched scene-scale report")
    _require_comparable_reports(baseline, patched)
    patch_receipt_path = (
        patched_repo / "bodyrig-rasterizer-ab-receipt.json"
    )
    patch_receipt = _read_json(
        patch_receipt_path,
        label="rasterizer A/B receipt",
    )
    if patch_receipt.get("production_activation") is not False:
        raise SceneScaleABError(
            "rasterizer A/B receipt crossed production authority"
        )

    summary.update(
        {
            "ab_executed": True,
            "comparability_verified": True,
            "patched_report": patched_report.as_posix(),
            "patched_source_interpretation": patched.get(
                "source_interpretation"
            ),
            "patched_combined_interpretation": patched.get(
                "combined_interpretation"
            ),
            "baseline_gradient_matrix": _source_gradient_matrix(baseline),
            "patched_gradient_matrix": _source_gradient_matrix(patched),
            "patch_receipt": {
                "format": patch_receipt.get("format"),
                "version": patch_receipt.get("version"),
                "source_commit": patch_receipt.get("source_commit"),
                "patch": patch_receipt.get("patch"),
                "upstream_reference": patch_receipt.get("upstream_reference"),
                "source_backward_sha256": patch_receipt.get(
                    "source_backward_sha256"
                ),
                "patched_backward_sha256": patch_receipt.get(
                    "patched_backward_sha256"
                ),
                "extension_sha256": patch_receipt.get("extension_sha256"),
            },
            "baseline_rasterizer_extension_sha256": baseline.get(
                "rasterizer_extension_sha256"
            ),
            "patched_rasterizer_extension_sha256": patched.get(
                "rasterizer_extension_sha256"
            ),
            "baseline_combined_physical_bad_rows": _bad_count(
                baseline,
                "combined_physical_scale_input_gradient",
            ),
            "patched_combined_physical_bad_rows": _bad_count(
                patched,
                "combined_physical_scale_input_gradient",
            ),
            "baseline_combined_physical_finite_abs_max": _finite_abs_max(
                baseline,
                "combined_physical_scale_input_gradient",
            ),
            "patched_combined_physical_finite_abs_max": _finite_abs_max(
                patched,
                "combined_physical_scale_input_gradient",
            ),
            "baseline_combined_log_scale_finite_abs_max": _finite_abs_max(
                baseline,
                "combined_scale_gradient",
            ),
            "patched_combined_log_scale_finite_abs_max": _finite_abs_max(
                patched,
                "combined_scale_gradient",
            ),
            "outcome": _summarize_change(baseline, patched),
        }
    )
    _write_json_atomic(summary_path, summary)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SceneScaleABError as exc:
        print(f"BodyRig scene-scale A/B: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
