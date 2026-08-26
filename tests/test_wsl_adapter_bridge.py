from __future__ import annotations

import pytest

from bodyrig.wsl_adapter_bridge import (
    WslBridgeError,
    build_wsl_invocation,
    expand_subst_path,
    translate_bodyrig_paths,
    validate_linux_command,
)


def _convert(value: str) -> str:
    mapping = {
        r"C:\temp\request.json": "/mnt/c/temp/request.json",
        r"C:\private\workspace": "/mnt/c/private/workspace",
        r"C:\temp\output": "/mnt/c/temp/output",
        r"D:\video\person.mp4": "/mnt/d/video/person.mp4",
        r"D:\video\person2.mp4": "/mnt/d/video/person2.mp4",
        r"C:\temp\stash.json": "/mnt/c/temp/stash.json",
    }
    return mapping[value]


def test_bridge_translates_only_bodyrig_path_flags():
    command = [
        "python",
        "/opt/bodyrig/sith_adapter.py",
        "--engine-config",
        "/opt/sith/config.yaml",
        "--bodyrig-request",
        r"C:\temp\request.json",
        "--bodyrig-workspace",
        r"C:\private\workspace",
        "--bodyrig-output",
        r"C:\temp\output",
        "--bodyrig-adapter",
        "sith-experimental",
        "--bodyrig-revision",
        "abc123",
        "--bodyrig-source",
        r"D:\video\person.mp4",
    ]
    translated = translate_bodyrig_paths(command, _convert)
    assert translated == [
        "python",
        "/opt/bodyrig/sith_adapter.py",
        "--engine-config",
        "/opt/sith/config.yaml",
        "--bodyrig-request",
        "/mnt/c/temp/request.json",
        "--bodyrig-workspace",
        "/mnt/c/private/workspace",
        "--bodyrig-output",
        "/mnt/c/temp/output",
        "--bodyrig-adapter",
        "sith-experimental",
        "--bodyrig-revision",
        "abc123",
        "--bodyrig-source",
        "/mnt/d/video/person.mp4",
    ]


def test_bridge_translates_observation_source_and_manifest_paths():
    command = [
        "python",
        "/opt/bodyrig/opencv_observation_analyzer.py",
        "--bodyrig-stash-manifest",
        r"C:\temp\stash.json",
        "--bodyrig-source-id",
        "s001",
        "--bodyrig-source-path",
        r"D:\video\person2.mp4",
    ]
    translated = translate_bodyrig_paths(command, _convert)
    assert translated == [
        "python",
        "/opt/bodyrig/opencv_observation_analyzer.py",
        "--bodyrig-stash-manifest",
        "/mnt/c/temp/stash.json",
        "--bodyrig-source-id",
        "s001",
        "--bodyrig-source-path",
        "/mnt/d/video/person2.mp4",
    ]


def test_expand_subst_path_uses_backing_local_drive():
    def fake_query(drive: str) -> str | None:
        assert drive == "E:"
        return r"\??\C:\BodyRigRemote\E"

    assert expand_subst_path(r"E:\VR\clip.mp4", query=fake_query) == r"C:\BodyRigRemote\E\VR\clip.mp4"


def test_expand_subst_path_leaves_physical_drive_mapping_unchanged():
    def fake_query(drive: str) -> str | None:
        assert drive == "E:"
        return r"\Device\HarddiskVolume9"

    assert expand_subst_path(r"E:\VR\clip.mp4", query=fake_query) == r"E:\VR\clip.mp4"


def test_build_wsl_invocation_never_inserts_shell():
    invocation = build_wsl_invocation(
        wsl_exe="wsl.exe",
        distribution="Ubuntu-24.04",
        linux_command=[
            "--",
            "python",
            "/opt/bodyrig/adapter.py",
            "--bodyrig-request",
            r"C:\temp\request.json",
        ],
        converter=_convert,
    )
    assert invocation == [
        "wsl.exe",
        "-d",
        "Ubuntu-24.04",
        "--",
        "python",
        "/opt/bodyrig/adapter.py",
        "--bodyrig-request",
        "/mnt/c/temp/request.json",
    ]
    assert "-c" not in invocation


@pytest.mark.parametrize("shell", ["bash", "sh", "zsh", "pwsh", "cmd.exe"])
def test_bridge_rejects_explicit_shell_commands(shell: str):
    with pytest.raises(WslBridgeError, match="may not invoke a command shell"):
        validate_linux_command([shell, "-c", "anything"])


def test_bridge_rejects_missing_path_flag_value():
    with pytest.raises(WslBridgeError, match="missing value"):
        translate_bodyrig_paths(["python", "adapter.py", "--bodyrig-output"], _convert)


def test_bridge_rejects_converter_newline_injection():
    with pytest.raises(WslBridgeError, match="invalid WSL path"):
        translate_bodyrig_paths(
            ["python", "adapter.py", "--bodyrig-output", r"C:\temp\output"],
            lambda _: "/mnt/c/output\nmalicious",
        )
