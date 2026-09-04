from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from bodyrig.observation import (
    Observation,
    ObservationError,
    build_selection_manifest,
    load_stash_source_manifest,
    materialize_segments,
    run_external_analyzer,
    select_observations,
    validate_analyzer_result,
)


def _source_manifest(tmp_path: Path) -> Path:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    manifest = {
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "source_kind": "stash-local",
        "performer": {"id": "7", "name": "Alice", "disambiguation": ""},
        "stash_version": "test",
        "candidate_count": 2,
        "selected": [
            {
                "scene_id": "11",
                "scene_title": "One",
                "path": str(first),
                "width": 1920,
                "height": 1080,
                "duration": 60.0,
                "framerate": 30.0,
                "performer_count": 1,
                "score": 100.0,
            },
            {
                "scene_id": "12",
                "scene_title": "Two",
                "path": str(second),
                "width": 3840,
                "height": 2160,
                "duration": 80.0,
                "framerate": 60.0,
                "performer_count": 1,
                "score": 120.0,
            },
        ],
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _observation(source_id: str, start: float, *, view: str, face: float, body: float, score_bias: float = 0.0) -> Observation:
    target_confidence = 0.9
    target_screen_fraction = 0.7
    sharpness = min(1.0, 0.8 + score_bias)
    occlusion = 0.1
    motion = 0.5
    positive = (
        0.24 * target_confidence
        + 0.12 * target_screen_fraction
        + 0.17 * face
        + 0.17 * body
        + 0.18 * sharpness
        + 0.12 * motion
    )
    base_score = max(0.0, min(1.0, positive - 0.22 * occlusion))
    return Observation(
        source_id=source_id,
        start_seconds=start,
        duration_seconds=6.0,
        target_confidence=target_confidence,
        target_screen_fraction=target_screen_fraction,
        face_visibility=face,
        full_body_visibility=body,
        sharpness=sharpness,
        occlusion=occlusion,
        motion=motion,
        view=view,
        base_score=base_score,
    )


def test_external_analyzer_keeps_source_paths_out_of_request_json(tmp_path: Path):
    source_manifest = _source_manifest(tmp_path)
    _, sources, source_sha = load_stash_source_manifest(source_manifest)
    script = tmp_path / "adapter.py"
    script.write_text(
        r'''
import argparse, json, pathlib
p=argparse.ArgumentParser()
p.add_argument('--bodyrig-request', required=True)
p.add_argument('--bodyrig-workspace', required=True)
p.add_argument('--bodyrig-output', required=True)
p.add_argument('--bodyrig-adapter', required=True)
p.add_argument('--bodyrig-revision', required=True)
p.add_argument('--bodyrig-source-id', action='append', default=[])
p.add_argument('--bodyrig-source-path', action='append', default=[])
a=p.parse_args()
raw=pathlib.Path(a.bodyrig_request).read_text(encoding='utf-8')
for source_path in a.bodyrig_source_path:
    assert source_path not in raw
request=json.loads(raw)
assert request['performer_id']=='7'
rows=[]
for i, source_id in enumerate(a.bodyrig_source_id):
    rows.append({
      'source_id': source_id,
      'start_seconds': 5.0+i,
      'duration_seconds': 6.0,
      'target_confidence': 0.95,
      'target_screen_fraction': 0.7,
      'face_visibility': 0.85 if i == 0 else 0.45,
      'full_body_visibility': 0.6 if i == 0 else 0.9,
      'sharpness': 0.9,
      'occlusion': 0.05,
      'motion': 0.5,
      'view': 'front' if i == 0 else 'left_profile',
    })
out=pathlib.Path(a.bodyrig_output)
(out/'observations.json').write_text(json.dumps({
  'format':'bodyrig-observation-analyzer-result','version':1,
  'adapter':a.bodyrig_adapter,'revision':a.bodyrig_revision,'observations':rows
}), encoding='utf-8')
''',
        encoding="utf-8",
    )
    workspace = tmp_path / "private"
    workspace.mkdir()
    observations = run_external_analyzer(
        [sys.executable, str(script)],
        sources=sources,
        performer_id="7",
        source_manifest_sha256=source_sha,
        workspace=workspace,
        adapter="fixture-analyzer",
        revision="r1",
    )
    assert len(observations) == 2
    assert {item.source_id for item in observations} == {"s001", "s002"}


def test_analyzer_result_rejects_unknown_source_and_out_of_bounds_window(tmp_path: Path):
    source_manifest = _source_manifest(tmp_path)
    _, sources, _ = load_stash_source_manifest(source_manifest)
    result = tmp_path / "observations.json"
    payload = {
        "format": "bodyrig-observation-analyzer-result",
        "version": 1,
        "adapter": "fixture",
        "revision": "r1",
        "observations": [
            {
                "source_id": "s999",
                "start_seconds": 0,
                "duration_seconds": 5,
                "target_confidence": 1,
                "target_screen_fraction": 1,
                "face_visibility": 1,
                "full_body_visibility": 1,
                "sharpness": 1,
                "occlusion": 0,
                "motion": 1,
                "view": "front",
            }
        ],
    }
    result.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ObservationError, match="unknown source_id"):
        validate_analyzer_result(result, sources=sources, expected_adapter="fixture", expected_revision="r1")

    payload["observations"][0]["source_id"] = "s001"
    payload["observations"][0]["start_seconds"] = 59
    result.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ObservationError, match="beyond source"):
        validate_analyzer_result(result, sources=sources, expected_adapter="fixture", expected_revision="r1")


