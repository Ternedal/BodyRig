from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any


class SceneScaleDiagnosticError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run exactly one ExAvatar training forward/backward to isolate scene-scale gradients."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument(
        "--gaussian-repo",
        default=None,
        help="Optional isolated Gaussian rasterizer repository to test.",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Optional path for the structured diagnostic JSON report.",
    )
    return parser


def _load_receipt(root: Path) -> dict[str, Any]:
    path = root / "workspace-receipt.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SceneScaleDiagnosticError("workspace receipt is unreadable") from exc
    if not isinstance(value, dict):
        raise SceneScaleDiagnosticError("workspace receipt must be an object")
    return value


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tensor_sha256(tensor) -> str:
    value = tensor.detach().cpu().contiguous().numpy()
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _stable_value_sha256(value: Any) -> str:
    import torch

    digest = hashlib.sha256()

    def feed(item: Any) -> None:
        if torch.is_tensor(item):
            digest.update(b"tensor\0")
            digest.update(_tensor_sha256(item).encode("ascii"))
            digest.update(b"\0")
            return
        if isinstance(item, dict):
            digest.update(b"dict\0")
            for key in sorted(item, key=lambda part: str(part)):
                digest.update(str(key).encode("utf-8"))
                digest.update(b"\0")
                feed(item[key])
            return
        if isinstance(item, (list, tuple)):
            digest.update(b"sequence\0")
            digest.update(str(len(item)).encode("ascii"))
            digest.update(b"\0")
            for child in item:
                feed(child)
            return
        if item is None:
            digest.update(b"none\0")
            return
        if isinstance(item, bool):
            digest.update(b"bool\0")
            digest.update(b"1" if item else b"0")
            digest.update(b"\0")
            return
        if isinstance(item, (int, float, str)):
            digest.update(type(item).__name__.encode("ascii"))
            digest.update(b"\0")
            digest.update(repr(item).encode("utf-8"))
            digest.update(b"\0")
            return
        raise SceneScaleDiagnosticError(
            f"unsupported diagnostic value for stable hash: {type(item).__name__}"
        )

    feed(value)
    return digest.hexdigest()


def _json_scalar(value: float) -> float | str:
    result = float(value)
    if math.isfinite(result):
        return result
    if math.isnan(result):
        return "nan"
    return "inf" if result > 0 else "-inf"


def _gradient_report(grad) -> dict[str, Any]:
    import torch

    if grad is None:
        return {"used": False}
    detached = grad.detach()
    finite = torch.isfinite(detached)
    bad = ~finite
    if detached.ndim >= 2:
        bad_rows = torch.nonzero(
            bad.reshape(detached.shape[0], -1).any(dim=1),
            as_tuple=False,
        ).flatten()
        first_bad_rows = bad_rows[:16].cpu().tolist()
        bad_row_count = int(bad_rows.numel())
    else:
        bad_indices = torch.nonzero(bad, as_tuple=False).flatten()
        first_bad_rows = bad_indices[:16].cpu().tolist()
        bad_row_count = int(bad_indices.numel())
    finite_values = detached[finite]
    finite_abs_max = (
        _json_scalar(float(finite_values.abs().max().cpu()))
        if finite_values.numel() > 0
        else None
    )
    return {
        "used": True,
        "all_finite": bool(finite.all()),
        "bad_row_count": bad_row_count,
        "first_bad_rows": first_bad_rows,
        "finite_abs_max": finite_abs_max,
    }


def _tensor_value_report(tensor) -> dict[str, Any]:
    import torch

    detached = tensor.detach()
    finite = torch.isfinite(detached)
    finite_values = detached[finite]
    return {
        "all_finite": bool(finite.all()),
        "nonfinite_value_count": int((~finite).sum().item()),
        "shape": list(detached.shape),
        "finite_min": (
            _json_scalar(float(finite_values.min().cpu()))
            if finite_values.numel() > 0 else None
        ),
        "finite_max": (
            _json_scalar(float(finite_values.max().cpu()))
            if finite_values.numel() > 0 else None
        ),
        "finite_abs_max": (
            _json_scalar(float(finite_values.abs().max().cpu()))
            if finite_values.numel() > 0 else None
        ),
    }


