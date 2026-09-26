from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scene_scale_diagnostic_is_one_iteration_read_only() -> None:
    tool = (ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py").read_text(
        encoding="utf-8"
    )

    compile(tool, "<scene-scale-diagnostic>", "exec")
    assert 'for name in ("rgb_scene", "ssim_scene")' in tool
    assert '"mean_scene"' in tool
    assert '"scale_scene"' in tool
    assert '"rotation_scene"' in tool
    assert '"opacity_scene"' in tool
    assert '"physical_scale_input"' in tool
    assert '"render_scene_output"' in tool
    assert '"render_scene_outputs"' in tool
    assert "GaussianRenderer.forward = bodyrig_renderer_forward" in tool
    assert "render_img.retain_grad()" in tool
    assert "loss-to-render-gradient-nonfinite" in tool
    assert "physical_scale.retain_grad()" in tool
    assert "_bodyrig_diagnostic_physical_scale" in tool
    assert '"combined_physical_scale_input_gradient"' in tool
    assert '"finite_abs_max"' in tool
    assert '"rasterizer_extension_relative_origin"' in tool
    assert '"rasterizer_extension_sha256"' in tool
    assert "imported outside requested repo" in tool
    assert "physical_scale_input.grad = None" in tool
    assert "torch.autograd.grad" in tool
    assert "sum(loss.values()).backward()" in tool
    assert '"optimizer_step_executed": False' in tool
    assert '"checkpoint_written": False' in tool
    assert "optimizer.step()" not in tool
    assert "save_model(" not in tool
    assert "densify_and_prune(" not in tool
    assert "adjust_gaussians(" not in tool
    assert "manual_seed(seed)" in tool
    assert "torch.cuda.manual_seed_all(seed)" in tool


def test_scene_scale_diagnostic_operator_is_single_launcher() -> None:
    wrapper = (
        ROOT / "run-photoreal-exavatar-scene-scale-diagnostic.ps1"
    ).read_text(encoding="utf-8")

    assert wrapper.count("& wsl.exe") == 1
    assert "diag/exavatar-final-symlink-containment-runner" in wrapper
    assert "status --porcelain" in wrapper
    assert "refs/remotes/origin/$diagnosticBranch^{commit}" in wrapper
    assert "merge-base --is-ancestor" in wrapper
    assert wrapper.count("photoreal_exavatar_scene_scale_diagnostic.py") == 1
    assert "Optimizer step: FALSE" in wrapper
    assert "Checkpoint write: FALSE" in wrapper
    assert "CUDA_LAUNCH_BLOCKING=1" in wrapper
    assert "Production: FALSE" in wrapper

def test_scene_scale_diagnostic_json_helpers_preserve_nonfinite_markers() -> None:
    import importlib.util
    import sys

    path = ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_scene_scale_diagnostic",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module._json_scalar(float("nan")) == "nan"
    assert module._json_scalar(float("inf")) == "inf"
    assert module._json_scalar(float("-inf")) == "-inf"
    assert module._json_nested([[1.0, float("inf")]]) == [[1.0, "inf"]]

def test_scene_scale_diagnostic_classifies_failure_layer() -> None:
    import importlib.util
    import sys

    path = ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_scene_scale_classification",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    finite = {"used": True, "all_finite": True}
    bad = {"used": True, "all_finite": False}

    assert module._classify_source_report(
        {
            "mean_scene": finite,
            "scale_scene": bad,
            "rotation_scene": finite,
            "opacity_scene": finite,
            "physical_scale_input": finite,
        }
    ) == "log-scale-chain-nonfinite"

    assert module._classify_source_report(
        {
            "render_scene_output": finite,
            "mean_scene": finite,
            "scale_scene": bad,
            "rotation_scene": finite,
            "opacity_scene": finite,
            "physical_scale_input": bad,
        }
    ) == "physical-scale-rasterizer-backward-nonfinite"

    assert module._classify_source_report(
        {
            "render_scene_output": bad,
            "mean_scene": finite,
            "scale_scene": bad,
            "rotation_scene": finite,
            "opacity_scene": finite,
            "physical_scale_input": bad,
        }
    ) == "loss-to-render-gradient-nonfinite"

    assert module._classify_source_report(
        {
            "mean_scene": bad,
            "scale_scene": bad,
            "rotation_scene": finite,
            "opacity_scene": finite,
            "physical_scale_input": bad,
        }
    ) == "broad-rasterizer-backward-nonfinite"