def test_selection_rewards_view_and_scene_diversity_and_avoids_overlap():
    observations = [
        _observation("s001", 0, view="front", face=0.95, body=0.55, score_bias=0.15),
        _observation("s001", 1, view="front", face=0.94, body=0.54, score_bias=0.14),
        _observation("s002", 10, view="left_profile", face=0.75, body=0.8),
        _observation("s002", 30, view="rear", face=0.1, body=0.95),
    ]
    selected = select_observations(observations, max_segments=3, min_base_score=0.2, max_per_source=2)
    assert len(selected) == 3
    assert {item.view for item in selected} == {"front", "left_profile", "rear"}
    assert not ({0.0, 1.0} <= {item.start_seconds for item in selected})


def test_materialize_segments_is_create_only_hashes_bytes_and_removes_workspace_on_failure(tmp_path: Path):
    source_manifest = _source_manifest(tmp_path)
    _, sources, source_sha = load_stash_source_manifest(source_manifest)
    selected = [
        _observation("s001", 2, view="front", face=0.9, body=0.7),
        _observation("s002", 4, view="left_profile", face=0.7, body=0.9),
    ]
    selection = build_selection_manifest(
        source_manifest_sha256=source_sha,
        adapter="fixture",
        revision="r1",
        sources=sources,
        selected=selected,
    )
    calls = []

    def fake_runner(argv: list[str]) -> int:
        calls.append(argv)
        output = Path(argv[-1])
        output.write_bytes(("segment:" + output.name).encode())
        return 0

    workspace = tmp_path / "segments"
    manifest = materialize_segments(sources=sources, selection_manifest=selection, workspace=workspace, runner=fake_runner)
    assert manifest["format"] == "bodyrig-observation-segments"
    assert len(manifest["segments"]) == 2
    assert all(Path(item["path"]).is_file() for item in manifest["segments"])
    for item in manifest["segments"]:
        assert item["sha256"] == hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
    assert all("-an" in call and "-c:v" in call and "libx264" in call for call in calls)
    with pytest.raises(ObservationError, match="already exists"):
        materialize_segments(sources=sources, selection_manifest=selection, workspace=workspace, runner=fake_runner)

    failed_workspace = tmp_path / "failed-segments"

    def failing_runner(argv: list[str]) -> int:
        return 2

    with pytest.raises(ObservationError, match="FFmpeg failed"):
        materialize_segments(sources=sources, selection_manifest=selection, workspace=failed_workspace, runner=failing_runner)
    assert not failed_workspace.exists()


def test_selection_rejects_only_low_quality_observations():
    poor = Observation(
        source_id="s001",
        start_seconds=0,
        duration_seconds=5,
        target_confidence=0.1,
        target_screen_fraction=0.1,
        face_visibility=0.1,
        full_body_visibility=0.1,
        sharpness=0.1,
        occlusion=0.9,
        motion=0.1,
        view="unknown",
        base_score=0.0,
    )
    with pytest.raises(ObservationError, match="minimum quality"):
        select_observations([poor])
