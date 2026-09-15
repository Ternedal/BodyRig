from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.photoreal_exavatar_teacher_config import (
    PhotorealExAvatarTeacherConfigError,
    build_exavatar_teacher_config,
)
from bodyrig.photoreal_exavatar_teacher_wsl_bridge import build_teacher_transport_revision


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    python = tmp_path / "python.exe"
    bridge = tmp_path / "bridge.py"
    adapter = tmp_path / "adapter.py"
    python.write_bytes(b"python")
    bridge.write_bytes(b"bridge-v1")
    adapter.write_bytes(b"adapter-v1")
    return python, bridge, adapter


def test_transport_revision_changes_when_bridge_or_adapter_bytes_change(tmp_path: Path) -> None:
    _python, bridge, adapter = _files(tmp_path)
    first = build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)

    bridge.write_bytes(b"bridge-v2")
    second = build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)
    assert second != first

    bridge.write_bytes(b"bridge-v1")
    adapter.write_bytes(b"adapter-v2")
    third = build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)
    assert third != first
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_teacher_config_is_exact_wsl_transport_and_pinned_upstream(tmp_path: Path) -> None:
    python, bridge, adapter = _files(tmp_path)
    result = build_exavatar_teacher_config(
        windows_python=python,
        bridge_path=bridge,
        adapter_path=adapter,
        linux_workspace_root="/opt/bodyrig-exavatar/workspaces/performer-42",
        linux_runtime_preflight="/opt/bodyrig-exavatar/workspaces/performer-42/runtime-preflight.json",
        linux_python="/opt/bodyrig-exavatar/bin/python",
        distribution="Ubuntu-22.04",
        wsl_exe="wsl.exe",
    )

    assert result["format"] == "bodyrig-photoreal-teacher-config"
    assert result["version"] == 1
    assert result["adapter"] == "exavatar-benchmark"
    assert result["upstream_repository"] == "https://github.com/mks0601/ExAvatar_RELEASE"
    assert result["upstream_commit"] == "d45268730c779fae4118f1a361cf9ff639bc4d1e"
    assert result["revision"] == build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)
    command = result["command"]
    assert command[0] == str(python.resolve())
    assert command[1] == str(bridge.resolve())
    assert "--workspace-root" in command
    assert "/opt/bodyrig-exavatar/workspaces/performer-42" in command
    assert "--runtime-preflight" in command
    assert str(adapter.resolve()) in command
    assert "held-out" not in " ".join(command).lower()


def test_teacher_config_rejects_relative_linux_paths(tmp_path: Path) -> None:
    python, bridge, adapter = _files(tmp_path)
    with pytest.raises(PhotorealExAvatarTeacherConfigError, match="absolute Linux path"):
        build_exavatar_teacher_config(
            windows_python=python,
            bridge_path=bridge,
            adapter_path=adapter,
            linux_workspace_root="relative/workspace",
            linux_runtime_preflight="/tmp/runtime.json",
        )


def test_teacher_config_rejects_timeout_above_generic_runner_limit(tmp_path: Path) -> None:
    python, bridge, adapter = _files(tmp_path)
    with pytest.raises(PhotorealExAvatarTeacherConfigError, match="1..604800"):
        build_exavatar_teacher_config(
            windows_python=python,
            bridge_path=bridge,
            adapter_path=adapter,
            linux_workspace_root="/tmp/workspace",
            linux_runtime_preflight="/tmp/workspace/runtime.json",
            timeout_seconds=604801,
        )
