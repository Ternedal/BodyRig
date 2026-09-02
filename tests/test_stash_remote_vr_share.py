from __future__ import annotations

import os
from types import SimpleNamespace

import bodyrig.stash_cli as stash_cli
from bodyrig.stash_cli import _auto_remote_vr_path


def _windows_os(*, isfile):
    return SimpleNamespace(
        name="nt",
        path=SimpleNamespace(join=os.path.join, isfile=isfile),
    )


def test_remote_stash_e_vr_maps_to_same_host_vr_e_share(monkeypatch) -> None:
    expected = r"\\192.168.1.42\VR_E\All Anal VR\clip.mp4"
    monkeypatch.setattr(stash_cli, "os", _windows_os(isfile=lambda value: value == expected))

    mapped = _auto_remote_vr_path(
        r"E:\VR\All Anal VR\clip.mp4",
        stash_url="http://192.168.1.42:9998",
    )

    assert mapped == expected


def test_remote_stash_f_vr_maps_to_vr_f_share(monkeypatch) -> None:
    expected = r"\\192.168.1.42\VR_F\Studio\scene.mkv"
    monkeypatch.setattr(stash_cli, "os", _windows_os(isfile=lambda value: value == expected))

    mapped = _auto_remote_vr_path(
        r"F:\VR\Studio\scene.mkv",
        stash_url="http://192.168.1.42:9998",
    )

    assert mapped == expected


def test_remote_stash_auto_map_fails_closed_when_share_path_is_not_readable(monkeypatch) -> None:
    monkeypatch.setattr(stash_cli, "os", _windows_os(isfile=lambda _value: False))
    original = r"E:\VR\missing.mp4"

    assert _auto_remote_vr_path(original, stash_url="http://192.168.1.42:9998") == original


def test_non_vr_drive_path_is_never_guessed(monkeypatch) -> None:
    monkeypatch.setattr(stash_cli, "os", _windows_os(isfile=lambda _value: True))
    original = r"E:\Other\clip.mp4"

    assert _auto_remote_vr_path(original, stash_url="http://192.168.1.42:9998") == original
