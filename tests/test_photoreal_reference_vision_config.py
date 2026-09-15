from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_reference_vision_config import (
    PhotorealReferenceVisionConfigError,
    build_reference_configs,
    write_reference_configs,
)

MMPOSE_REVISION = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"
MMDET_REVISION = "fe3f809a0a514189baf889aa358c498d51ee36cd"


def _model_root(
    tmp_path: Path,
    *,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    (root / "bodyrig-reference-vision-v1.json").write_text("{}\n", encoding="utf-8")
    (root / "weights.bin").write_bytes(b"weights")
    (root / "runtime-environment.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-reference-runtime-environment",
                "version": 1,
                "distribution": distribution,
                "linux_python": linux_python,
                "mmpose_revision": MMPOSE_REVISION,
                "mmdetection_revision": MMDET_REVISION,
                "observed": {
                    "torch_cuda_available": True,
                    "onnxruntime_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
                },
                "build_only": True,
                "production_activation": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def test_reference_configs_bind_same_adapter_revision_model_set_and_runtime(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path)
    adapter = tmp_path / "adapter.py"
    adapter.write_text("print('adapter')\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")

    identity, frame = build_reference_configs(
        model_root=model_root,
        adapter_path=adapter,
        windows_python=python,
        distribution="Ubuntu-22.04",
        linux_python="/opt/bodyrig-photoreal/bin/python",
    )

    assert identity["format"] == "bodyrig-photoreal-identity-extractor-config"
    assert frame["format"] == "bodyrig-photoreal-frame-analyzer-config"
    assert identity["adapter"] == frame["adapter"] == "bodyrig-reference-vision-v1"
    assert identity["revision"] == frame["revision"]
    assert len(identity["revision"]) == 64
    assert identity["model_set_sha256"] == frame["model_set_sha256"]
    assert identity["command"] == frame["command"]
    assert "bodyrig.photoreal_wsl_request_bridge" in identity["command"]
    assert identity["timeout_seconds"] == 86400


def test_reference_config_rejects_missing_runtime_receipt(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "weights.bin").write_bytes(b"weights")
    adapter = tmp_path / "adapter.py"
    adapter.write_text("adapter\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")

    with pytest.raises(PhotorealReferenceVisionConfigError, match="runtime-environment.json is missing"):
        build_reference_configs(
            model_root=model_root,
            adapter_path=adapter,
            windows_python=python,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
        )


def test_reference_config_rejects_runtime_distribution_or_python_drift(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path)
    adapter = tmp_path / "adapter.py"
    adapter.write_text("adapter\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")

    with pytest.raises(PhotorealReferenceVisionConfigError, match="distribution differs"):
        build_reference_configs(
            model_root=model_root,
            adapter_path=adapter,
            windows_python=python,
            distribution="Other-Distro",
            linux_python="/opt/bodyrig-photoreal/bin/python",
        )
    with pytest.raises(PhotorealReferenceVisionConfigError, match="Linux Python differs"):
        build_reference_configs(
            model_root=model_root,
            adapter_path=adapter,
            windows_python=python,
            distribution="Ubuntu-22.04",
            linux_python="/other/bin/python",
        )


def test_reference_config_revision_changes_when_adapter_bytes_change(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path, distribution="Ubuntu", linux_python="/vision/bin/python")
    adapter = tmp_path / "adapter.py"
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")
    adapter.write_text("one\n", encoding="utf-8")
    first, _ = build_reference_configs(
        model_root=model_root,
        adapter_path=adapter,
        windows_python=python,
        distribution="Ubuntu",
        linux_python="/vision/bin/python",
    )
    adapter.write_text("two\n", encoding="utf-8")
    second, _ = build_reference_configs(
        model_root=model_root,
        adapter_path=adapter,
        windows_python=python,
        distribution="Ubuntu",
        linux_python="/vision/bin/python",
    )
    assert first["revision"] != second["revision"]


def test_write_reference_configs_is_create_only(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path, distribution="Ubuntu", linux_python="/vision/bin/python")
    adapter = tmp_path / "adapter.py"
    adapter.write_text("adapter\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")
    identity_out = tmp_path / "identity.json"
    frame_out = tmp_path / "frame.json"

    write_reference_configs(
        model_root=model_root,
        adapter_path=adapter,
        windows_python=python,
        distribution="Ubuntu",
        linux_python="/vision/bin/python",
        identity_output=identity_out,
        frame_output=frame_out,
    )
    identity = json.loads(identity_out.read_text(encoding="utf-8"))
    frame = json.loads(frame_out.read_text(encoding="utf-8"))
    assert identity["model_set_sha256"] == frame["model_set_sha256"]

    with pytest.raises(PhotorealReferenceVisionConfigError, match="already exists"):
        write_reference_configs(
            model_root=model_root,
            adapter_path=adapter,
            windows_python=python,
            distribution="Ubuntu",
            linux_python="/vision/bin/python",
            identity_output=identity_out,
            frame_output=frame_out,
        )
