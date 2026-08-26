from __future__ import annotations

import subprocess

import pytest

import bodyrig.wsl_adapter_bridge as bridge
from bodyrig.wsl_adapter_bridge import (
    WslBridgeError,
    build_wsl_invocation,
    expand_subst_path,
    make_wsl_path_converter,
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


def test_make_wsl_path_converter_escapes_backslashes_before_wslpath(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="/mnt/c/temp/request.json\n", stderr="")

    monkeypatch.setattr(bridge, "expand_subst_path", lambda path: path)
    monkeypatch.setattr(bridge, "resolve_windows_reparse_path", lambda path: path)
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    converter = make_wsl_path_converter("wsl.exe", "Ubuntu-22.04")

    assert converter(r"C:\temp\request.json") == "/mnt/c/temp/request.json"
    assert calls == [[
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "wslpath",
        "-a",
        "-u",
        r"C:\\temp\\request.json",
    ]]


def test_split_unc_path_preserves_share_root_and_suffix():
    assert bridge.split_unc_path(r"\\192.168.1.20\VR_E\MilfVR\clip.mp4") == (
        r"\\192.168.1.20\VR_E",
        r"MilfVR\clip.mp4",
    )
    assert bridge.split_unc_path(r"C:\VR\clip.mp4") is None


def test_make_wsl_path_converter_routes_resolved_unc_through_drvfs_mount(monkeypatch):
    mount_calls = []

    monkeypatch.setattr(bridge, "expand_subst_path", lambda path: r"C:\BodyRigRemote\E\VR\MilfVR\clip.mp4")
    monkeypatch.setattr(
        bridge,
        "resolve_windows_reparse_path",
        lambda path: r"\\192.168.1.20\VR_E\MilfVR\clip.mp4",
    )

    def fake_mount(wsl_exe: str, distribution: str, unc_root: str) -> str:
        mount_calls.append((wsl_exe, distribution, unc_root))
        return "/mnt/bodyrig/VR_E"

    monkeypatch.setattr(bridge, "ensure_wsl_unc_mount", fake_mount)
    converter = make_wsl_path_converter("wsl.exe", "Ubuntu-22.04")

    assert converter(r"E:\VR\MilfVR\clip.mp4") == "/mnt/bodyrig/VR_E/MilfVR/clip.mp4"
    assert mount_calls == [("wsl.exe", "Ubuntu-22.04", r"\\192.168.1.20\VR_E")]


def test_ensure_wsl_unc_mount_reuses_existing_operator_mount(monkeypatch):
    calls = []

    def fake_run(command):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="/mnt/bodyrig/VR_E\n", stderr="")

    monkeypatch.setattr(bridge, "_run_wsl_capture", fake_run)

    assert bridge.ensure_wsl_unc_mount(
        "wsl.exe",
        "Ubuntu-22.04",
        r"\\192.168.1.20\VR_E",
    ) == "/mnt/bodyrig/VR_E"
    assert calls == [[
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/usr/bin/findmnt",
        "-rn",
        "-S",
        r"\\\\192.168.1.20\\VR_E",
        "-o",
        "TARGET",
    ]]


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
