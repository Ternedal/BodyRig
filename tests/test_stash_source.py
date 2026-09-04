from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.stash_source import (
    StashClient,
    StashConfig,
    StashGraphQLError,
    StashSourceError,
    build_source_manifest,
    rank_sources,
    write_source_manifest,
)


def _scene(
    scene_id: str,
    path: Path,
    *,
    performer_ids: tuple[str, ...] = ("7",),
    width: int = 1920,
    height: int = 1080,
    duration: float = 120.0,
    framerate: float = 30.0,
    tags: tuple[str, ...] = (),
) -> dict:
    return {
        "id": scene_id,
        "title": f"Scene {scene_id}",
        "files": [
            {
                "path": str(path),
                "basename": path.name,
                "width": width,
                "height": height,
                "duration": duration,
                "frame_rate": framerate,
                "video_codec": "h264",
                "size": 123,
            }
        ],
        "tags": [{"name": value} for value in tags],
        "performers": [{"id": value, "name": f"P{value}"} for value in performer_ids],
    }


def test_config_refuses_embedded_credentials_and_query():
    with pytest.raises(StashSourceError):
        StashConfig("http://user:pass@localhost:9999")
    with pytest.raises(StashSourceError):
        StashConfig("http://localhost:9999/?apikey=secret")


def test_search_performers_maps_minimal_fields():
    seen = {}

    def transport(query, variables):
        seen["query"] = query
        seen["variables"] = variables
        return {
            "findPerformers": {
                "performers": [
                    {"id": "7", "name": "Alice", "disambiguation": "A"},
                    {"id": "8", "name": "Bob", "disambiguation": None},
                ]
            }
        }

    client = StashClient(StashConfig("http://localhost:9999", api_key="secret"), transport=transport)
    result = client.search_performers("ali", limit=5)
    assert result == [
        {"id": "7", "name": "Alice", "disambiguation": "A"},
        {"id": "8", "name": "Bob", "disambiguation": ""},
    ]
    assert seen["variables"] == {"q": "ali", "limit": 5}
    assert "secret" not in seen["query"]


def test_scenes_for_performer_falls_back_to_legacy_schema(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fixture")
    calls = []

    def transport(query, variables):
        calls.append(query)
        if "performers: {value:" in query:
            raise StashGraphQLError("unknown field performers")
        return {"findScenes": {"count": 1, "scenes": [_scene("1", video)]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    scenes = client.scenes_for_performer("7")
    assert len(scenes) == 1
    assert len(calls) == 2
    assert "performer_id" in calls[1]


def test_rank_prefers_single_performer_high_quality_flat_video(tmp_path: Path):
    best = tmp_path / "best.mp4"
    multi = tmp_path / "multi.mp4"
    vr = tmp_path / "vr.mp4"
    low = tmp_path / "low.mp4"
    for path in (best, multi, vr, low):
        path.write_bytes(b"fixture")

    scenes = [
        _scene("best", best, width=3840, height=2160, framerate=60),
        _scene("multi", multi, performer_ids=("7", "8"), width=3840, height=2160, framerate=60),
        _scene("vr", vr, width=3840, height=2160, framerate=60, tags=("VR180", "SBS")),
        _scene("low", low, width=640, height=360, framerate=15),
    ]
    ranked = rank_sources(scenes, performer_id="7", max_sources=4)
    assert ranked[0].path == str(best.resolve())
    assert ranked[0].performer_count == 1
    assert ranked[-1].path == str(low.resolve())
    assert next(item for item in ranked if item.path == str(multi.resolve())).score < ranked[0].score
    assert next(item for item in ranked if item.path == str(vr.resolve())).score < ranked[0].score


def test_rank_rejects_wrong_performer_missing_files_and_deduplicates(tmp_path: Path):
    usable = tmp_path / "usable.mp4"
    usable.write_bytes(b"fixture")
    missing = tmp_path / "missing.mp4"
    scenes = [
        _scene("1", usable),
        _scene("2", usable, width=1280, height=720),
        _scene("3", missing),
        _scene("4", tmp_path / "wrong.mp4", performer_ids=("99",)),
    ]
    ranked = rank_sources(scenes, performer_id="7", max_sources=10)
    assert len(ranked) == 1
    assert ranked[0].scene_id == "1"


def test_manifest_is_build_only_and_contains_no_connection_secret(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fixture")
    selected = rank_sources([_scene("1", video)], performer_id="7", max_sources=1)
    manifest = build_source_manifest(
        performer={"id": "7", "name": "Alice", "disambiguation": ""},
        candidates=selected,
        stash_version="v0.30.1",
        candidate_count=1,
    )
    raw = json.dumps(manifest)
    assert manifest["format"] == "bodyrig-stash-source-manifest"
    assert manifest["source_kind"] == "stash-local"
    assert "apikey" not in raw.lower()
    assert "http://localhost:9999" not in raw
    assert manifest["selected"][0]["path"] == str(video.resolve())

    output = write_source_manifest(tmp_path / "sources.json", manifest)
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    with pytest.raises(StashSourceError):
        write_source_manifest(output, manifest)


def test_rank_requires_usable_local_source(tmp_path: Path):
    ranked = rank_sources([_scene("1", tmp_path / "missing.mp4")], performer_id="7")
    assert ranked == []
    with pytest.raises(StashSourceError, match="no usable"):
        build_source_manifest(
            performer={"id": "7", "name": "Alice"},
            candidates=ranked,
            stash_version="x",
            candidate_count=1,
        )
