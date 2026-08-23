from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.sith_prepare as prepare
from bodyrig.sith_input import stage_sith_input


def _png(width: int, height: int, tail: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + tail


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "identity-workspace"
    capture = workspace / "identity-capture"
    capture.mkdir(parents=True)
    rgb = capture / "primary-rgb.png"
    rgba = capture / "primary-rgba.png"
    rgb.write_bytes(_png(1280, 1920, b"rgb"))
    rgba.write_bytes(_png(1280, 1920, b"rgba"))
    manifest = {
        "format": "bodyrig-private-identity-capture",
        "version": 1,
        "adapter": "opencv-identity-rgba",
        "revision": "1",
        "subject_track_id": "s00-t7",
        "primary": {
            "rgb": "primary-rgb.png",
            "rgba": "primary-rgba.png",
            "rgb_sha256": hashlib.sha256(rgb.read_bytes()).hexdigest(),
            "rgba_sha256": hashlib.sha256(rgba.read_bytes()).hexdigest(),
            "source_index": 0,
            "time_seconds": 1.25,
            "foreground_fraction": 0.42,
        },
    }
    (capture / "capture.json").write_text(json.dumps(manifest), encoding="utf-8")
    stage_sith_input(workspace)
    return workspace


def _points(count: int, confidence: float = 0.9) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend((100.0 + index, 200.0 + index, confidence))
    return values


def _openpose_payload(*, people: int = 1, body_confidence: float = 0.9) -> dict:
    person = {
        "pose_keypoints_2d": _points(25, body_confidence),
        "hand_left_keypoints_2d": _points(21),
        "hand_right_keypoints_2d": _points(21),
        "face_keypoints_2d": _points(70),
    }
    return {"version": 1.3, "people": [dict(person) for _ in range(people)]}


def test_validate_openpose_requires_exact_one_person_and_useful_keypoints(tmp_path: Path):
    path = tmp_path / "keypoints.json"
    path.write_text(json.dumps(_openpose_payload()), encoding="utf-8")
    quality = prepare.validate_openpose_result(path)
    assert quality == {
        "body_confident": 25,
        "left_hand_confident": 21,
        "right_hand_confident": 21,
        "face_confident": 70,
    }

    path.write_text(json.dumps(_openpose_payload(people=2)), encoding="utf-8")
    with pytest.raises(prepare.SithPrepareError, match="exactly one person"):
        prepare.validate_openpose_result(path)

    path.write_text(json.dumps(_openpose_payload(body_confidence=0.01)), encoding="utf-8")
    with pytest.raises(prepare.SithPrepareError, match="insufficient confident BODY_25"):
        prepare.validate_openpose_result(path)


def test_load_stage_rebinds_to_original_private_capture(tmp_path: Path):
    workspace = _workspace(tmp_path)
    stage, manifest, stage_sha = prepare.load_stage(workspace)
    assert stage.name == "sith-input-v1"
    assert manifest["subject_track_id"] == "s00-t7"
    assert len(stage_sha) == 64

    capture_path = workspace / "identity-capture" / "capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["primary"]["time_seconds"] = 2.0
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(prepare.SithPrepareError, match="not bound to the current private capture"):
        prepare.load_stage(workspace)


def test_prepare_runs_pinned_centralizer_then_hardened_openpose(monkeypatch, tmp_path: Path):
    workspace = _workspace(tmp_path)
    stage = workspace / "sith-input-v1"
    commands = []

    monkeypatch.setattr(prepare, "verify_sith_authority", lambda **kwargs: None)
    monkeypatch.setattr(prepare, "_linux_path", lambda path, **kwargs: "/mnt/c/private/sith-input-v1")

    def fake_checked_wsl(*, command, label, **kwargs):
        command = list(command)
        commands.append((label, command))
        if label == "SiTH RGBA centralization":
            (stage / "images" / "000.png").write_bytes(_png(1024, 1024, b"centralized"))
            return ""
        if label == "SiTH OpenPose keypoint extraction":
            (stage / "images" / "000_keypoints.json").write_text(
                json.dumps(_openpose_payload()), encoding="utf-8"
            )
            return ""
        raise AssertionError(f"unexpected command label: {label}")

    monkeypatch.setattr(prepare, "_checked_wsl", fake_checked_wsl)
    result = prepare.prepare_sith_input(
        workspace=workspace,
        distribution="Ubuntu-22.04",
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
    )

    centralizer = commands[0][1]
    assert centralizer[:2] == [
        "/opt/sith/.venv/bin/python",
        "/opt/sith/tools/centralize_rgba.py",
    ]
    assert centralizer[-4:] == ["--ratio", "0.85", "--size", "1024"]

    openpose = commands[1][1]
    assert openpose[0] == "/opt/openpose/build/examples/openpose/openpose.bin"
    assert openpose[openpose.index("--model_pose") + 1] == "BODY_25"
    assert openpose[openpose.index("--model_folder") + 1] == "/opt/openpose/models"
    assert openpose[openpose.index("--number_people_max") + 1] == "1"
    assert "--hand" in openpose and "--face" in openpose

    prep_path = stage / "prep.json"
    assert prep_path.is_file()
    persisted = json.loads(prep_path.read_text(encoding="utf-8"))
    assert persisted == result
    assert persisted["sith_revision"] == prepare.SITH_REVISION
    assert persisted["centralizer_blob"] == prepare.SITH_CENTRALIZE_RGBA_BLOB
    assert "workspace" not in json.dumps(persisted).lower()
    assert persisted["openpose_quality"]["body_confident"] == 25


def test_prepare_rejects_nonstandard_openpose_layout():
    with pytest.raises(prepare.SithPrepareError, match="standard"):
        prepare._openpose_model_root("/opt/openpose/openpose.bin")
