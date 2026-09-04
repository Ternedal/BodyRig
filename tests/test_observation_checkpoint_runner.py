from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.observation_runner as runner
from bodyrig.observation import Observation


def _observation(source_id: str) -> Observation:
    return Observation(
        source_id=source_id,
        start_seconds=10.0,
        duration_seconds=6.0,
        target_confidence=0.9,
        target_screen_fraction=0.5,
        face_visibility=0.8,
        full_body_visibility=0.7,
        sharpness=0.9,
        occlusion=0.1,
        motion=0.2,
        view="front",
        base_score=0.75,
    )


def test_builtin_runner_checkpoints_each_source_and_reuses_across_fresh_workspace(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"video")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "performer": {"id": "42"},
                "selected": [{"scene_id": "scene-1", "performer_count": 1}],
            }
        ),
        encoding="utf-8",
    )
    command = ["python", "bridge.py", "--bodyrig-stash-manifest", str(manifest)]
    sources = [{"source_id": "s001", "scene_id": "scene-1", "path": str(source_file), "duration": 100.0}]
    calls = []

    def fake_run_single_source(*args, **kwargs):
        calls.append(kwargs["source"]["source_id"])
        return [_observation(str(kwargs["source"]["source_id"]))]

    monkeypatch.setattr(runner, "_run_single_source", fake_run_single_source)

    workspace1 = tmp_path / "workspace-1"
    workspace1.mkdir()
    first = runner._run_checkpointed_builtin(
        command,
        sources=sources,
        performer_id="42",
        source_manifest_sha256="a" * 64,
        workspace=workspace1,
        adapter="opencv-hog-haar",
        revision="1",
        timeout_seconds=7200,
    )
    assert first is not None and len(first) == 1
    assert calls == ["s001"]

    workspace2 = tmp_path / "workspace-2"
    workspace2.mkdir()

    def must_not_run(*args, **kwargs):
        raise AssertionError("checkpoint miss on unchanged source")

    monkeypatch.setattr(runner, "_run_single_source", must_not_run)
    second_sources = [{"source_id": "s007", "scene_id": "scene-1", "path": str(source_file), "duration": 100.0}]
    second = runner._run_checkpointed_builtin(
        command,
        sources=second_sources,
        performer_id="42",
        source_manifest_sha256="b" * 64,
        workspace=workspace2,
        adapter="opencv-hog-haar",
        revision="1",
        timeout_seconds=7200,
    )
    assert second is not None and len(second) == 1
    assert second[0].source_id == "s007"


def test_checkpoint_is_invalidated_when_source_bytes_change(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"first")
    source = {"source_id": "s001", "scene_id": "scene-1", "path": str(source_file), "duration": 100.0}
    before = runner._source_fingerprint(
        source=source,
        performer_id="42",
        performer_count=1,
        adapter="opencv-hog-haar",
        revision="1",
    )
    source_file.write_bytes(b"second-and-different")
    after = runner._source_fingerprint(
        source=source,
        performer_id="42",
        performer_count=1,
        adapter="opencv-hog-haar",
        revision="1",
    )
    assert before != after


def test_builtin_source_timeout_is_never_the_old_two_hour_whole_run_limit() -> None:
    assert runner._BUILTIN_SOURCE_TIMEOUT_SECONDS == 86_400
    assert runner._BUILTIN_SOURCE_TIMEOUT_SECONDS > 7200
