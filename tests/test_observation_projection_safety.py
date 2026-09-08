from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import observation_cli
from bodyrig.projection_safety import (
    is_projection_ambiguous_geometry,
    projection_ambiguous_manifest_entries,
)


def _manifest(tmp_path: Path, *, width: int, height: int) -> Path:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fixture")
    payload = {
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "source_kind": "stash-local",
        "performer": {"id": "7", "name": "Alice", "disambiguation": ""},
        "stash_version": "test",
        "candidate_count": 1,
        "selected": [
            {
                "scene_id": "1",
                "scene_title": "Source",
                "path": str(video),
                "width": width,
                "height": height,
                "duration": 60.0,
                "framerate": 30.0,
                "performer_count": 1,
                "score": 100.0,
            }
        ],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_projection_helper_preserves_flat_16x9_and_flags_real_two_to_one_geometry():
    assert not is_projection_ambiguous_geometry(3840, 2160)
    assert is_projection_ambiguous_geometry(8192, 4096)
    assert is_projection_ambiguous_geometry(5120, 2560)
    assert is_projection_ambiguous_geometry(4320, 2160)


@pytest.mark.parametrize("width,height", [(8192, 4096), (5120, 2560), (4320, 2160)])
def test_canonical_observation_cli_rejects_stale_projection_ambiguous_manifest_before_analyzer(
    tmp_path: Path,
    capsys,
    width: int,
    height: int,
):
    source_manifest = _manifest(tmp_path, width=width, height=height)
    workspace = tmp_path / "workspace"

    result = observation_cli.main(
        [
            str(source_manifest),
            "--config",
            str(tmp_path / "must-not-be-read.json"),
            "--workspace",
            str(workspace),
            "--selection-out",
            str(tmp_path / "selection.json"),
            "--segments-out",
            str(tmp_path / "segments.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "projection-ambiguous" in captured.err
    assert not workspace.exists()


def test_manifest_projection_scan_is_metadata_only_and_returns_indexes(tmp_path: Path):
    source_manifest = _manifest(tmp_path, width=3840, height=2160)
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    assert projection_ambiguous_manifest_entries(payload) == []
    payload["selected"][0]["width"] = 8192
    payload["selected"][0]["height"] = 4096
    assert projection_ambiguous_manifest_entries(payload) == [0]
