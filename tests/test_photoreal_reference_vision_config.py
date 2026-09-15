from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_reference_vision_config import (
    PhotorealReferenceVisionConfigError,
    build_reference_configs,
    write_reference_configs,
)


def _model_root(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    root.mkdir()
    (root / "bodyrig-reference-vision-v1.json").write_text("{}\n", encoding="utf-8")
    (root / "weights.bin").write_bytes(b"weights")
    return root


def test_reference_configs_bind_same_adapter_revision_and_model_set(tmp_path: Path) -> None:
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


def test_reference_config_revision_changes_when_adapter_bytes_change(tmp_path: Path) -> None:
    model_root = _model_root(tmp_path)
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
    model_root = _model_root(tmp_path)
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
