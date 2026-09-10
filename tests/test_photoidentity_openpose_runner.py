from __future__ import annotations

import json
from pathlib import Path

from bodyrig import photoidentity_openpose_runner as runner


def _row(scene: str, ordinal: int, start: float, *, face: float, body: float, sharpness: float = 0.95) -> dict:
    return {
        "scene_id": scene,
        "source_ordinal": ordinal,
        "start_seconds": start,
        "duration_seconds": 6.0,
        "target_confidence": 0.95,
        "target_screen_fraction": 0.5,
        "face_visibility": face,
        "full_body_visibility": body,
        "sharpness": sharpness,
        "occlusion": 0.05,
        "motion": 0.1,
        "view": "front",
    }


def _points(count: int, confidence: float, *, x0: float, y0: float, step: float) -> list[float]:
    result: list[float] = []
    for index in range(count):
        result.extend([x0 + step * index, y0 + step * (index % 3), confidence])
    return result


def _payload() -> dict:
    body = _points(25, 0.95, x0=100.0, y0=200.0, step=15.0)
    for point_index, (x, y) in {
        19: (400.0, 900.0), 20: (475.0, 900.0), 21: (410.0, 840.0),
        22: (900.0, 900.0), 23: (975.0, 900.0), 24: (910.0, 840.0),
    }.items():
        body[point_index * 3] = x
        body[point_index * 3 + 1] = y
    face = _points(70, 0.95, x0=400.0, y0=180.0, step=4.0)
    for offset, point_index in enumerate(range(36, 42)):
        face[point_index * 3] = 500.0 + offset * 12.0
        face[point_index * 3 + 1] = 260.0
    for offset, point_index in enumerate(range(42, 48)):
        face[point_index * 3] = 620.0 + offset * 12.0
        face[point_index * 3 + 1] = 260.0
    return {
        "people": [{
            "pose_keypoints_2d": body,
            "hand_left_keypoints_2d": _points(21, 0.95, x0=260.0, y0=520.0, step=10.0),
            "hand_right_keypoints_2d": _points(21, 0.95, x0=900.0, y0=520.0, step=10.0),
            "face_keypoints_2d": face,
        }]
    }


def test_candidate_selector_keeps_face_best_and_body_best_per_scene() -> None:
    rows = [
        _row("a", 1, 0.0, face=0.95, body=0.50),
        _row("a", 1, 10.0, face=0.50, body=0.97),
        _row("a", 1, 20.0, face=0.30, body=0.30),
        _row("b", 2, 0.0, face=0.90, body=0.90),
    ]
    selected = runner.select_detail_frame_candidates(rows)
    by_scene = {}
    for row in selected:
        by_scene.setdefault(row["scene_id"], []).append(row)
    assert len(by_scene["a"]) == 2
    assert {row["start_seconds"] for row in by_scene["a"]} == {0.0, 10.0}
    assert len(by_scene["b"]) == 1


def test_runner_stops_after_two_distinct_scenes_prove_all_supported_details(monkeypatch, tmp_path: Path) -> None:
    source1 = tmp_path / "one.mp4"
    source2 = tmp_path / "two.mp4"
    source3 = tmp_path / "three.mp4"
    for path in (source1, source2, source3):
        path.write_bytes(b"x")

    extracted: list[Path] = []

    def fake_extract(*, ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
        del ffmpeg, source, timestamp
        output.parent.mkdir(parents=True, exist_ok=True)
        # Minimal valid PNG header with 1920x1080 IHDR dimensions; runner only
        # reads the first 24 bytes in this unit test.
        output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1920).to_bytes(4, "big") + (1080).to_bytes(4, "big"))
        extracted.append(output)

    monkeypatch.setattr(runner, "_extract_frame", fake_extract)
    monkeypatch.setattr(runner, "_run_openpose", lambda **kwargs: _payload())

    rows = [
        _row("scene-1", 1, 0.0, face=0.95, body=0.95),
        _row("scene-2", 2, 0.0, face=0.95, body=0.95),
        _row("scene-3", 3, 0.0, face=0.95, body=0.95),
    ]
    evidence = runner.collect_openpose_detail_evidence(
        rows=rows,
        sources_by_ordinal={
            1: {"scene_id": "scene-1", "path": str(source1)},
            2: {"scene_id": "scene-2", "path": str(source2)},
            3: {"scene_id": "scene-3", "path": str(source3)},
        },
        private_root=tmp_path / "private",
        ffmpeg="ffmpeg",
        distribution="Ubuntu-22.04",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        wsl_exe="wsl.exe",
    )

    assert set(evidence) == {"eyes_detail", "hands", "feet"}
    assert {item["scene_id"] for item in evidence["eyes_detail"]} == {"scene-1", "scene-2"}
    assert len(extracted) == 2
    serialized = json.dumps(evidence)
    assert str(source1) not in serialized
    assert str(source2) not in serialized
    assert str(source3) not in serialized


def test_model_root_requires_standard_pinned_openpose_layout() -> None:
    assert runner._openpose_model_root("/opt/openpose/build/examples/openpose/openpose.bin") == "/opt/openpose/models"