def _tensor_gradient_report(grad) -> dict[str, Any]:
    import torch

    if grad is None:
        return {"used": False}
    detached = grad.detach()
    finite = torch.isfinite(detached)
    bad_indices = torch.nonzero(~finite, as_tuple=False)
    finite_values = detached[finite]
    finite_abs_max = (
        _json_scalar(float(finite_values.abs().max().cpu()))
        if finite_values.numel() > 0
        else None
    )
    return {
        "used": True,
        "all_finite": bool(finite.all()),
        "nonfinite_value_count": int((~finite).sum().item()),
        "first_bad_indices": bad_indices[:16].cpu().tolist(),
        "shape": list(detached.shape),
        "finite_abs_max": finite_abs_max,
    }


def _report_is_nonfinite(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and report.get("used") is True
        and report.get("all_finite") is False
    )


def _classify_source_report(report: Any) -> str:
    if not isinstance(report, dict):
        return "invalid-report"
    if "backward_error" in report:
        return "backward-error"
    if report.get("missing") is True:
        return "missing-loss"
    render_bad = _report_is_nonfinite(report.get("render_scene_output"))
    physical_bad = _report_is_nonfinite(report.get("physical_scale_input"))
    log_bad = _report_is_nonfinite(report.get("scale_scene"))
    broader_bad = any(
        _report_is_nonfinite(report.get(name))
        for name in ("mean_scene", "rotation_scene", "opacity_scene")
    )
    if render_bad:
        return "loss-to-render-gradient-nonfinite"
    if physical_bad and broader_bad:
        return "broad-rasterizer-backward-nonfinite"
    if physical_bad:
        return "physical-scale-rasterizer-backward-nonfinite"
    if log_bad:
        return "log-scale-chain-nonfinite"
    if broader_bad:
        return "non-scale-scene-gradient-nonfinite"
    return "finite"


def _json_nested(value):
    if isinstance(value, (list, tuple)):
        return [_json_nested(item) for item in value]
    if isinstance(value, float):
        return _json_scalar(value)
    return value


