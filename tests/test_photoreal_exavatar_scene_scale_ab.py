from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_exavatar_scene_scale_ab.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_scene_scale_ab",
        TOOL,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scene_scale_ab_only_runs_patch_when_rasterizer_is_implicated() -> None:
    tool = _load_tool()

    assert tool._rasterizer_implicated(
        {
            "source_interpretation": {
                "rgb_scene": "physical-scale-rasterizer-backward-nonfinite",
                "ssim_scene": "finite",
            },
            "combined_interpretation": "finite",
        }
    )
    assert tool._rasterizer_implicated(
        {
            "source_interpretation": {
                "rgb_scene": "finite",
                "ssim_scene": "finite",
            },
            "combined_interpretation": "broad-rasterizer-backward-nonfinite",
        }
    )
    assert not tool._rasterizer_implicated(
        {
            "source_interpretation": {
                "rgb_scene": "log-scale-chain-nonfinite",
                "ssim_scene": "finite",
            },
            "combined_interpretation": "log-scale-chain-nonfinite",
        }
    )


def test_scene_scale_ab_summarizes_elimination_and_reduction() -> None:
    tool = _load_tool()
    baseline = {
        "combined_interpretation": "physical-scale-rasterizer-backward-nonfinite",
        "combined_physical_scale_input_gradient": {
            "bad_row_count": 20,
        },
    }

    eliminated = {
        "combined_interpretation": "finite",
        "source_interpretation": {
            "rgb_scene": "finite",
            "ssim_scene": "finite",
        },
        "combined_physical_scale_input_gradient": {
            "bad_row_count": 0,
        },
    }
    reduced = {
        "combined_interpretation": "physical-scale-rasterizer-backward-nonfinite",
        "source_interpretation": {
            "rgb_scene": "physical-scale-rasterizer-backward-nonfinite",
            "ssim_scene": "finite",
        },
        "combined_physical_scale_input_gradient": {
            "bad_row_count": 5,
        },
    }

    assert (
        tool._summarize_change(baseline, eliminated)
        == "candidate-fix-eliminated-observed-rasterizer-nonfinite"
    )
    assert (
        tool._summarize_change(baseline, reduced)
        == "candidate-fix-reduced-observed-rasterizer-nonfinite"
    )


def test_scene_scale_ab_tool_and_operator_are_nonproduction() -> None:
    source = TOOL.read_text(encoding="utf-8")
    wrapper = (
        ROOT / "run-photoreal-exavatar-scene-scale-ab.ps1"
    ).read_text(encoding="utf-8")

    compile(source, "<scene-scale-ab>", "exec")
    assert '"production_activation": False' in source
    assert "optimizer.step()" not in source
    assert wrapper.count("& wsl.exe") == 1
    assert "diag/exavatar-final-symlink-containment-runner" in wrapper
    assert "status --porcelain" in wrapper
    assert "fetch --prune origin" in wrapper
    assert "refs/remotes/origin/$diagnosticBranch^{commit}" in wrapper
    assert "git reset --hard origin/$diagnosticBranch" in wrapper
    assert "merge-base --is-ancestor" in wrapper
    assert "Baseline iterations: 1" in wrapper
    assert "Patched iterations: 0 or 1" in wrapper
    assert "Optimizer step: FALSE" in wrapper
    assert "Checkpoint write: FALSE" in wrapper
    assert "Original rasterizer mutation: FALSE" in wrapper
    assert "CUDA_LAUNCH_BLOCKING=1" in wrapper
    assert "Production: FALSE" in wrapper

def test_scene_scale_ab_requires_forward_identical_reports() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1, "ssim_scene": 0.2},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    same = dict(base)
    same["background_point_cloud"] = {"sha256": "a" * 64}
    same["rasterizer_extension_sha256"] = "b" * 64
    same["rasterizer_backward_sha256"] = "f" * 64

    tool._require_comparable_reports(base, same)

    changed = dict(same)
    changed["loss_values"] = {"rgb_scene": 0.1001, "ssim_scene": 0.2}
    with pytest.raises(
        tool.SceneScaleABError,
        match="loss_values",
    ):
        tool._require_comparable_reports(base, changed)


def test_scene_scale_ab_rejects_scene_identity_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    changed = dict(base)
    changed["scene_point_count"] = 99
    changed["background_point_cloud"] = {"sha256": "b" * 64}
    changed["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="scene_point_count,background_point_cloud.sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_rejects_identical_extension_digest() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "c" * 64,
        "rasterizer_backward_sha256": "d" * 64,
    }
    patched = dict(base)
    patched["rasterizer_backward_sha256"] = "e" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="extension digests are identical",
    ):
        tool._require_comparable_reports(base, patched)

