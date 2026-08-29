from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.stash_cli import _path_map_rules, _remap_scene_paths, _remap_source_path
from bodyrig.stash_source import StashSourceError, rank_sources


def test_path_map_rewrites_windows_drive_prefix_to_local_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "vr-e"
    target.mkdir()
    video = target / "Uidentificerede" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"fixture")

    monkeypatch.setenv(
        "BODYRIG_STASH_PATH_MAP",
        json.dumps({r"E:\VR": str(target)}),
    )

    rules = _path_map_rules()
    mapped = _remap_source_path(r"E:\VR\Uidentificerede\clip.mp4", rules)
    assert Path(mapped) == video


def test_scene_remap_makes_server_local_stash_path_rankable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "vr-f"
    target.mkdir()
    video = target / "VRHush" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"fixture")

    monkeypatch.setenv(
        "BODYRIG_STASH_PATH_MAP",
        json.dumps({r"F:\VR": str(target)}),
    )

    scenes = [
        {
            "id": "1",
            "title": "Mapped",
            "files": [
                {
                    "path": r"F:\VR\VRHush\clip.mp4",
                    "width": 1920,
                    "height": 1080,
                    "duration": 120,
                    "frame_rate": 30,
                }
            ],
            "tags": [],
            "performers": [{"id": "42", "name": "Lauren Phillips"}],
        }
    ]

    mapped = _remap_scene_paths(scenes)
    ranked = rank_sources(mapped, performer_id="42", max_sources=10, require_local=True)

    assert len(ranked) == 1
    assert Path(ranked[0].path) == video.resolve()
    assert scenes[0]["files"][0]["path"] == r"F:\VR\VRHush\clip.mp4"


def test_longest_path_prefix_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "BODYRIG_STASH_PATH_MAP",
        json.dumps({r"E:\VR": r"X:\broad", r"E:\VR\Special": r"Y:\specific"}),
    )
    rules = _path_map_rules()
    mapped = _remap_source_path(r"E:\VR\Special\clip.mp4", rules)
    assert mapped.casefold().startswith(r"Y:\specific".casefold())


def test_invalid_path_map_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BODYRIG_STASH_PATH_MAP", "not-json")
    with pytest.raises(StashSourceError, match="BODYRIG_STASH_PATH_MAP"):
        _path_map_rules()
