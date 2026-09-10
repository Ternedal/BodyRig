from __future__ import annotations

from pathlib import Path

import bodyrig.photoidentity_source_universe as universe
from bodyrig.photoidentity_stash_inventory import PerformerSceneInventory


def _scene(
    scene_id: str,
    path: Path,
    *,
    performers: tuple[str, ...] = ("42",),
    width: int = 1920,
    height: int = 1080,
    tags: tuple[str, ...] = (),
) -> dict:
    return {
        "id": scene_id,
        "title": scene_id,
        "performers": [{"id": item, "name": item} for item in performers],
        "tags": [{"name": item} for item in tags],
        "files": [
            {
                "path": str(path),
                "width": width,
                "height": height,
                "duration": 60.0,
                "frame_rate": 30.0,
            }
        ],
    }


class _Client:
    def __init__(self, config) -> None:
        self.config = config

    def performer(self, performer_id: str) -> dict:
        return {"id": performer_id, "name": "Target", "disambiguation": ""}


def test_universe_separates_safe_single_multi_missing_and_projection_unsafe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe.mp4"
    multi = tmp_path / "multi.mp4"
    unsafe = tmp_path / "unsafe.mp4"
    safe.write_bytes(b"safe")
    multi.write_bytes(b"multi")
    unsafe.write_bytes(b"unsafe")
    missing = tmp_path / "missing.mp4"

    scenes = (
        _scene("single-safe", safe),
        _scene("single-missing", missing),
        _scene("single-vr", unsafe, width=4096, height=2048),
        _scene("multi", multi, performers=("42", "7")),
    )
    monkeypatch.setattr(universe, "StashClient", _Client)
    monkeypatch.setattr(
        universe,
        "fetch_exhaustive_performer_scenes",
        lambda *args, **kwargs: PerformerSceneInventory(scenes, 4, 2, 2, "current"),
    )
    monkeypatch.setattr(universe, "_remap_scene_paths", lambda values, stash_url: list(values))

    result = universe.audit_source_universe(
        performer_id="42",
        stash_url="http://localhost:9999",
        stash_api_key="secret",
    )

    assert result["stash_scene_count"] == 4
    assert result["stash_inventory_exhausted"] is True
    assert result["single_performer_scene_count"] == 3
    assert result["multi_performer_scene_count"] == 1
    assert result["single_performer_projection_safe_local_video_count"] == 1
    assert result["single_performer_missing_local_video_count"] == 1
    assert result["single_performer_projection_unsafe_video_count"] == 1
    assert result["multi_performer_projection_safe_local_video_count"] == 1
    assert result["multi_performer_identity_resolution_required"] is True
    assert result["performer_media_fully_identity_resolved"] is False
    assert result["biometric_identity_inference_used"] is False
    assert result["generic_guessing_permitted"] is False
    assert result["reconstruction_permitted"] is False
    assert result["human_review_render_permitted"] is False
    assert result["production_activation"] is False
    assert "secret" not in str(result)
    assert str(tmp_path) not in str(result)


def test_universe_can_prove_all_stash_scenes_are_single_performer(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    scenes = (_scene("a", first), _scene("b", second))
    monkeypatch.setattr(universe, "StashClient", _Client)
    monkeypatch.setattr(
        universe,
        "fetch_exhaustive_performer_scenes",
        lambda *args, **kwargs: PerformerSceneInventory(scenes, 2, 1, 250, "current"),
    )
    monkeypatch.setattr(universe, "_remap_scene_paths", lambda values, stash_url: list(values))

    result = universe.audit_source_universe(
        performer_id="42",
        stash_url="http://localhost:9999",
        stash_api_key="secret",
    )
    assert result["performer_media_fully_identity_resolved"] is True
    assert result["multi_performer_identity_resolution_required"] is False
    assert result["single_performer_projection_safe_local_video_count"] == 2


def test_universe_fails_if_inventory_scene_loses_target_binding(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "x.mp4"
    source.write_bytes(b"x")
    scenes = (_scene("wrong", source, performers=("7",)),)
    monkeypatch.setattr(universe, "StashClient", _Client)
    monkeypatch.setattr(
        universe,
        "fetch_exhaustive_performer_scenes",
        lambda *args, **kwargs: PerformerSceneInventory(scenes, 1, 1, 250, "current"),
    )
    monkeypatch.setattr(universe, "_remap_scene_paths", lambda values, stash_url: list(values))

    try:
        universe.audit_source_universe(
            performer_id="42",
            stash_url="http://localhost:9999",
            stash_api_key="secret",
        )
    except universe.PhotoIdentitySourceUniverseError as exc:
        assert "lost target performer binding" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected fail-closed target binding rejection")