def test_scene_scale_ab_rejects_first_batch_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    changed = dict(base)
    changed["batch_frame_idx"] = [18]
    changed["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="batch_frame_idx",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_rejects_missing_report_identity() -> None:
    import pytest

    tool = _load_tool()
    incomplete = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    patched = dict(incomplete)
    patched["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="batch_frame_idx is invalid",
    ):
        tool._require_comparable_reports(incomplete, patched)

def test_scene_scale_ab_gradient_matrix_is_compact_and_loss_scoped() -> None:
    tool = _load_tool()
    report = {
        "source_scale_gradients": {
            "rgb_scene": {
                "render_scene_output": {
                    "used": True,
                    "all_finite": True,
                    "nonfinite_value_count": 0,
                },
                "scale_scene": {
                    "used": True,
                    "all_finite": False,
                    "bad_row_count": 3,
                },
                "physical_scale_input": {
                    "used": True,
                    "all_finite": False,
                    "bad_row_count": 3,
                },
            },
            "ssim_scene": {
                "backward_error": "synthetic",
            },
        }
    }

    matrix = tool._source_gradient_matrix(report)

    assert matrix["rgb_scene"]["scale_scene"]["bad_row_count"] == 3
    assert (
        matrix["rgb_scene"]["render_scene_output"]["nonfinite_value_count"]
        == 0
    )
    assert matrix["ssim_scene"]["backward_error"] == "synthetic"


def test_scene_scale_ab_source_mentions_patch_receipt_in_summary_path() -> None:
    source = TOOL.read_text(encoding="utf-8")

    assert "bodyrig-rasterizer-ab-receipt.json" in source
    assert '"baseline_gradient_matrix"' in source
    assert '"patched_gradient_matrix"' in source
    assert '"upstream_reference"' in source
    assert '"build_environment"' in source
    assert "lost candidate-only status" in source
    assert "incorrectly claims maintainer confirmation" in source
    assert "lacks build environment provenance" in source
    assert "crossed production authority" in source

def test_scene_scale_ab_rejects_initialized_scene_tensor_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    changed = dict(base)
    changed["scene_log_scale_sha256"] = "3" * 64
    changed["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="scene_log_scale_sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_extracts_finite_gradient_magnitude() -> None:
    tool = _load_tool()

    report = {
        "combined_scale_gradient": {
            "finite_abs_max": 123.5,
        }
    }
    assert (
        tool._finite_abs_max(report, "combined_scale_gradient")
        == 123.5
    )
    assert tool._finite_abs_max(report, "missing") is None

def test_scene_scale_ab_rejects_exavatar_source_hash_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    changed = dict(base)
    changed["source_patch_provenance"] = {
        "loss_sha256": "f" * 64,
        "custom_sha256": "e" * 64,
    }
    changed["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="source_patch_provenance.loss_sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_rejects_forward_render_identity_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [{"all_finite": True, "sha256": "3" * 64}],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }
    changed = dict(base)
    changed["scene_render_sha256"] = ["4" * 64]
    changed["forward_scene_render_outputs"] = [
        {"all_finite": True, "sha256": "4" * 64}
    ]
    changed["rasterizer_extension_sha256"] = "b" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="scene_render_sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_rejects_inconsistent_forward_render_hash_fields() -> None:
    import pytest

    tool = _load_tool()
    report = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_render_sha256": ["3" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [
            {"all_finite": True, "sha256": "4" * 64}
        ],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "a" * 64,
        "rasterizer_backward_sha256": "c" * 64,
    }

    with pytest.raises(
        tool.SceneScaleABError,
        match="forward render SHA fields disagree",
    ):
        tool._require_report_identity(report, label="synthetic")

def test_scene_scale_ab_does_not_implicate_rasterizer_when_forward_is_nonfinite() -> None:
    tool = _load_tool()

    report = {
        "forward_interpretation": "forward-render-nonfinite",
        "source_interpretation": {
            "rgb_scene": "physical-scale-rasterizer-backward-nonfinite",
        },
        "combined_interpretation": "physical-scale-rasterizer-backward-nonfinite",
    }

    assert not tool._rasterizer_implicated(report)