def _scale_report(
    grad,
    *,
    scene_scale,
    scene_mean,
    stats,
) -> dict[str, Any]:
    import torch

    if grad is None:
        return {"used": False}
    detached = grad.detach()
    bad_rows = torch.nonzero(
        (~torch.isfinite(detached)).any(dim=1),
        as_tuple=False,
    ).flatten()
    first_rows = bad_rows[:16]
    physical = torch.exp(scene_scale.detach())
    visible = stats["is_vis"][0]
    radius = stats["radius"][0]
    return {
        "used": True,
        "all_finite": bool(torch.isfinite(detached).all()),
        "bad_row_count": int(bad_rows.numel()),
        "first_bad_rows": first_rows.cpu().tolist(),
        "first_bad_log_scale": _json_nested(
            scene_scale.detach()[first_rows].cpu().tolist()
            if first_rows.numel() else []
        ),
        "first_bad_physical_scale": _json_nested(
            physical[first_rows].cpu().tolist()
            if first_rows.numel() else []
        ),
        "first_bad_mean_3d": _json_nested(
            scene_mean[first_rows].cpu().tolist()
            if first_rows.numel() else []
        ),
        "first_bad_visible": (
            visible[first_rows].cpu().tolist()
            if first_rows.numel() else []
        ),
        "first_bad_radius": (
            radius[first_rows].cpu().tolist()
            if first_rows.numel() else []
        ),
        "physical_scale_min": _json_scalar(float(physical.min().cpu())),
        "physical_scale_max": _json_scalar(float(physical.max().cpu())),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise SceneScaleDiagnosticError(f"workspace root is missing or unsafe: {root}")

    receipt = _load_receipt(root)
    subject = str(receipt.get("subject_id") or "").strip()
    dataset_rel = str(receipt.get("working_dataset_relative_path") or "").strip()
    if not subject or not dataset_rel:
        raise SceneScaleDiagnosticError("workspace receipt lacks subject/dataset")
    dataset = root / dataset_rel
    if not dataset.is_dir() or dataset.is_symlink():
        raise SceneScaleDiagnosticError("workspace dataset is missing or unsafe")

    from tools import photoreal_exavatar_teacher_adapter as adapter

    preprocess_state = adapter._validate_preprocess(root, receipt)
    camera_mode = str(preprocess_state["camera_mode"]).strip().lower()
    cloud = adapter._validate_background_point_cloud(
        dataset,
        camera_mode=camera_mode,
    )

    exavatar = root / "repos" / "ExAvatar_RELEASE"
    exavatar_main = exavatar / "avatar" / "main"
    custom_source = exavatar / "avatar" / "data" / "Custom" / "Custom.py"
    loss_source = exavatar / "avatar" / "common" / "nets" / "loss.py"
    gaussian_repo = (
        Path(args.gaussian_repo).expanduser().resolve()
        if args.gaussian_repo
        else root / "repos" / "diff-gaussian-rasterization-depth"
    )
    for path, label in (
        (exavatar_main, "ExAvatar main"),
        (gaussian_repo, "Gaussian rasterizer"),
    ):
        if not path.is_dir() or path.is_symlink():
            raise SceneScaleDiagnosticError(f"{label} is missing or unsafe")

    arm_patch = adapter._ensure_arm_rgb_reg_empty_support_patch(loss_source)
    bbox_patch = adapter._ensure_avatar_custom_bbox_patch(custom_source)
    scene_sampling_patch = adapter._ensure_avatar_custom_scene_sampling_patch(
        custom_source
    )
    source_patch_provenance = {
        "loss_sha256": arm_patch["after_sha256"],
        "custom_sha256": scene_sampling_patch["after_sha256"],
        "arm_rgb_reg_applied_this_run": bool(arm_patch["applied"]),
        "bbox_applied_this_run": bool(bbox_patch["applied"]),
        "scene_sampling_applied_this_run": bool(scene_sampling_patch["applied"]),
    }

    sys.path.insert(0, str(gaussian_repo))
    sys.path.insert(0, str(exavatar_main))
    os.chdir(exavatar_main)

    import numpy as np
    import torch
    import diff_gaussian_rasterization_depth._C as rasterizer_ext
    from base import Trainer
    from config import cfg
    from nets.module import GaussianRenderer, SceneGaussian

    rasterizer_origin = Path(rasterizer_ext.__file__).resolve()
    try:
        rasterizer_relative_origin = rasterizer_origin.relative_to(
            gaussian_repo.resolve()
        ).as_posix()
    except ValueError as exc:
        raise SceneScaleDiagnosticError(
            f"Gaussian rasterizer extension imported outside requested repo: {rasterizer_origin}"
        ) from exc
    if not rasterizer_origin.is_file() or rasterizer_origin.is_symlink():
        raise SceneScaleDiagnosticError(
            f"Gaussian rasterizer extension origin is missing or unsafe: {rasterizer_origin}"
        )
    rasterizer_extension_sha256 = _file_sha(rasterizer_origin)

    original_scene_forward = SceneGaussian.forward
    original_renderer_forward = GaussianRenderer.forward

    def bodyrig_renderer_forward(self, gaussian_assets, *args, **kwargs):
        result = original_renderer_forward(self, gaussian_assets, *args, **kwargs)
        render_img = result.get("img")
        if render_img is not None and render_img.requires_grad:
            render_img.retain_grad()
        calls = getattr(self, "_bodyrig_diagnostic_calls", None)
        if calls is None:
            calls = []
            self._bodyrig_diagnostic_calls = calls
        calls.append(
            {
                "scale_input": gaussian_assets.get("scale"),
                "render_img": render_img,
            }
        )
        return result

    GaussianRenderer.forward = bodyrig_renderer_forward

    def bodyrig_scene_forward(self, cam_param):
        result = original_scene_forward(self, cam_param)
        physical_scale = result.get("scale")
        if physical_scale is None or not physical_scale.requires_grad:
            raise SceneScaleDiagnosticError(
                "scene physical scale is missing or not differentiable"
            )
        physical_scale.retain_grad()
        self._bodyrig_diagnostic_physical_scale = physical_scale
        return result

    SceneGaussian.forward = bodyrig_scene_forward

    seed = 0
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    cfg.set_args(subject)
    trainer = Trainer()
    trainer._make_batch_generator()
    trainer._make_model()

    try:
        data = next(iter(trainer.batch_generator))
    except StopIteration as exc:
        raise SceneScaleDiagnosticError("training dataset produced no batch") from exc

    frame_value = data.get("frame_idx")
    if frame_value is None:
        raise SceneScaleDiagnosticError("training batch omitted frame_idx")
    if hasattr(frame_value, "detach"):
        frame_indices = frame_value.detach().cpu().reshape(-1).tolist()
    elif isinstance(frame_value, (list, tuple)):
        frame_indices = [int(value) for value in frame_value]
    else:
        frame_indices = [int(frame_value)]
    if not frame_indices:
        raise SceneScaleDiagnosticError("training batch frame_idx is empty")

    cur_itr = 0
    cfg.set_stage(cur_itr)
    tot_itr = cfg.end_epoch * len(trainer.batch_generator)
    trainer.set_lr(cur_itr, tot_itr)
    trainer.optimizer.zero_grad()

    stats, raw_loss = trainer.model(data, cur_itr, "train")
    loss = {key: value.mean() for key, value in raw_loss.items()}
    nonfinite_loss = [
        key for key, value in loss.items()
        if not bool(torch.isfinite(value.detach()).all())
    ]

    scene_module = trainer.model.module.scene_gaussian
    scene_mean_param = scene_module.mean
    scene_scale = scene_module.scale
    scene_rotation = scene_module.rotation
    scene_opacity = scene_module.opacity
    scene_feature_dc = scene_module.feature_dc
    scene_feature_rest = scene_module.feature_rest
    scene_mean = scene_mean_param.detach()
    physical_scale_input = getattr(
        scene_module,
        "_bodyrig_diagnostic_physical_scale",
        None,
    )
    if physical_scale_input is None:
        raise SceneScaleDiagnosticError(
            "scene physical scale was not captured during forward"
        )
    renderer = trainer.model.module.gaussian_renderer
    render_calls = getattr(renderer, "_bodyrig_diagnostic_calls", [])
    scene_render_outputs = [
        item.get("render_img")
        for item in render_calls
        if item.get("scale_input") is physical_scale_input
        and item.get("render_img") is not None
    ]
    if not scene_render_outputs:
        raise SceneScaleDiagnosticError(
            "scene renderer output was not captured during forward"
        )
    forward_scene_parameters = {
        "mean_scene": _tensor_value_report(scene_mean_param),
        "log_scale_scene": _tensor_value_report(scene_scale),
        "physical_scale_input": _tensor_value_report(physical_scale_input),
        "rotation_scene": _tensor_value_report(scene_rotation),
        "opacity_scene": _tensor_value_report(scene_opacity),
    }
    forward_scene_render_outputs = [
        {
            **_tensor_value_report(render_img),
            "sha256": _tensor_sha256(render_img),
        }
        for render_img in scene_render_outputs
    ]
    scene_render_sha256 = [
        item["sha256"]
        for item in forward_scene_render_outputs
    ]
    scene_params = (
        scene_mean_param,
        scene_scale,
        scene_rotation,
        scene_opacity,
        physical_scale_input,
    )
    scene_param_names = (
        "mean_scene",
        "scale_scene",
        "rotation_scene",
        "opacity_scene",
        "physical_scale_input",
    )
    source_reports: dict[str, Any] = {}
    for name in ("rgb_scene", "ssim_scene"):
        value = loss.get(name)
        if value is None:
            source_reports[name] = {"missing": True}
            continue
        try:
            all_inputs = scene_params + tuple(scene_render_outputs)
            grads = torch.autograd.grad(
                value,
                all_inputs,
                retain_graph=True,
                allow_unused=True,
            )
            scene_param_grads = grads[:len(scene_params)]
            render_grads = grads[len(scene_params):]
            param_reports = {
                param_name: _gradient_report(grad)
                for param_name, grad in zip(scene_param_names, scene_param_grads)
            }
            param_reports["scale_scene"] = _scale_report(
                scene_param_grads[1],
                scene_scale=scene_scale,
                scene_mean=scene_mean,
                stats=stats,
            )
            param_reports["physical_scale_input"] = {
                **_gradient_report(scene_param_grads[4]),
                "first_bad_values": _json_nested(
                    physical_scale_input.detach()[
                        torch.nonzero(
                            (~torch.isfinite(scene_param_grads[4].detach())).any(dim=1),
                            as_tuple=False,
                        ).flatten()[:16]
                    ].cpu().tolist()
                    if scene_param_grads[4] is not None
                    and not bool(torch.isfinite(scene_param_grads[4].detach()).all())
                    else []
                ),
            }
            render_reports = [
                _tensor_gradient_report(grad)
                for grad in render_grads
            ]
            param_reports["render_scene_outputs"] = render_reports
            param_reports["render_scene_output"] = {
                "used": any(report.get("used") is True for report in render_reports),
                "all_finite": all(
                    report.get("all_finite") is True
                    for report in render_reports
                    if report.get("used") is True
                ),
                "render_count": len(render_reports),
                "nonfinite_value_count": sum(
                    int(report.get("nonfinite_value_count") or 0)
                    for report in render_reports
                ),
            }
            source_reports[name] = param_reports
        except RuntimeError as exc:
            source_reports[name] = {
                "backward_error": str(exc).replace("\n", " ")[:1000]
            }

    trainer.optimizer.zero_grad()
    physical_scale_input.grad = None
    combined_error = None
    try:
        sum(loss.values()).backward()
    except RuntimeError as exc:
        combined_error = str(exc).replace("\n", " ")[:2000]

    total_report = _scale_report(
        scene_scale.grad,
        scene_scale=scene_scale,
        scene_mean=scene_mean,
        stats=stats,
    )
    total_physical_scale_report = {
        **_gradient_report(physical_scale_input.grad),
        "input_min": _json_scalar(float(physical_scale_input.detach().min().cpu())),
        "input_max": _json_scalar(float(physical_scale_input.detach().max().cpu())),
    }

    nonfinite_groups: list[str] = []
    for group in trainer.optimizer.param_groups:
        group_name = str(group.get("name", "<unnamed>"))
        for param_index, param in enumerate(group["params"]):
            if param.grad is not None and not bool(torch.isfinite(param.grad).all()):
                nonfinite_groups.append(f"{group_name}[{param_index}]")

    forward_parameter_bad = any(
        item.get("all_finite") is False
        for item in forward_scene_parameters.values()
        if isinstance(item, dict)
    )
    forward_render_bad = any(
        item.get("all_finite") is False
        for item in forward_scene_render_outputs
        if isinstance(item, dict)
    )
    forward_interpretation = (
        "forward-scene-parameter-nonfinite"
        if forward_parameter_bad
        else (
            "forward-render-nonfinite"
            if forward_render_bad
            else "finite"
        )
    )

    interpretation = {
        name: _classify_source_report(report)
        for name, report in source_reports.items()
    }
    combined_interpretation = (
        "combined-backward-error"
        if combined_error is not None
        else (
            "physical-scale-rasterizer-backward-nonfinite"
            if _report_is_nonfinite(total_physical_scale_report)
            else (
                "log-scale-chain-nonfinite"
                if _report_is_nonfinite(total_report)
                else "finite"
            )
        )
    )

    result = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": subject,
        "seed": seed,
        "cur_itr": cur_itr,
        "batch_frame_idx": frame_indices,
        "loss_values": {
            key: _json_scalar(float(value.detach().cpu()))
            for key, value in sorted(loss.items())
        },
        "nonfinite_loss": nonfinite_loss,
        "background_point_cloud": cloud,
        "camera_mode": camera_mode,
        "scene_point_count": int(scene_scale.shape[0]),
        "batch_input_sha256": _stable_value_sha256(data),
        "scene_mean_sha256": _tensor_sha256(scene_mean_param),
        "scene_log_scale_sha256": _tensor_sha256(scene_scale),
        "scene_rotation_sha256": _tensor_sha256(scene_rotation),
        "scene_opacity_sha256": _tensor_sha256(scene_opacity),
        "scene_feature_dc_sha256": _tensor_sha256(scene_feature_dc),
        "scene_feature_rest_sha256": _tensor_sha256(scene_feature_rest),
        "scene_render_sha256": scene_render_sha256,
        "forward_scene_parameters": forward_scene_parameters,
        "forward_scene_render_outputs": forward_scene_render_outputs,
        "source_patch_provenance": source_patch_provenance,
        "gaussian_repo": gaussian_repo.as_posix(),
        "rasterizer_extension_relative_origin": rasterizer_relative_origin,
        "rasterizer_extension_sha256": rasterizer_extension_sha256,
        "source_scale_gradients": source_reports,
        "forward_interpretation": forward_interpretation,
        "source_interpretation": interpretation,
        "combined_interpretation": combined_interpretation,
        "combined_backward_error": combined_error,
        "combined_scale_gradient": total_report,
        "combined_physical_scale_input_gradient": total_physical_scale_report,
        "nonfinite_optimizer_groups": nonfinite_groups,
        "optimizer_step_executed": False,
        "checkpoint_written": False,
        "production_activation": False,
    }
    encoded = json.dumps(result, sort_keys=True, allow_nan=False)
    if args.report_json:
        report_path = Path(args.report_json).expanduser().resolve()
        if report_path.is_symlink():
            raise SceneScaleDiagnosticError(
                f"diagnostic report path may not be a symlink: {report_path}"
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = report_path.with_name(report_path.name + ".bodyrig-tmp")
        if temp_path.is_symlink():
            raise SceneScaleDiagnosticError(
                f"diagnostic report temp path may not be a symlink: {temp_path}"
            )
        if temp_path.exists():
            if not temp_path.is_file():
                raise SceneScaleDiagnosticError(
                    f"diagnostic report temp path is not a regular file: {temp_path}"
                )
            temp_path.unlink()
        temp_path.write_text(encoded + "\n", encoding="utf-8")
        temp_path.replace(report_path)
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
