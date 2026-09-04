from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.observation_evidence import ObservationEvidenceError, build_observation_evidence


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_sha(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"source")
    source = {
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "source_kind": "stash-local",
        "performer": {"id": "7", "name": "Alice", "disambiguation": ""},
        "stash_version": "test",
        "candidate_count": 1,
        "selected": [{
            "scene_id": "11", "scene_title": "Scene", "path": str(source_video),
            "width": 1920, "height": 1080, "duration": 60.0, "framerate": 30.0,
            "performer_count": 1, "score": 100.0,
        }],
    }
    source_path = tmp_path / "source.json"
    _write_json(source_path, source)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

    selection = {
        "format": "bodyrig-observation-selection",
        "version": 1,
        "source_manifest_sha256": source_sha,
        "adapter": "fixture",
        "revision": "r1",
        "selected": [{
            "source_id": "s001", "scene_id": "11", "start_seconds": 2.0,
            "duration_seconds": 6.0, "target_confidence": 0.9,
            "target_screen_fraction": 0.5, "face_visibility": 0.8,
            "full_body_visibility": 0.8, "sharpness": 0.9, "occlusion": 0.0,
            "motion": 0.5, "view": "front", "base_score": 0.8,
        }],
    }
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)

    segment = tmp_path / "private" / "segment-01.mp4"
    segment.parent.mkdir()
    segment.write_bytes(b"private-segment")
    segment_sha = hashlib.sha256(segment.read_bytes()).hexdigest()
    segments = {
        "format": "bodyrig-observation-segments",
        "version": 1,
        "selection_sha256": _canonical_sha(selection),
        "segments": [{
            "source_id": "s001", "scene_id": "11", "path": str(segment),
            "start_seconds": 2.0, "duration_seconds": 6.0, "sha256": segment_sha,
        }],
    }
    segments_path = tmp_path / "segments.json"
    _write_json(segments_path, segments)
    return source_path, selection_path, segments_path, segment


def test_evidence_rehashes_chain_and_strips_private_paths(tmp_path: Path):
    source_path, selection_path, segments_path, segment = _fixture(tmp_path)
    evidence = build_observation_evidence(
        source_manifest_path=source_path,
        selection_path=selection_path,
        segments_path=segments_path,
    )
    raw = json.dumps(evidence)
    assert evidence["format"] == "bodyrig-observation-evidence"
    assert evidence["adapter"] == "fixture"
    assert evidence["segments"][0]["sha256"] == hashlib.sha256(segment.read_bytes()).hexdigest()
    assert str(segment) not in raw
    assert str(tmp_path) not in raw
    assert "path" not in evidence["segments"][0]


def test_evidence_rejects_selection_not_bound_to_source(tmp_path: Path):
    source_path, selection_path, segments_path, _ = _fixture(tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["source_manifest_sha256"] = "0" * 64
    _write_json(selection_path, selection)
    with pytest.raises(ObservationEvidenceError, match="not bound to this source"):
        build_observation_evidence(
            source_manifest_path=source_path,
            selection_path=selection_path,
            segments_path=segments_path,
        )


def test_evidence_rejects_segment_manifest_not_bound_to_selection(tmp_path: Path):
    source_path, selection_path, segments_path, _ = _fixture(tmp_path)
    segments = json.loads(segments_path.read_text(encoding="utf-8"))
    segments["selection_sha256"] = "0" * 64
    _write_json(segments_path, segments)
    with pytest.raises(ObservationEvidenceError, match="not bound to this selection"):
        build_observation_evidence(
            source_manifest_path=source_path,
            selection_path=selection_path,
            segments_path=segments_path,
        )


def test_evidence_rejects_segment_byte_tampering(tmp_path: Path):
    source_path, selection_path, segments_path, segment = _fixture(tmp_path)
    segment.write_bytes(b"tampered")
    with pytest.raises(ObservationEvidenceError, match="byte hash"):
        build_observation_evidence(
            source_manifest_path=source_path,
            selection_path=selection_path,
            segments_path=segments_path,
        )