def test_scene_scale_ab_rejects_batch_input_hash_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_rotation_sha256": "3" * 64,
        "scene_opacity_sha256": "4" * 64,
        "scene_feature_dc_sha256": "5" * 64,
        "scene_feature_rest_sha256": "6" * 64,
        "scene_render_sha256": ["7" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [
            {"all_finite": True, "sha256": "7" * 64}
        ],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "b" * 64,
        "rasterizer_backward_sha256": "d" * 64,
    }
    changed = dict(base)
    changed["batch_input_sha256"] = "f" * 64
    changed["rasterizer_extension_sha256"] = "c" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="batch_input_sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_rejects_missing_full_state_hash() -> None:
    import pytest

    tool = _load_tool()
    report = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "0" * 64,
        "scene_mean_sha256": "1" * 64,
        "scene_log_scale_sha256": "2" * 64,
        "scene_rotation_sha256": "3" * 64,
        "scene_opacity_sha256": "4" * 64,
        "scene_feature_dc_sha256": "5" * 64,
        "scene_render_sha256": ["6" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "forward_scene_render_outputs": [
            {"all_finite": True, "sha256": "6" * 64}
        ],
        "background_point_cloud": {"sha256": "a" * 64},
        "source_patch_provenance": {
            "loss_sha256": "d" * 64,
            "custom_sha256": "e" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "b" * 64,
        "rasterizer_backward_sha256": "d" * 64,
    }

    with pytest.raises(
        tool.SceneScaleABError,
        match="scene_feature_rest_sha256",
    ):
        tool._require_report_identity(report, label="synthetic")

def test_scene_scale_ab_clears_only_known_previous_result_files(tmp_path: Path) -> None:
    tool = _load_tool()
    result_dir = tmp_path / "scene-scale-ab"
    result_dir.mkdir()
    known = (
        "baseline.json",
        "conic-offdiag-fix.json",
        "comparison.json",
        "baseline.log",
        "conic-offdiag-fix.log",
        "prepare-conic-offdiag-fix.log",
    )
    for name in known:
        (result_dir / name).write_text("old\n", encoding="utf-8")
    keep = result_dir / "operator-note.txt"
    keep.write_text("keep\n", encoding="utf-8")

    tool._clear_previous_result_files(result_dir)

    assert all(not (result_dir / name).exists() for name in known)
    assert keep.read_text(encoding="utf-8") == "keep\n"


def test_scene_scale_ab_refuses_symlinked_previous_result(tmp_path: Path) -> None:
    import os
    import pytest

    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")

    tool = _load_tool()
    result_dir = tmp_path / "scene-scale-ab"
    result_dir.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    link = result_dir / "comparison.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(
        tool.SceneScaleABError,
        match="may not be a symlink",
    ):
        tool._clear_previous_result_files(result_dir)

    assert target.read_text(encoding="utf-8") == "{}\n"

def test_scene_scale_ab_next_action_is_conservative_and_total() -> None:
    import pytest

    tool = _load_tool()
    expected = {
        "baseline-forward-nonfinite":
            "inspect-forward-scene-parameters-and-render-before-backward",
        "baseline-did-not-implicate-rasterizer":
            "inspect-log-scale-chain-or-other-scene-gradient-source",
        "candidate-fix-eliminated-observed-rasterizer-nonfinite":
            "run-controlled-teacher-itr0-with-candidate-before-any-broader-validation",
        "candidate-fix-reduced-observed-rasterizer-nonfinite":
            "candidate-insufficient-inspect-residual-bad-gaussians",
        "candidate-fix-did-not-change-observed-rasterizer-nonfinite-count":
            "reject-candidate-and-continue-rasterizer-backward-diagnosis",
        "candidate-fix-changed-observation-without-eliminating-nonfinite":
            "candidate-inconclusive-inspect-gradient-matrix-and-residuals",
    }

    for outcome, action in expected.items():
        assert tool._next_action_for_outcome(outcome) == action
        lowered = action.lower()
        assert "production" not in lowered
        assert "merge" not in lowered
        assert "ship" not in lowered

    with pytest.raises(
        tool.SceneScaleABError,
        match="unsupported scene-scale A/B outcome",
    ):
        tool._next_action_for_outcome("unknown")

def test_scene_scale_ab_compares_scene_distribution() -> None:
    source = TOOL.read_text(encoding="utf-8")

    assert '"scene_distribution",' in source
    assert '"baseline_scene_distribution": baseline.get("scene_distribution")' in source
    assert '"patched_scene_distribution": patched.get("scene_distribution")' in source

