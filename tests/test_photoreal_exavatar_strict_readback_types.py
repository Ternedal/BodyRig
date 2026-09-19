from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_materializer as materializer
from bodyrig import photoreal_exavatar_preflight_strict as preflight
from bodyrig import photoreal_exavatar_runtime_preflight_strict as runtime_preflight
from bodyrig import photoreal_exavatar_teacher_config as teacher_config
from bodyrig import photoreal_exavatar_workspace_wsl as workspace_wsl
from bodyrig import photoreal_teacher_benchmark_authority as benchmark_authority


@pytest.mark.parametrize(
    "module",
    [preflight, runtime_preflight, teacher_config, benchmark_authority],
)
def test_strict_persisted_json_comparison_rejects_bool_numeric_alias(module: object) -> None:
    compare = getattr(module, "_strict_json_equal")
    assert compare({"version": 1}, {"version": 1})
    assert not compare({"version": True}, {"version": 1})
    assert not compare({"version": 1}, {"version": 1.0})


def test_workspace_and_materializer_version_helpers_reject_boolean_v1() -> None:
    assert workspace_wsl._is_v1(1)
    assert workspace_wsl._is_v1(1.0)
    assert not workspace_wsl._is_v1(True)
    assert materializer._is_version(1, 1)
    assert materializer._is_version(1.0, 1)
    assert not materializer._is_version(True, 1)


def test_preflight_readback_rejects_boolean_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = {"format": "strict-preflight", "version": 1}
    monkeypatch.setattr(preflight, "build_exavatar_preflight_strict", lambda **_kwargs: expected)
    receipt = tmp_path / "preflight.json"
    receipt.write_text(json.dumps({"format": "strict-preflight", "version": True}), encoding="utf-8")

    with pytest.raises(preflight.PhotorealExAvatarPreflightError, match="does not match"):
        preflight.validate_exavatar_preflight_strict_file(
            receipt,
            dependency_root=tmp_path,
            asset_root=tmp_path,
            reference_model_root=tmp_path,
            smplx_gender="neutral",
        )


def test_runtime_readback_rejects_boolean_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = {"format": "runtime-preflight", "version": 1}
    monkeypatch.setattr(runtime_preflight, "build_runtime_preflight_strict", lambda **_kwargs: expected)
    receipt = tmp_path / "runtime.json"
    receipt.write_text(json.dumps({"format": "runtime-preflight", "version": True}), encoding="utf-8")

    with pytest.raises(runtime_preflight.PhotorealExAvatarRuntimePreflightStrictError, match="does not match"):
        runtime_preflight.validate_runtime_preflight_strict_file(
            workspace_root=tmp_path,
            output_path=receipt,
        )


def test_teacher_config_readback_rejects_boolean_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = {"format": "teacher-config", "version": 1}
    monkeypatch.setattr(teacher_config, "build_exavatar_teacher_config", lambda **_kwargs: expected)
    receipt = tmp_path / "teacher-config.json"
    receipt.write_text(json.dumps({"format": "teacher-config", "version": True}), encoding="utf-8")

    with pytest.raises(teacher_config.PhotorealExAvatarTeacherConfigError, match="does not match"):
        teacher_config.validate_exavatar_teacher_config_file(
            config_path=receipt,
            windows_python=tmp_path / "python.exe",
            bridge_path=tmp_path / "bridge.py",
            adapter_path=tmp_path / "adapter.py",
            linux_workspace_root="/tmp/workspace",
            linux_runtime_preflight="/tmp/runtime.json",
        )


def test_benchmark_plan_readback_rejects_boolean_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    teacher = tmp_path / "teacher.json"
    teacher.write_text("{}\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"format": "benchmark-plan", "version": True}), encoding="utf-8")
    expected = {"format": "benchmark-plan", "version": 1}
    monkeypatch.setattr(benchmark_authority, "validate_teacher_input_document", lambda _value: {})
    monkeypatch.setattr(benchmark_authority, "build_teacher_benchmark_plan", lambda _value: expected)

    with pytest.raises(benchmark_authority.PhotorealTeacherBenchmarkPlanError, match="does not match"):
        benchmark_authority.validate_teacher_benchmark_plan_files_strict(teacher, plan)
