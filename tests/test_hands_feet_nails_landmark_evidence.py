from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.hands_feet_nails_landmark_evidence as evidence
from bodyrig.hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    build_landmark_evidence,
    validate_landmark_evidence,
)
from bodyrig.hands_feet_nails_source_capture import FORMAT as CAPTURE_FORMAT
from bodyrig.hands_feet_nails_source_capture import POLICY_REVISION as CAPTURE_POLICY_REVISION
from bodyrig.hands_feet_nails_source_capture import VERSION as CAPTURE_VERSION
from bodyrig.hands_feet_nails_source_capture import capture_dir

PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE = "hfncap-" + "2" * 32
SOURCE_REVISION = "3" * 40
EVIDENCE_REVISION = "4" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _points(count: int, *, base_x: float, base_y: float, spacing: float, confidence: float) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend([base_x + (index % 5) * spacing, base_y + (index // 5) * spacing, confidence])
    return values


def _payload(*, missing_left_pinky: bool = False) -> dict:
    body = _points(25, base_x=100.0, base_y=100.0, spacing=10.0, confidence=0.0)
    for index, point in {
        19: (300.0, 420.0),
        20: (360.0, 420.0),
        21: (330.0, 470.0),
        22: (700.0, 420.0),
        23: (760.0, 420.0),
        24: (730.0, 470.0),
    }.items():
        body[index * 3] = point[0]
        body[index * 3 + 1] = point[1]
        body[index * 3 + 2] = 0.95
    left = _points(21, base_x=200.0, base_y=200.0, spacing=20.0, confidence=0.95)
    if missing_left_pinky:
        left[20 * 3 + 2] = 0.0
    return {
        "people": [
            {
                "pose_keypoints_2d": body,
                "hand_left_keypoints_2d": left,
                "hand_right_keypoints_2d": _points(21, base_x=600.0, base_y=200.0, spacing=20.0, confidence=0.95),
            }
        ]
    }


def _fixture(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"exact-person-bound-source-media")
    source_sha = _sha(source)
    root = tmp_path / "library"
    capture_root = capture_dir(root, PERSON, BODY, CAPTURE)
    capture_root.mkdir(parents=True)

    specs = {
        "left_hand": ("scene-left-hand", 1000, [0.10, 0.20, 0.40, 0.60]),
        "right_hand": ("scene-right-hand", 2000, [0.55, 0.20, 0.40, 0.60]),
        "left_foot": ("scene-left-foot", 3000, [0.20, 0.70, 0.25, 0.30]),
        "right_foot": ("scene-right-foot", 4000, [0.65, 0.70, 0.25, 0.30]),
    }
    regions: dict[str, dict] = {}
    by_scene: dict[str, dict] = {}
    for region, (scene, timestamp, crop_norm) in specs.items():
        image = capture_root / f"{region.replace('_', '-')}.png"
        Image.new("RGB", (1024, 1024), (120, 110, 100)).save(image)
        regions[region] = {
            "scene_id": scene,
            "source_name": "source.mp4",
            "source_media_sha256": source_sha,
            "timestamp_ms": timestamp,
            "crop_norm": crop_norm,
            "image": image.name,
            "image_sha256": _sha(image),
            "width": 1024,
            "height": 1024,
        }
        by_scene[scene] = {
            "scene_id": scene,
            "name": "source.mp4",
            "sha256": source_sha,
            "path": str(source),
        }

    capture = {
        "format": CAPTURE_FORMAT,
        "version": CAPTURE_VERSION,
        "policy_revision": CAPTURE_POLICY_REVISION,
        "capture_id": CAPTURE,
        "person_id": PERSON,
        "body_revision": BODY,
        "bodyrig_revision": SOURCE_REVISION,
        "source_manifest_sha256": "5" * 64,
        "ffmpeg_version": "ffmpeg version source-capture-test",
        "regions": regions,
        "source_grounded": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    capture_manifest = capture_root / "source-capture.json"
    capture_manifest.write_text(json.dumps(capture, sort_keys=True) + "\n", encoding="utf-8")
    source_authority = {
        "manifest_sha256": "5" * 64,
        "by_scene": by_scene,
    }
    return capture, source_authority, root, source


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, capture: dict, source_authority: dict, *, missing_left_pinky: bool = False) -> None:
    monkeypatch.setattr(evidence, "read_source_capture", lambda *args, **kwargs: capture)
    monkeypatch.setattr(evidence, "_source_authority", lambda *args, **kwargs: source_authority)
    monkeypatch.setattr(evidence, "_ffmpeg_version", lambda ffmpeg: "ffmpeg version landmark-test")

    def fake_extract(*, ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
        del ffmpeg, source, timestamp
        Image.new("RGB", (1000, 500), (80, 90, 100)).save(output)

    monkeypatch.setattr(evidence, "_extract_frame", fake_extract)
    monkeypatch.setattr(evidence, "_run_openpose", lambda **kwargs: _payload(missing_left_pinky=missing_left_pinky))


def test_build_binds_person_body_capture_and_persists_no_private_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, source = _fixture(tmp_path)
    _patch_runtime(monkeypatch, capture, source_authority)

    result = build_landmark_evidence(
        root,
        PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        evidence_bodyrig_revision=EVIDENCE_REVISION,
        ffmpeg="ffmpeg",
        distribution="BodyRig",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
    )

    output = Path(result["manifest"])
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["person_id"] == PERSON
    assert persisted["body_revision"] == BODY
    assert persisted["capture_id"] == CAPTURE
    assert persisted["source_bodyrig_revision"] == SOURCE_REVISION
    assert persisted["evidence_bodyrig_revision"] == EVIDENCE_REVISION
    assert persisted["source_capture_sha256"] == _sha(capture_dir(root, PERSON, BODY, CAPTURE) / "source-capture.json")
    assert persisted["source_manifest_sha256"] == capture["source_manifest_sha256"]
    assert persisted["region_count"] == 4
    assert persisted["all_regions_application_ready"] is True
    assert persisted["package_application_authority"] is False
    assert persisted["production_activation"] is False
    assert persisted["regions"]["left_hand"]["semantic_region"] == "left_fingernails"
    assert persisted["regions"]["left_foot"]["semantic_region"] == "left_toenails"
    assert persisted["regions"]["left_hand"]["crop_px"] == [100, 100, 500, 400]
    text = output.read_text(encoding="utf-8")
    assert str(source) not in text
    assert str(root) not in text

    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="already exists"):
        build_landmark_evidence(
            root,
            PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            evidence_bodyrig_revision=EVIDENCE_REVISION,
            ffmpeg="ffmpeg",
            distribution="BodyRig",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        )


def test_incomplete_fingertip_evidence_is_preserved_but_not_application_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, _source = _fixture(tmp_path)
    _patch_runtime(monkeypatch, capture, source_authority, missing_left_pinky=True)
    result = build_landmark_evidence(
        root,
        PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        evidence_bodyrig_revision=EVIDENCE_REVISION,
        ffmpeg="ffmpeg",
        distribution="BodyRig",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
    )
    assert result["regions"]["left_hand"]["projection"]["observed_landmark_count"] == 4
    assert result["regions"]["left_hand"]["projection"]["application_ready"] is False
    assert result["all_regions_application_ready"] is False
    assert result["package_application_authority"] is False


def test_source_media_tamper_fails_before_frame_extraction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, source = _fixture(tmp_path)
    monkeypatch.setattr(evidence, "read_source_capture", lambda *args, **kwargs: capture)
    monkeypatch.setattr(evidence, "_source_authority", lambda *args, **kwargs: source_authority)
    monkeypatch.setattr(evidence, "_ffmpeg_version", lambda ffmpeg: "ffmpeg version landmark-test")
    source.write_bytes(b"tampered")
    called = False

    def fake_extract(**kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(evidence, "_extract_frame", fake_extract)
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="source media bytes changed"):
        build_landmark_evidence(
            root,
            PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            evidence_bodyrig_revision=EVIDENCE_REVISION,
            ffmpeg="ffmpeg",
            distribution="BodyRig",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        )
    assert called is False


def test_closeup_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, _source = _fixture(tmp_path)
    _patch_runtime(monkeypatch, capture, source_authority)
    closeup = capture_dir(root, PERSON, BODY, CAPTURE) / "left-hand.png"
    Image.new("RGB", (1024, 1024), (255, 0, 0)).save(closeup)
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="closeup bytes changed"):
        build_landmark_evidence(
            root,
            PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            evidence_bodyrig_revision=EVIDENCE_REVISION,
            ffmpeg="ffmpeg",
            distribution="BodyRig",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        )


def test_source_capture_boolean_v1_is_rejected_even_if_legacy_reader_returns_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, _source = _fixture(tmp_path)
    capture["version"] = True
    monkeypatch.setattr(evidence, "read_source_capture", lambda *args, **kwargs: capture)
    monkeypatch.setattr(evidence, "_source_authority", lambda *args, **kwargs: source_authority)
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="strict v1 authority"):
        build_landmark_evidence(
            root,
            PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            evidence_bodyrig_revision=EVIDENCE_REVISION,
            ffmpeg="ffmpeg",
            distribution="BodyRig",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        )


def test_validator_rejects_boolean_v1_and_authority_escalation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    capture, source_authority, root, _source = _fixture(tmp_path)
    _patch_runtime(monkeypatch, capture, source_authority)
    result = build_landmark_evidence(
        root,
        PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        evidence_bodyrig_revision=EVIDENCE_REVISION,
        ffmpeg="ffmpeg",
        distribution="BodyRig",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
    )
    value = {key: result[key] for key in evidence.TOP_FIELDS}
    assert validate_landmark_evidence(value)["all_regions_application_ready"] is True

    bad_version = dict(value)
    bad_version["version"] = True
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="format/version/identity mismatch"):
        validate_landmark_evidence(bad_version)

    elevated = dict(value)
    elevated["package_application_authority"] = True
    with pytest.raises(HandsFeetNailsLandmarkEvidenceError, match="evidence-only authority boundary"):
        validate_landmark_evidence(elevated)