def test_scene_scale_ab_rejects_runtime_preflight_drift() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "c" * 64,
        "scene_point_count": 100,
        "background_point_cloud": {"sha256": "a" * 64},
        "batch_input_sha256": "1" * 64,
        "scene_mean_sha256": "2" * 64,
        "scene_log_scale_sha256": "3" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_render_sha256": ["8" * 64],
        "forward_scene_parameters": {
            "mean_scene": {"all_finite": True},
            "log_scale_scene": {"all_finite": True},
            "physical_scale_input": {"all_finite": True},
            "rotation_scene": {"all_finite": True},
            "opacity_scene": {"all_finite": True},
        },
        "scene_distribution": {},
        "forward_scene_render_outputs": [
            {"all_finite": True, "sha256": "8" * 64}
        ],
        "source_patch_provenance": {
            "loss_sha256": "9" * 64,
            "custom_sha256": "a" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "b" * 64,
        "rasterizer_backward_sha256": "d" * 64,
    }
    changed = dict(base)
    changed["runtime_preflight_sha256"] = "d" * 64
    changed["rasterizer_extension_sha256"] = "e" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="runtime_preflight_sha256",
    ):
        tool._require_comparable_reports(base, changed)

def test_scene_scale_ab_compacts_combined_gradient_matrix() -> None:
    tool = _load_tool()
    report = {
        "combined_scene_gradients": {
            "mean_scene": {
                "used": True,
                "all_finite": True,
                "bad_row_count": 0,
                "finite_abs_max": 3.0,
            },
            "scale_scene": {
                "used": True,
                "all_finite": False,
                "bad_row_count": 2,
                "finite_abs_max": 9.0,
            },
        }
    }

    matrix = tool._combined_gradient_matrix(report)

    assert matrix["mean_scene"]["all_finite"] is True
    assert matrix["scale_scene"]["bad_row_count"] == 2
    assert matrix["physical_scale_input"] is None


def test_scene_scale_ab_summary_source_contains_baseline_diagnostics_before_ab() -> None:
    source = TOOL.read_text(encoding="utf-8")

    summary_index = source.index('"baseline_scene_distribution"')
    early_return_index = source.index("if not implicated:")
    assert '"baseline_gradient_matrix"' in source[summary_index:early_return_index]
    assert '"baseline_combined_gradient_matrix"' in source[
        summary_index:early_return_index
    ]
    assert '"baseline_nonfinite_optimizer_groups"' in source[
        summary_index:early_return_index
    ]

def test_scene_scale_ab_rejects_identical_backward_source_digest() -> None:
    import pytest

    tool = _load_tool()
    base = {
        "format": "bodyrig-exavatar-scene-scale-diagnostic",
        "version": 1,
        "subject_id": "bodyrig-42",
        "seed": 0,
        "cur_itr": 0,
        "batch_frame_idx": [17],
        "camera_mode": "virtual",
        "runtime_preflight_sha256": "e" * 64,
        "scene_point_count": 100,
        "batch_input_sha256": "1" * 64,
        "scene_mean_sha256": "2" * 64,
        "scene_log_scale_sha256": "3" * 64,
        "scene_rotation_sha256": "4" * 64,
        "scene_opacity_sha256": "5" * 64,
        "scene_feature_dc_sha256": "6" * 64,
        "scene_feature_rest_sha256": "7" * 64,
        "scene_render_sha256": ["8" * 64],
        "background_point_cloud": {"sha256": "9" * 64},
        "forward_scene_parameters": {
            key: {"all_finite": True}
            for key in (
                "mean_scene",
                "log_scale_scene",
                "physical_scale_input",
                "rotation_scene",
                "opacity_scene",
            )
        },
        "scene_distribution": {},
        "forward_scene_render_outputs": [
            {"all_finite": True, "sha256": "8" * 64}
        ],
        "source_patch_provenance": {
            "loss_sha256": "a" * 64,
            "custom_sha256": "b" * 64,
        },
        "loss_values": {"rgb_scene": 0.1},
        "nonfinite_loss": [],
        "rasterizer_extension_sha256": "c" * 64,
        "rasterizer_backward_sha256": "d" * 64,
    }
    patched = dict(base)
    patched["rasterizer_extension_sha256"] = "f" * 64

    with pytest.raises(
        tool.SceneScaleABError,
        match="backward source digests are identical",
    ):
        tool._require_comparable_reports(base, patched)