def test_scene_scale_diagnostic_uses_preprocess_camera_authority() -> None:
    tool = (
        ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    ).read_text(encoding="utf-8")

    assert "adapter._validate_preprocess(root, receipt)" in tool
    assert 'camera_mode = str(preprocess_state["camera_mode"])' in tool
    assert "adapter._validate_background_point_cloud(" in tool
    assert "camera_mode=camera_mode" in tool
    assert '"camera_mode": camera_mode' in tool


def test_scene_scale_diagnostic_supports_atomic_report_output() -> None:
    tool = (
        ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    ).read_text(encoding="utf-8")

    assert '"--report-json"' in tool
    assert 'report_path.with_name(report_path.name + ".bodyrig-tmp")' in tool
    assert "temp_path.replace(report_path)" in tool
    assert "allow_nan=False" in tool

def test_scene_scale_diagnostic_combined_backward_error_precedes_scale_classification() -> None:
    source = (
        ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    ).read_text(encoding="utf-8")

    assert '"combined-backward-error"' in source
    assert "if combined_error is not None" in source

def test_scene_scale_diagnostic_reports_forward_scene_health() -> None:
    tool = (
        ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
    ).read_text(encoding="utf-8")

    assert "def _tensor_value_report" in tool
    assert '"scene_render_sha256"' in tool
    assert '"forward_scene_parameters"' in tool
    assert '"forward_scene_render_outputs"' in tool
    assert '"mean_scene": _tensor_value_report(scene_mean_param)' in tool
    assert '"physical_scale_input": _tensor_value_report(physical_scale_input)' in tool
    assert '"sha256": _tensor_sha256(render_img)' in tool

def test_scene_scale_diagnostic_stable_value_hash_tracks_nested_tensor_state() -> None:
    import importlib.util
    import sys
    import types

    class FakeArray:
        def __init__(self, payload: bytes, shape: tuple[int, ...]) -> None:
            self._payload = payload
            self.dtype = "float32"
            self.shape = shape

        def tobytes(self, order: str = "C") -> bytes:
            assert order == "C"
            return self._payload

    class FakeTensor:
        def __init__(self, payload: bytes, shape: tuple[int, ...]) -> None:
            self._array = FakeArray(payload, shape)

        def detach(self):
            return self

        def cpu(self):
            return self

        def contiguous(self):
            return self

        def numpy(self):
            return self._array

    fake_torch = types.SimpleNamespace(
        is_tensor=lambda value: isinstance(value, FakeTensor),
    )
    previous_torch = sys.modules.get("torch")
    sys.modules["torch"] = fake_torch
    try:
        path = ROOT / "tools" / "photoreal_exavatar_scene_scale_diagnostic.py"
        spec = importlib.util.spec_from_file_location(
            "bodyrig_test_scene_scale_hash",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        first = {
            "img": FakeTensor(b"img-1-2", (1, 2)),
            "cam_param": {
                "R": FakeTensor(b"identity-2", (2, 2)),
                "tag": "virtual",
            },
        }
        second = {
            "cam_param": {
                "tag": "virtual",
                "R": FakeTensor(b"identity-2", (2, 2)),
            },
            "img": FakeTensor(b"img-1-2", (1, 2)),
        }
        changed = {
            "img": FakeTensor(b"img-1-3", (1, 2)),
            "cam_param": {
                "R": FakeTensor(b"identity-2", (2, 2)),
                "tag": "virtual",
            },
        }

        assert module._stable_value_sha256(first) == module._stable_value_sha256(second)
        assert module._stable_value_sha256(first) != module._stable_value_sha256(changed)
    finally:
        if previous_torch is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = previous_torch

